"""
Phase 2: /task commands — GitHub Issues integration.

/task list          — show open tasks (good first issue and task labels)
/task take <id>     — assign a GitHub Issue to yourself
/task done <id>     — close an Issue and post to #tasks
/task status <id>   — show Issue details
"""

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import settings
from integrations import github

log = logging.getLogger("tower.tasks")

TASK_LABELS = ["task", "good first issue"]


def _issue_embed(issue: github.Issue, *, color: discord.Color | None = None) -> discord.Embed:
    c = color or discord.Color.blurple()
    embed = discord.Embed(title=f"#{issue.number} {issue.title}", url=issue.url, color=c)
    if issue.assignees:
        embed.add_field(name="Assignee(s)", value=", ".join(issue.assignees), inline=True)
    else:
        embed.add_field(name="Assignee(s)", value="*unassigned*", inline=True)
    if issue.labels:
        embed.add_field(name="Labels", value=" · ".join(issue.labels), inline=True)
    embed.add_field(name="State", value=issue.state.capitalize(), inline=True)
    if issue.body:
        embed.description = issue.body[:300] + ("…" if len(issue.body) > 300 else "")
    return embed


class TasksCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    task_group = app_commands.Group(name="task", description="GitHub task management")

    # ------------------------------------------------------------------ #

    @task_group.command(name="list", description="Show open tasks")
    @app_commands.describe(label="Filter by label (default: all tasks)")
    @app_commands.choices(
        label=[
            app_commands.Choice(name="All tasks", value="task"),
            app_commands.Choice(name="Good first issue", value="good first issue"),
        ]
    )
    async def task_list(
        self, interaction: discord.Interaction, label: str = "task"
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            issues = await github.list_open_issues(label=label)
        except Exception as exc:
            await interaction.followup.send(f"❌ GitHub error: {exc}", ephemeral=True)
            return

        if not issues:
            await interaction.followup.send("No open tasks found.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Open tasks — {label}",
            color=discord.Color.blurple(),
            description="\n".join(
                f"[#{i.number}]({i.url}) {i.title}"
                + (f" — *{', '.join(i.assignees)}*" if i.assignees else "")
                for i in issues[:20]
            ),
        )
        embed.set_footer(text=f"{len(issues)} open · {settings.github_repo}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #

    @task_group.command(name="take", description="Assign a task to yourself")
    @app_commands.describe(issue_number="GitHub Issue number")
    async def task_take(self, interaction: discord.Interaction, issue_number: int) -> None:
        await interaction.response.defer(ephemeral=True)
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.followup.send("❌ Can only be used in a server.", ephemeral=True)
            return

        gh_login = member.name  # best effort; ideally mapped via DB in Phase 3
        try:
            issue = await github.assign_issue(issue_number, [gh_login])
        except Exception as exc:
            await interaction.followup.send(f"❌ GitHub error: {exc}", ephemeral=True)
            return

        await github.add_comment(
            issue_number,
            f"🧱 Task claimed by **{member.display_name}** (`{gh_login}`) via Tower of Babel bot.",
        )

        embed = _issue_embed(issue, color=discord.Color.green())
        await interaction.followup.send(
            content=f"✅ You're now assigned to #{issue_number}.",
            embed=embed,
            ephemeral=True,
        )

        # Post to #tasks channel
        tasks_ch = await self._tasks_channel(interaction.guild)
        if tasks_ch:
            await tasks_ch.send(
                f"🎯 **{member.display_name}** took task "
                f"[#{issue.number} {issue.title}]({issue.url})"
            )
        log.info("%s took issue #%d", gh_login, issue_number)

    # ------------------------------------------------------------------ #

    @task_group.command(name="done", description="Mark a task as completed")
    @app_commands.describe(issue_number="GitHub Issue number")
    async def task_done(self, interaction: discord.Interaction, issue_number: int) -> None:
        await interaction.response.defer(ephemeral=True)
        member = interaction.user
        try:
            issue = await github.close_issue(issue_number, reason="completed")
        except Exception as exc:
            await interaction.followup.send(f"❌ GitHub error: {exc}", ephemeral=True)
            return

        await github.add_comment(
            issue_number,
            f"✅ Marked as done by **{getattr(member, 'display_name', str(member))}** via Tower of Babel bot.",
        )

        embed = _issue_embed(issue, color=discord.Color.green())
        embed.title = f"✅ #{issue.number} {issue.title}"
        await interaction.followup.send(embed=embed, ephemeral=True)

        tasks_ch = await self._tasks_channel(interaction.guild)
        if tasks_ch:
            await tasks_ch.send(
                f"✅ **{getattr(member, 'display_name', str(member))}** completed "
                f"[#{issue.number} {issue.title}]({issue.url})"
            )
        log.info("%s closed issue #%d", member, issue_number)

    # ------------------------------------------------------------------ #

    @task_group.command(name="status", description="Show details of a task")
    @app_commands.describe(issue_number="GitHub Issue number")
    async def task_status(self, interaction: discord.Interaction, issue_number: int) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            issue = await github.get_issue(issue_number)
        except Exception as exc:
            await interaction.followup.send(f"❌ GitHub error: {exc}", ephemeral=True)
            return
        color = discord.Color.green() if issue.state == "open" else discord.Color.greyple()
        await interaction.followup.send(embed=_issue_embed(issue, color=color), ephemeral=True)

    # ------------------------------------------------------------------ #

    @staticmethod
    async def _tasks_channel(
        guild: discord.Guild | None,
    ) -> discord.TextChannel | None:
        if guild is None:
            return None
        return discord.utils.get(guild.text_channels, name=settings.tasks_channel_name)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TasksCog(bot))
