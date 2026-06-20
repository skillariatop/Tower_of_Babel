"""Audit log helper — every bot action is posted to #audit-log."""

import logging

import discord
from discord.ext import commands

from bot.config import settings

log = logging.getLogger("tower.audit")


class AuditCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def log_action(self, guild: discord.Guild, message: str) -> None:
        channel: discord.TextChannel | None = discord.utils.get(
            guild.text_channels, name=settings.audit_channel_name
        )
        if channel is None:
            log.warning("audit-log channel not found")
            return
        await channel.send(f"🤖 {message}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AuditCog(bot))
