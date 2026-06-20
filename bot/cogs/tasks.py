"""Phase 2: /task take | done | status — GitHub Issues integration."""

from discord.ext import commands


class TasksCog(commands.Cog):
    """Placeholder — implemented in Phase 2."""


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TasksCog(bot))
