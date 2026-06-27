"""
One-time Discord server setup script.
Creates categories, channels, roles, and permissions for Tower of Babel.

Run once:
    python infra/setup_discord.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])

# ------------------------------------------------------------------ #
#  Structure to create                                                 #
# ------------------------------------------------------------------ #

ROLES = [
    # (name, color_hex, hoist, mentionable)
    ("🛡️ Keeper",      0xE74C3C, True,  False),
    ("🏛️ Architect",   0x9B59B6, True,  True),
    ("⚒️ Mason",        0x3498DB, True,  True),
    ("🧱 Apprentice",  0x2ECC71, True,  True),
    ("👁️ Observer",    0x95A5A6, False, False),
    ("🤖 Orchestrator", 0xF39C12, False, False),
]

CATEGORIES_AND_CHANNELS = [
    {
        "name": "📣 COMMUNITY",
        "channels": [
            {"name": "announcements", "type": "text",  "topic": "Releases, digests, important decisions. Bot and Architects post here."},
            {"name": "voting",        "type": "text",  "topic": "Community votes only. Use /vote start to open a new vote."},
            {"name": "rfc",           "type": "text",  "topic": "Major proposals. Open a thread per RFC."},
        ],
    },
    {
        "name": "⚒️ DEVELOPMENT",
        "channels": [
            {"name": "tasks",       "type": "text", "topic": "Task feed from the Orchestrator. Use /task take|done|status."},
            {"name": "dev-general", "type": "text", "topic": "Free-form technical discussion."},
            {"name": "help",        "type": "text", "topic": "Questions welcome. Everyone answers."},
        ],
    },
    {
        "name": "🤖 BOT",
        "channels": [
            {"name": "audit-log", "type": "text", "topic": "AI Orchestrator action log. Read-only for humans."},
        ],
    },
    {
        "name": "🔊 VOICE",
        "channels": [
            {"name": "Construction Site", "type": "voice"},
            {"name": "Mob Programming",   "type": "voice"},
        ],
    },
]


async def setup() -> None:
    intents = discord.Intents.default()
    intents.members = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        guild = client.get_guild(GUILD_ID)
        if guild is None:
            print(f"❌  Guild {GUILD_ID} not found. Is the bot in the server?")
            await client.close()
            return

        print(f"✅  Connected to: {guild.name}")

        # ---- Roles ----
        existing_roles = {r.name for r in guild.roles}
        created_roles: dict[str, discord.Role] = {}

        for name, color, hoist, mentionable in ROLES:
            if name in existing_roles:
                role = discord.utils.get(guild.roles, name=name)
                print(f"   ↩️  Role exists: {name}")
            else:
                role = await guild.create_role(
                    name=name,
                    color=discord.Color(color),
                    hoist=hoist,
                    mentionable=mentionable,
                    reason="Tower of Babel setup",
                )
                print(f"   ✅  Created role: {name}")
            if role:
                created_roles[name] = role

        # ---- Categories & channels ----
        existing_channels = {c.name for c in guild.channels}

        for cat_def in CATEGORIES_AND_CHANNELS:
            cat_name = cat_def["name"]

            # Find or create category
            category = discord.utils.get(guild.categories, name=cat_name)
            if category is None:
                category = await guild.create_category(
                    cat_name, reason="Tower of Babel setup"
                )
                print(f"\n   📁  Created category: {cat_name}")
            else:
                print(f"\n   ↩️  Category exists: {cat_name}")

            for ch_def in cat_def["channels"]:
                ch_name = ch_def["name"]
                ch_type = ch_def["type"]
                topic   = ch_def.get("topic", "")

                if ch_name in existing_channels:
                    print(f"      ↩️  Channel exists: #{ch_name}")
                    continue

                if ch_type == "text":
                    ch = await guild.create_text_channel(
                        ch_name,
                        category=category,
                        topic=topic,
                        reason="Tower of Babel setup",
                    )
                    # #announcements — only Architects+ and bot can send
                    if ch_name == "announcements":
                        await ch.set_permissions(
                            guild.default_role, send_messages=False
                        )
                        for role_name in ("🏛️ Architect", "🛡️ Keeper", "🤖 Orchestrator"):
                            role = created_roles.get(role_name)
                            if role:
                                await ch.set_permissions(role, send_messages=True)

                    # #audit-log — read-only for everyone except bot
                    if ch_name == "audit-log":
                        await ch.set_permissions(
                            guild.default_role, send_messages=False
                        )
                        bot_role = created_roles.get("🤖 Orchestrator")
                        if bot_role:
                            await ch.set_permissions(bot_role, send_messages=True)

                else:  # voice
                    ch = await guild.create_voice_channel(
                        ch_name,
                        category=category,
                        reason="Tower of Babel setup",
                    )

                print(f"      ✅  Created {'🔊' if ch_type == 'voice' else '#'}{ch_name}")

        print("\n🗼  Server setup complete!")
        await client.close()

    await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(setup())
