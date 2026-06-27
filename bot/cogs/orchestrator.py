"""
/orchestrate decompose <decision_id>  — manually trigger AI decomposition
/orchestrate digest                   — generate and post weekly digest
/orchestrate summarize                — summarize last N messages in current channel
"""

import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.config import settings
from orchestrator.decompose import decompose_decision, decompose_decision_text
from orchestrator.digest import generate_weekly_digest
from orchestrator.llm import llm
from orchestrator.metrics import collect as collect_metrics
from orchestrator.projects import list_projects, register_project

log = logging.getLogger("tower.orchestrator")


class OrchestratorCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._weekly_digest.start()

    def cog_unload(self) -> None:
        self._weekly_digest.cancel()

    orch_group = app_commands.Group(
        name="orchestrate", description="AI Orchestrator commands (Architect+ only)"
    )

    # ------------------------------------------------------------------ #
    #  /orchestrate decompose                                              #
    # ------------------------------------------------------------------ #

    @orch_group.command(
        name="decompose", description="AI-decompose a decision file into GitHub Issues"
    )
    @app_commands.describe(decision_id="Decision number (e.g. 2 for decisions/0002-*.yaml)")
    async def decompose(self, interaction: discord.Interaction, decision_id: int) -> None:
        if not await _is_mason_or_above(interaction):
            await interaction.response.send_message(
                "❌ Mason+ required.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=False)

        path = _find_decision(decision_id)
        if path is None:
            await interaction.followup.send(
                f"❌ Decision #{decision_id:04d} not found in `decisions/`."
            )
            return

        await interaction.followup.send(
            f"🤖 Decomposing decision `{path.name}`… this may take a moment."
        )

        try:
            issues = await decompose_decision(path)
        except Exception as exc:
            await interaction.followup.send(f"❌ Decomposition failed: {exc}")
            return

        if not issues:
            await interaction.followup.send("No issues created (decision may not be accepted).")
            return

        lines = [f"✅ Created **{len(issues)}** GitHub Issue(s):"]
        for di in issues:
            if di.github_issue:
                gfi = " 🟢" if di.good_first_issue else ""
                lines.append(
                    f"  • [#{di.github_issue.number}]({di.github_issue.url}) "
                    f"**{di.title}** `{di.estimate}`{gfi}"
                )
        await interaction.followup.send("\n".join(lines))

    # ------------------------------------------------------------------ #
    #  /orchestrate decompose-text                                         #
    # ------------------------------------------------------------------ #

    @orch_group.command(
        name="decompose-text",
        description="Decompose a free-form decision text into GitHub Issues",
    )
    @app_commands.describe(
        title="Short decision title",
        decision="Full decision text",
        hint="Optional: hint on how to break it down",
    )
    async def decompose_text(
        self,
        interaction: discord.Interaction,
        title: str,
        decision: str,
        hint: str = "",
    ) -> None:
        if not await _is_mason_or_above(interaction):
            await interaction.response.send_message("❌ Mason+ required.", ephemeral=True)
            return

        await interaction.response.defer()
        await interaction.followup.send("🤖 Decomposing… this may take a moment.")

        try:
            issues = await decompose_decision_text(title, decision, hint)
        except Exception as exc:
            await interaction.followup.send(f"❌ Decomposition failed: {exc}")
            return

        lines = [f"✅ Created **{len(issues)}** GitHub Issue(s):"]
        for di in issues:
            if di.github_issue:
                gfi = " 🟢" if di.good_first_issue else ""
                lines.append(
                    f"  • [#{di.github_issue.number}]({di.github_issue.url}) "
                    f"**{di.title}** `{di.estimate}`{gfi}"
                )
        await interaction.followup.send("\n".join(lines))

    # ------------------------------------------------------------------ #
    #  /orchestrate digest                                                 #
    # ------------------------------------------------------------------ #

    @orch_group.command(name="digest", description="Generate and post the weekly digest now")
    async def digest(self, interaction: discord.Interaction) -> None:
        if not await _is_mason_or_above(interaction):
            await interaction.response.send_message("❌ Mason+ required.", ephemeral=True)
            return

        await interaction.response.defer()
        await interaction.followup.send("🤖 Generating weekly digest…")

        try:
            text = await generate_weekly_digest()
        except Exception as exc:
            await interaction.followup.send(f"❌ Digest generation failed: {exc}")
            return

        await self._post_digest(text, interaction.guild)
        await interaction.followup.send("✅ Digest posted to `#announcements`.")

    # ------------------------------------------------------------------ #
    #  /orchestrate summarize                                              #
    # ------------------------------------------------------------------ #

    @orch_group.command(
        name="summarize", description="Summarize the last N messages in this channel"
    )
    @app_commands.describe(count="How many messages to summarize (default 50)")
    async def summarize(
        self, interaction: discord.Interaction, count: int = 50
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("❌ Works in text channels only.", ephemeral=True)
            return

        messages = [
            m async for m in channel.history(limit=min(count, 100))
            if not m.author.bot and m.content.strip()
        ]
        messages.reverse()

        if not messages:
            await interaction.followup.send("No messages to summarize.", ephemeral=True)
            return

        transcript = "\n".join(
            f"{m.author.display_name}: {m.content[:300]}" for m in messages
        )
        prompt = (
            f"Summarize this Discord discussion in 3–5 bullet points. "
            f"Focus on decisions made, open questions, and action items.\n\n"
            f"Discussion:\n{transcript}"
        )

        try:
            summary = await llm.complete(prompt)
        except Exception as exc:
            await interaction.followup.send(f"❌ LLM error: {exc}", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📝 Summary of last {len(messages)} messages",
            description=summary,
            color=discord.Color.blurple(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    #  Automatic weekly digest (Monday 09:00 UTC)                         #
    # ------------------------------------------------------------------ #

    @tasks.loop(hours=168)  # every 7 days
    async def _weekly_digest(self) -> None:
        try:
            text = await generate_weekly_digest()
            for guild in self.bot.guilds:
                await self._post_digest(text, guild)
        except Exception as exc:
            log.error("Auto weekly digest failed: %s", exc)

    @_weekly_digest.before_loop
    async def _before_digest(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ #
    #  /orchestrate metrics                                                #
    # ------------------------------------------------------------------ #

    @orch_group.command(name="metrics", description="Show project health metrics")
    @app_commands.describe(days="Period in days (default 7)")
    async def metrics(self, interaction: discord.Interaction, days: int = 7) -> None:
        await interaction.response.defer()
        try:
            m = await collect_metrics(period_days=days)
        except Exception as exc:
            await interaction.followup.send(f"❌ Metrics collection failed: {exc}")
            return

        embed = discord.Embed(
            title=f"📊 Tower of Babel — {days}-day Metrics",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="🚀 Velocity",
            value=(
                f"Issues opened: **{m.issues_opened}** / closed: **{m.issues_closed}** "
                f"({m.close_rate:.0%})\n"
                f"PRs opened: **{m.prs_opened}** / merged: **{m.prs_merged}** "
                f"({m.merge_rate:.0%})"
            ),
            inline=False,
        )
        embed.add_field(
            name="👥 Contributors",
            value=(
                f"Active this period: **{len(m.active_contributors)}**\n"
                f"New this period: **{len(m.new_contributors)}**\n"
                f"All-time: **{len(m.all_time_contributors)}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="📋 Backlog",
            value=(
                f"Open issues: **{m.open_issues}**\n"
                f"Stale (>7d): **{m.stale_issues}**\n"
                f"Unassigned tasks: **{m.unassigned_tasks}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="🗳️ Governance",
            value=f"Decisions accepted: **{m.decisions_made}**",
            inline=True,
        )
        if m.active_contributors:
            embed.set_footer(text="Contributors: " + ", ".join(sorted(m.active_contributors)[:10]))
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------ #
    #  /orchestrate project list / register                               #
    # ------------------------------------------------------------------ #

    project_group = app_commands.Group(
        name="project", description="Multi-project management", parent=orch_group
    )

    @project_group.command(name="list", description="List all registered projects")
    async def project_list(self, interaction: discord.Interaction) -> None:
        projects = list_projects()
        if not projects:
            await interaction.response.send_message("No projects registered.", ephemeral=True)
            return
        lines = [f"**{p.name}** (`{p.id}`) — `{p.github_repo}`" for p in projects]
        embed = discord.Embed(
            title="🗂️ Registered Projects",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @project_group.command(name="register", description="Register a new project (Architect+)")
    @app_commands.describe(
        project_id="Short slug (e.g. my-project)",
        name="Human-readable name",
        github_repo="owner/repo format",
    )
    async def project_register(
        self,
        interaction: discord.Interaction,
        project_id: str,
        name: str,
        github_repo: str,
    ) -> None:
        if not await _is_mason_or_above(interaction):
            await interaction.response.send_message("❌ Mason+ required.", ephemeral=True)
            return
        proj = register_project(project_id, name, github_repo)
        await interaction.response.send_message(
            f"✅ Registered **{proj.name}** (`{proj.id}`) → `{proj.github_repo}`\n"
            f"Decisions dir: `{proj.decisions_dir}`",
            ephemeral=True,
        )

    async def _post_digest(self, text: str, guild: discord.Guild | None) -> None:
        if guild is None:
            return
        ch = discord.utils.get(guild.text_channels, name=settings.announcements_channel_name)
        if ch is None:
            log.warning("announcements channel not found")
            return
        # Split if over Discord's 2000-char limit
        for chunk in _split_message(text):
            await ch.send(chunk)


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _find_decision(decision_id: int) -> Path | None:
    pattern = f"{decision_id:04d}-*.yaml"
    matches = list(settings.decisions_dir.glob(pattern))
    return matches[0] if matches else None


async def _is_mason_or_above(interaction: discord.Interaction) -> bool:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    role_names = {r.name.lower() for r in member.roles}
    return bool(role_names & {"mason", "architect", "keeper",
                               "⚒️ mason", "🏛️ architect", "🛡️ keeper"})


def _split_message(text: str, limit: int = 1900) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    while text:
        parts.append(text[:limit])
        text = text[limit:]
    return parts


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OrchestratorCog(bot))
