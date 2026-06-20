"""Phase 1b: sync Discord roles <-> GitHub teams."""

from discord.ext import commands


class RolesCog(commands.Cog):
    """Placeholder — implemented in Phase 1b."""


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RolesCog(bot))
