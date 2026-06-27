import asyncio
import logging
import sys

import discord
import uvicorn
from discord.ext import commands

from bot.config import settings
from integrations import webhooks

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("tower")

COGS = [
    "bot.cogs.voting",
    "bot.cogs.tasks",
    "bot.cogs.roles",
    "bot.cogs.audit",
    "bot.cogs.orchestrator",
    "bot.cogs.admin",
]

POLLING_COGS = [
    "integrations.poller",
]


class TowerBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        all_cogs = COGS + (POLLING_COGS if not settings.webhook_enabled else [])
        for cog in all_cogs:
            try:
                await self.load_extension(cog)
                log.info("Loaded cog: %s", cog)
            except Exception as exc:
                log.error("Failed to load cog %s: %s", cog, exc)

        guild = discord.Object(id=settings.discord_guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log.info("Slash commands synced to guild %d", settings.discord_guild_id)

    async def on_ready(self) -> None:
        log.info("Tower of Babel bot ready — logged in as %s", self.user)

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:  # type: ignore[override]
        log.error("Command error: %s", error)


async def main() -> None:
    bot = TowerBot()
    webhooks.set_bot(bot)

    async with bot:
        if settings.webhook_enabled:
            config = uvicorn.Config(
                webhooks.app,
                host="0.0.0.0",
                port=settings.webhook_port,
                log_level=settings.log_level.lower(),
            )
            server = uvicorn.Server(config)
            await asyncio.gather(
                bot.start(settings.discord_token),
                server.serve(),
            )
        else:
            await bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
