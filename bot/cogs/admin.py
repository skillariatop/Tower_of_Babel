"""
Admin cog — Keeper-only controls.

/admin status   — system health overview
/admin stop     — kill switch: pause all orchestrator tasks
/admin resume   — resume after stop
/admin check    — run deadline check now
/admin suggest <issue> — show assignment suggestions for an Issue
/admin review <pr>     — trigger AI review of a PR manually
"""

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.config import settings
from orchestrator.assign import auto_suggest_for_issue
from orchestrator.deadlines import run_deadline_check
from orchestrator.review import review_pr_safe
from integrations.github import get_issue

log = logging.getLogger("tower.admin")

# Global pause flag — all background orchestrator loops check this
_paused = False


def is_paused() -> bool:
    return _paused


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._started_at = datetime.now(timezone.utc)
        self._deadline_check.start()

    def cog_unload(self) -> None:
        self._deadline_check.cancel()

    admin_group = app_commands.Group(
        name="admin", description="Keeper-only system controls"
    )

    # ------------------------------------------------------------------ #
    #  /admin status                                                       #
    # ------------------------------------------------------------------ #

    @admin_group.command(name="status", description="Show system health")
    async def status(self, interaction: discord.Interaction) -> None:
        uptime = datetime.now(timezone.utc) - self._started_at
        h, rem = divmod(int(uptime.total_seconds()), 3600)
        m = rem // 60

        embed = discord.Embed(
            title="🗼 Tower of Babel — System Status",
            color=discord.Color.red() if _paused else discord.Color.green(),
        )
        embed.add_field(name="Bot",         value="🟢 Online",                      inline=True)
        embed.add_field(name="Orchestrator",value="🔴 PAUSED" if _paused else "🟢 Running", inline=True)
        embed.add_field(name="Uptime",      value=f"{h}h {m}m",                    inline=True)
        embed.add_field(name="LLM provider",value=settings.llm_provider,           inline=True)
        embed.add_field(name="LLM model",   value=settings.openrouter_model,       inline=True)
        embed.add_field(name="Webhook",
                        value=f"`:{ settings.webhook_port}`" if settings.webhook_enabled else "disabled",
                        inline=True)
        embed.add_field(name="GitHub repo", value=f"`{settings.github_repo}`",     inline=False)
        embed.set_footer(text=f"Logged in as {self.bot.user}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    #  /admin stop / resume — kill switch                                  #
    # ------------------------------------------------------------------ #

    @admin_group.command(name="stop", description="🛑 Kill switch: pause all AI orchestrator tasks")
    async def stop(self, interaction: discord.Interaction) -> None:
        if not await _is_keeper(interaction):
            await interaction.response.send_message("❌ Keepers only.", ephemeral=True)
            return
        global _paused
        _paused = True
        log.warning("ORCHESTRATOR PAUSED by %s", interaction.user)
        await interaction.response.send_message(
            "🛑 **Orchestrator paused.** All AI background tasks halted. "
            "Use `/admin resume` to restart.",
            ephemeral=False,
        )
        audit = _get_audit_channel(interaction.guild)
        if audit:
            await audit.send(
                f"🛑 **KILL SWITCH** activated by {interaction.user.mention}. "
                f"All orchestrator tasks paused."
            )

    @admin_group.command(name="resume", description="▶️ Resume orchestrator after stop")
    async def resume(self, interaction: discord.Interaction) -> None:
        if not await _is_keeper(interaction):
            await interaction.response.send_message("❌ Keepers only.", ephemeral=True)
            return
        global _paused
        _paused = False
        log.info("Orchestrator resumed by %s", interaction.user)
        await interaction.response.send_message("▶️ Orchestrator resumed.", ephemeral=False)
        audit = _get_audit_channel(interaction.guild)
        if audit:
            await audit.send(
                f"▶️ Orchestrator **resumed** by {interaction.user.mention}."
            )

    # ------------------------------------------------------------------ #
    #  /admin check — run deadline tracker now                             #
    # ------------------------------------------------------------------ #

    @admin_group.command(name="check", description="Run deadline check now")
    async def check(self, interaction: discord.Interaction) -> None:
        if not await _is_keeper_or_architect(interaction):
            await interaction.response.send_message("❌ Architect+ required.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        acted = await run_deadline_check(interaction.guild)
        await interaction.followup.send(
            f"✅ Deadline check complete — acted on **{acted}** stale issue(s).",
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    #  /admin suggest <issue>                                              #
    # ------------------------------------------------------------------ #

    @admin_group.command(name="suggest", description="Suggest assignees for an Issue")
    @app_commands.describe(issue_number="GitHub Issue number")
    async def suggest(self, interaction: discord.Interaction, issue_number: int) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            issue = await get_issue(issue_number)
            suggestions = await auto_suggest_for_issue(issue)
        except Exception as exc:
            await interaction.followup.send(f"❌ Error: {exc}", ephemeral=True)
            return

        if not suggestions:
            await interaction.followup.send(
                "No suggestions — no contributor history yet.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🎯 Assignment suggestions for #{issue_number}",
            description="\n".join(f"{i+1}. `{login}`" for i, login in enumerate(suggestions)),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Ranked by domain fit and lowest workload")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    #  /admin review <pr>                                                  #
    # ------------------------------------------------------------------ #

    @admin_group.command(name="review", description="Trigger AI review of a PR")
    @app_commands.describe(pr_number="GitHub PR number")
    async def review(self, interaction: discord.Interaction, pr_number: int) -> None:
        if not await _is_keeper_or_architect(interaction):
            await interaction.response.send_message("❌ Architect+ required.", ephemeral=True)
            return
        await interaction.response.defer()
        await interaction.followup.send(f"🤖 Running AI review for PR #{pr_number}…")
        await review_pr_safe(pr_number)
        await interaction.followup.send(
            f"✅ Review posted as a comment on PR #{pr_number}."
        )

    # ------------------------------------------------------------------ #
    #  Background deadline check — every 12 hours                         #
    # ------------------------------------------------------------------ #

    @tasks.loop(hours=12)
    async def _deadline_check(self) -> None:
        if _paused:
            return
        guild = self.bot.guilds[0] if self.bot.guilds else None
        await run_deadline_check(guild)

    @_deadline_check.before_loop
    async def _before_deadline(self) -> None:
        await self.bot.wait_until_ready()


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

async def _is_keeper(interaction: discord.Interaction) -> bool:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    return any(r.name.lower() in {"keeper", "🛡️ keeper"} for r in member.roles)


async def _is_keeper_or_architect(interaction: discord.Interaction) -> bool:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    names = {r.name.lower() for r in member.roles}
    return bool(names & {"keeper", "🛡️ keeper", "architect", "🏛️ architect"})


def _get_audit_channel(guild: discord.Guild | None) -> discord.TextChannel | None:
    if guild is None:
        return None
    return discord.utils.get(guild.text_channels, name=settings.audit_channel_name)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
