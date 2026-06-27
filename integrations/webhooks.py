"""
FastAPI app — receives GitHub webhooks and posts events to Discord.

Run alongside the bot:
    uvicorn integrations.webhooks:app --port 8080

GitHub → Settings → Webhooks → add URL, choose events:
  issues, pull_request, check_run (CI status)
"""

import hashlib
import hmac
import logging
from typing import Any

import asyncio

import discord
from fastapi import FastAPI, Header, HTTPException, Request

from bot.config import settings

log = logging.getLogger("tower.webhooks")

app = FastAPI(title="Tower of Babel — GitHub Webhook Receiver")

# Injected at startup by the bot process
_discord_bot: discord.Client | None = None


def set_bot(bot: discord.Client) -> None:
    global _discord_bot
    _discord_bot = bot


# ------------------------------------------------------------------ #
#  Signature verification                                              #
# ------------------------------------------------------------------ #

WEBHOOK_SECRET = ""  # set via env var GITHUB_WEBHOOK_SECRET


def _verify_signature(body: bytes, sig_header: str | None) -> None:
    if not WEBHOOK_SECRET:
        return  # skip verification if secret not configured
    if not sig_header or not sig_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing signature")
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig_header):
        raise HTTPException(status_code=401, detail="Invalid signature")


# ------------------------------------------------------------------ #
#  Event handlers                                                      #
# ------------------------------------------------------------------ #

@app.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, str]:
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)
    payload: dict[str, Any] = await request.json()

    handler = _HANDLERS.get(x_github_event)
    if handler:
        await handler(payload)
    else:
        log.debug("Unhandled GitHub event: %s", x_github_event)

    return {"status": "ok"}


async def _handle_issues(payload: dict[str, Any]) -> None:
    action = payload.get("action", "")
    issue = payload.get("issue", {})
    number = issue.get("number")
    title = issue.get("title", "")
    url = issue.get("html_url", "")
    user = issue.get("user", {}).get("login", "?")

    messages = {
        "opened": f"📬 New issue [#{number} {title}]({url}) opened by **{user}**",
        "closed": f"✅ Issue [#{number} {title}]({url}) closed",
        "assigned": (
            f"🎯 Issue [#{number} {title}]({url}) assigned to "
            f"**{payload.get('assignee', {}).get('login', '?')}**"
        ),
        "reopened": f"🔄 Issue [#{number} {title}]({url}) reopened",
    }
    msg = messages.get(action)
    if msg:
        await _post_to_tasks(msg)


async def _handle_pull_request(payload: dict[str, Any]) -> None:
    from bot.cogs.admin import is_paused
    from orchestrator.review import review_pr_safe

    action = payload.get("action", "")
    pr = payload.get("pull_request", {})
    number = pr.get("number")
    title = pr.get("title", "")
    url = pr.get("html_url", "")
    user = pr.get("user", {}).get("login", "?")

    messages = {
        "opened": f"🔀 PR [#{number} {title}]({url}) opened by **{user}**",
        "closed": (
            f"{'✅ Merged' if pr.get('merged') else '❌ Closed'} PR "
            f"[#{number} {title}]({url})"
        ),
        "review_requested": f"👀 Review requested on [#{number} {title}]({url})",
    }
    msg = messages.get(action)
    if msg:
        await _post_to_tasks(msg)

    # Auto AI review when PR is opened (non-draft, not by the bot itself)
    if action == "opened" and not pr.get("draft") and not is_paused():
        asyncio.create_task(review_pr_safe(number))


async def _handle_check_run(payload: dict[str, Any]) -> None:
    if payload.get("action") != "completed":
        return
    check = payload.get("check_run", {})
    conclusion = check.get("conclusion", "")
    name = check.get("name", "CI")
    pr_urls = [p.get("html_url", "") for p in check.get("pull_requests", [])]

    if conclusion == "failure" and pr_urls:
        await _post_to_tasks(
            f"❌ **{name}** failed on {' '.join(pr_urls)}"
        )


async def _handle_release(payload: dict[str, Any]) -> None:
    from bot.cogs.admin import is_paused
    from orchestrator.release_notes import generate_release_notes

    if payload.get("action") != "published" or is_paused():
        return

    release = payload.get("release", {})
    tag = release.get("tag_name", "")
    if not tag:
        return

    try:
        notes = await generate_release_notes(tag)
    except Exception as exc:
        log.error("Release notes generation failed for %s: %s", tag, exc)
        return

    await _post_to_announcements(f"🚀 **Release {tag}**\n\n{notes[:1800]}")


_HANDLERS = {
    "issues": _handle_issues,
    "pull_request": _handle_pull_request,
    "check_run": _handle_check_run,
    "release": _handle_release,
}


async def _post_to_tasks(message: str) -> None:
    await _post_to_channel(settings.tasks_channel_name, message)


async def _post_to_announcements(message: str) -> None:
    await _post_to_channel(settings.announcements_channel_name, message)


async def _post_to_channel(channel_name: str, message: str) -> None:
    if _discord_bot is None:
        log.warning("Discord bot not available for webhook message")
        return
    for guild in _discord_bot.guilds:
        channel = discord.utils.get(guild.text_channels, name=channel_name)
        if channel:
            await channel.send(message)
            return
    log.warning("channel #%s not found in any guild", channel_name)
