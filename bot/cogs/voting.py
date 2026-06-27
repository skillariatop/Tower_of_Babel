"""
/vote start  — open a new vote
/vote status — show current results
/vote close  — close early (Architect+ only)

Votes run as Discord polls in #voting. The bot tracks state in memory
(and eventually in the DB). On completion it writes a YAML file to
decisions/ and opens a PR.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Optional

import discord
import yaml
from discord import app_commands
from discord.ext import commands, tasks

from bot.config import settings
from integrations import github
from orchestrator.decompose import decompose_decision

log = logging.getLogger("tower.voting")

VOTE_EMOJI = {"for": "✅", "against": "❌", "abstain": "🤷"}


class VoteLevel(StrEnum):
    ROUTINE = "routine"
    SIGNIFICANT = "significant"
    CRITICAL = "critical"


LEVEL_HOURS: dict[VoteLevel, int] = {
    VoteLevel.ROUTINE: settings.routine_duration_hours,
    VoteLevel.SIGNIFICANT: settings.significant_duration_hours,
    VoteLevel.CRITICAL: settings.critical_duration_hours,
}

LEVEL_THRESHOLD: dict[VoteLevel, float] = {
    VoteLevel.ROUTINE: 0.5,
    VoteLevel.SIGNIFICANT: 2 / 3,
    VoteLevel.CRITICAL: 3 / 4,
}


@dataclass
class ActiveVote:
    id: int                          # sequential, stored in bot state
    title: str
    level: VoteLevel
    started_by: int                  # Discord user ID
    ends_at: datetime
    message_id: int                  # the message in #voting
    discord_thread_url: str = ""
    votes_for: set[int] = field(default_factory=set)
    votes_against: set[int] = field(default_factory=set)
    votes_abstain: set[int] = field(default_factory=set)
    closed: bool = False

    @property
    def total(self) -> int:
        return len(self.votes_for) + len(self.votes_against) + len(self.votes_abstain)

    @property
    def result(self) -> Optional[bool]:
        """True = accepted, False = rejected, None = undecided."""
        total = self.total
        if total == 0:
            return None
        ratio = len(self.votes_for) / total
        threshold = LEVEL_THRESHOLD[self.level]
        return ratio > threshold

    def summary_embed(self, *, final: bool = False) -> discord.Embed:
        color = discord.Color.yellow()
        if final:
            color = discord.Color.green() if self.result else discord.Color.red()
        embed = discord.Embed(
            title=f"{'🗳️' if not final else ('✅' if self.result else '❌')} {self.title}",
            color=color,
        )
        embed.add_field(name="Level", value=self.level.value.capitalize(), inline=True)
        embed.add_field(
            name="Ends",
            value=f"<t:{int(self.ends_at.timestamp())}:R>" if not final else "Closed",
            inline=True,
        )
        embed.add_field(
            name="Votes",
            value=(
                f"{VOTE_EMOJI['for']} {len(self.votes_for)}  "
                f"{VOTE_EMOJI['against']} {len(self.votes_against)}  "
                f"{VOTE_EMOJI['abstain']} {len(self.votes_abstain)}"
            ),
            inline=False,
        )
        if final:
            verdict = "**Accepted**" if self.result else "**Rejected**"
            embed.add_field(name="Result", value=verdict, inline=False)
        return embed


class VotingCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._votes: dict[int, ActiveVote] = {}
        self._next_id: int = 1
        self._next_decision_id: int = self._detect_next_decision_id()
        self._check_expired.start()

    def cog_unload(self) -> None:
        self._check_expired.cancel()

    def _detect_next_decision_id(self) -> int:
        d = settings.decisions_dir
        if not d.exists():
            return 2  # 0001 is bootstrap
        existing = sorted(d.glob("[0-9][0-9][0-9][0-9]-*.yaml"))
        if not existing:
            return 2
        last = int(existing[-1].name[:4])
        return last + 1

    # ------------------------------------------------------------------ #
    #  Slash command group: /vote                                          #
    # ------------------------------------------------------------------ #

    vote_group = app_commands.Group(name="vote", description="Community voting")

    @vote_group.command(name="start", description="Open a new community vote")
    @app_commands.describe(
        title="What are we voting on?",
        level="Vote level: routine | significant | critical",
    )
    @app_commands.choices(
        level=[
            app_commands.Choice(name="Routine (24h, simple majority)", value="routine"),
            app_commands.Choice(name="Significant (48h, 2/3)", value="significant"),
            app_commands.Choice(name="Critical (72h, 3/4 + Keeper)", value="critical"),
        ]
    )
    async def vote_start(
        self,
        interaction: discord.Interaction,
        title: str,
        level: str = "routine",
    ) -> None:
        channel = await self._get_voting_channel(interaction.guild)
        if channel is None:
            await interaction.response.send_message(
                "❌ Could not find `#voting` channel.", ephemeral=True
            )
            return

        vote_level = VoteLevel(level)
        ends_at = datetime.now(timezone.utc) + timedelta(hours=LEVEL_HOURS[vote_level])
        vote_id = self._next_id
        self._next_id += 1

        vote = ActiveVote(
            id=vote_id,
            title=title,
            level=vote_level,
            started_by=interaction.user.id,
            ends_at=ends_at,
            message_id=0,
        )

        embed = vote.summary_embed()
        embed.set_footer(text=f"Vote #{vote_id} · started by {interaction.user.display_name}")

        msg = await channel.send(
            content=(
                f"**New {vote_level.value} vote** — react to cast your ballot:\n"
                f"{VOTE_EMOJI['for']} For  "
                f"{VOTE_EMOJI['against']} Against  "
                f"{VOTE_EMOJI['abstain']} Abstain"
            ),
            embed=embed,
        )
        for emoji in VOTE_EMOJI.values():
            await msg.add_reaction(emoji)

        vote.message_id = msg.id
        vote.discord_thread_url = msg.jump_url
        self._votes[vote_id] = vote

        await interaction.response.send_message(
            f"✅ Vote #{vote_id} opened in {channel.mention}.", ephemeral=True
        )
        log.info("Vote #%d opened: %s (%s)", vote_id, title, level)

    @vote_group.command(name="status", description="Show results of an ongoing vote")
    @app_commands.describe(vote_id="Vote number (leave blank for the latest)")
    async def vote_status(
        self, interaction: discord.Interaction, vote_id: Optional[int] = None
    ) -> None:
        vote = self._resolve_vote(vote_id)
        if vote is None:
            await interaction.response.send_message("❌ Vote not found.", ephemeral=True)
            return
        await interaction.response.send_message(embed=vote.summary_embed(), ephemeral=True)

    @vote_group.command(name="close", description="Close a vote early (Architect+ only)")
    @app_commands.describe(vote_id="Vote number to close")
    async def vote_close(self, interaction: discord.Interaction, vote_id: int) -> None:
        if not await self._is_architect_or_keeper(interaction):
            await interaction.response.send_message(
                "❌ Only Architects and Keepers can close votes early.", ephemeral=True
            )
            return
        vote = self._votes.get(vote_id)
        if vote is None or vote.closed:
            await interaction.response.send_message(
                "❌ Vote not found or already closed.", ephemeral=True
            )
            return
        await self._finalize_vote(vote, interaction.guild)
        await interaction.response.send_message(
            f"Vote #{vote_id} closed early.", ephemeral=True
        )

    # ------------------------------------------------------------------ #
    #  Reaction listener — count votes                                     #
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == self.bot.user.id:  # type: ignore[union-attr]
            return
        vote = self._vote_by_message(payload.message_id)
        if vote is None or vote.closed:
            return
        emoji = str(payload.emoji)
        uid = payload.user_id
        self._remove_from_all(vote, uid)
        if emoji == VOTE_EMOJI["for"]:
            vote.votes_for.add(uid)
        elif emoji == VOTE_EMOJI["against"]:
            vote.votes_against.add(uid)
        elif emoji == VOTE_EMOJI["abstain"]:
            vote.votes_abstain.add(uid)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        vote = self._vote_by_message(payload.message_id)
        if vote is None or vote.closed:
            return
        self._remove_from_all(vote, payload.user_id)

    # ------------------------------------------------------------------ #
    #  Background task — close expired votes                               #
    # ------------------------------------------------------------------ #

    @tasks.loop(minutes=1)
    async def _check_expired(self) -> None:
        now = datetime.now(timezone.utc)
        for vote in list(self._votes.values()):
            if not vote.closed and vote.ends_at <= now:
                guild = self.bot.guilds[0] if self.bot.guilds else None
                if guild:
                    await self._finalize_vote(vote, guild)

    @_check_expired.before_loop
    async def _before_check(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ #
    #  Finalization — write decision file                                  #
    # ------------------------------------------------------------------ #

    async def _finalize_vote(
        self, vote: ActiveVote, guild: Optional[discord.Guild]
    ) -> None:
        vote.closed = True
        log.info(
            "Finalizing vote #%d: for=%d against=%d abstain=%d result=%s",
            vote.id,
            len(vote.votes_for),
            len(vote.votes_against),
            len(vote.votes_abstain),
            vote.result,
        )

        status = "accepted" if vote.result else "rejected"
        doc = {
            "id": self._next_decision_id,
            "title": vote.title,
            "level": vote.level.value,
            "status": status,
            "supersedes": None,
            "votes": {
                "for": len(vote.votes_for),
                "against": len(vote.votes_against),
                "abstain": len(vote.votes_abstain),
            },
            "discord_thread": vote.discord_thread_url,
            "decided_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "decided_by": "vote",
            "decision": vote.title,
            "tasks_hint": "",
        }

        slug = vote.title.lower()[:40].replace(" ", "-").replace("/", "-")
        filename = f"{self._next_decision_id:04d}-{slug}.yaml"
        path = settings.decisions_dir / filename

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(doc, f, allow_unicode=True, sort_keys=False)

        self._next_decision_id += 1
        log.info("Decision written: %s", path)

        # Auto-create GitHub Issue for accepted decisions
        gh_issue_url = ""
        if vote.result and settings.github_token and settings.github_token != "your-github-pat-here":
            try:
                body = (
                    f"## Decision accepted by community vote\n\n"
                    f"**Vote #{vote.id}** · level: `{vote.level.value}` · "
                    f"✅ {len(vote.votes_for)} / ❌ {len(vote.votes_against)} / 🤷 {len(vote.votes_abstain)}\n\n"
                    f"**Discord thread:** {vote.discord_thread_url}\n"
                    f"**Decision file:** `{filename}`\n\n"
                    f"---\n*Auto-created by Tower of Babel Orchestrator.*"
                )
                issue = await github.create_issue(
                    title=f"[Decision #{self._next_decision_id - 1}] {vote.title}",
                    body=body,
                    labels=["task", "from-vote"],
                )
                gh_issue_url = issue.url
                log.info("GitHub Issue #%d created for vote #%d", issue.number, vote.id)
            except Exception as exc:
                log.warning("Could not create GitHub Issue for vote #%d: %s", vote.id, exc)

        # Update the original voting message
        if guild:
            channel = await self._get_voting_channel(guild)
            if channel:
                try:
                    msg = await channel.fetch_message(vote.message_id)
                    await msg.edit(embed=vote.summary_embed(final=True))
                except Exception as exc:
                    log.warning("Could not update vote message: %s", exc)

            # Post to #tasks if accepted
            if vote.result:
                tasks_ch = await self._get_channel(guild, settings.tasks_channel_name)
                if tasks_ch:
                    msg_text = (
                        f"📋 New task from accepted vote: **{vote.title}**"
                        + (f"\n🔗 GitHub Issue: {gh_issue_url}" if gh_issue_url else "")
                    )
                    await tasks_ch.send(msg_text)

            # AI decomposition — fire-and-forget in background
            if vote.result and path.exists():
                asyncio.create_task(self._run_decomposition(path, guild))

            # Post to audit log
            audit = await self._get_channel(guild, settings.audit_channel_name)
            if audit:
                await audit.send(
                    f"📋 Vote #{vote.id} **{status}**: {vote.title} "
                    f"(✅{len(vote.votes_for)} ❌{len(vote.votes_against)} "
                    f"🤷{len(vote.votes_abstain)}) → `{filename}`"
                    + (f" → {gh_issue_url}" if gh_issue_url else "")
                )

    # ------------------------------------------------------------------ #
    #  AI decomposition (background)                                       #
    # ------------------------------------------------------------------ #

    async def _run_decomposition(
        self, decision_path: Path, guild: Optional[discord.Guild]
    ) -> None:
        log.info("Starting AI decomposition for %s", decision_path.name)
        tasks_ch = await self._get_channel(guild, settings.tasks_channel_name) if guild else None
        try:
            issues = await decompose_decision(decision_path)
            if not issues:
                return
            lines = [f"🤖 **AI decomposed decision into {len(issues)} task(s):**"]
            for di in issues:
                if di.github_issue:
                    gfi = " 🟢 good first issue" if di.good_first_issue else ""
                    lines.append(
                        f"  • [{di.github_issue.number}]({di.github_issue.url}) "
                        f"**{di.title}** `{di.estimate}`{gfi}"
                    )
                else:
                    lines.append(f"  • {di.title} `{di.estimate}` *(issue creation failed)*")
            if tasks_ch:
                await tasks_ch.send("\n".join(lines))
        except Exception as exc:
            log.error("Decomposition failed: %s", exc)
            if tasks_ch:
                await tasks_ch.send(
                    f"⚠️ AI decomposition failed for `{decision_path.name}`: {exc}"
                )

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _vote_by_message(self, message_id: int) -> Optional[ActiveVote]:
        return next((v for v in self._votes.values() if v.message_id == message_id), None)

    def _resolve_vote(self, vote_id: Optional[int]) -> Optional[ActiveVote]:
        if vote_id is not None:
            return self._votes.get(vote_id)
        open_votes = [v for v in self._votes.values() if not v.closed]
        return open_votes[-1] if open_votes else None

    @staticmethod
    def _remove_from_all(vote: ActiveVote, uid: int) -> None:
        vote.votes_for.discard(uid)
        vote.votes_against.discard(uid)
        vote.votes_abstain.discard(uid)

    async def _get_voting_channel(
        self, guild: Optional[discord.Guild]
    ) -> Optional[discord.TextChannel]:
        return await self._get_channel(guild, settings.voting_channel_name)

    @staticmethod
    async def _get_channel(
        guild: Optional[discord.Guild], name: str
    ) -> Optional[discord.TextChannel]:
        if guild is None:
            return None
        return discord.utils.get(guild.text_channels, name=name)

    @staticmethod
    async def _is_architect_or_keeper(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        role_names = {r.name.lower() for r in member.roles}
        return bool(role_names & {"architect", "keeper", "🏛️ architect", "🛡️ keeper"})


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VotingCog(bot))
