"""
Deadline tracker — background loop that watches open GitHub Issues.

Stages:
  stale_days=3  → reminder DM / #tasks mention to assignee
  stale_days=7  → escalation message to Architect of the domain
  stale_days=14 → auto-unassign and repost to #tasks as free task
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
import httpx

from bot.config import settings
from integrations.github import BASE, _auth_headers, add_comment

log = logging.getLogger("tower.deadlines")

REMIND_DAYS = 3
ESCALATE_DAYS = 7
REASSIGN_DAYS = 14

# Domain → Architect role name mapping (adjust as server grows)
DOMAIN_ROLE: dict[str, str] = {
    "domain:bot":            "🏛️ Architect",
    "domain:orchestrator":   "🏛️ Architect",
    "domain:infra":          "🏛️ Architect",
    "domain:docs":           "🏛️ Architect",
    "domain:integrations":   "🏛️ Architect",
}


async def _get_stale_issues() -> list[dict]:
    """Return open assigned issues with their last-update age."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE}/repos/{settings.github_repo}/issues",
            headers=_auth_headers(),
            params={"state": "open", "per_page": "100", "assignee": "*"},
            timeout=15,
        )
        r.raise_for_status()

    now = datetime.now(timezone.utc)
    stale = []
    for issue in r.json():
        if "pull_request" in issue or not issue.get("assignees"):
            continue
        updated = datetime.fromisoformat(issue["updated_at"].replace("Z", "+00:00"))
        age_days = (now - updated).days
        if age_days >= REMIND_DAYS:
            stale.append({
                "number": issue["number"],
                "title": issue["title"],
                "url": issue["html_url"],
                "assignees": [a["login"] for a in issue["assignees"]],
                "labels": [l["name"] for l in issue["labels"]],
                "age_days": age_days,
                "updated_at": updated,
            })
    return stale


async def run_deadline_check(guild: Optional[discord.Guild]) -> int:
    """
    Check all stale issues, post reminders/escalations.
    Returns number of issues acted on.
    """
    try:
        stale = await _get_stale_issues()
    except Exception as exc:
        log.error("Could not fetch stale issues: %s", exc)
        return 0

    tasks_ch: Optional[discord.TextChannel] = None
    if guild:
        tasks_ch = discord.utils.get(guild.text_channels, name=settings.tasks_channel_name)

    acted = 0
    for issue in stale:
        age = issue["age_days"]
        num = issue["number"]
        title = issue["title"]
        url = issue["url"]
        assignees = issue["assignees"]
        labels = issue["labels"]

        if age >= REASSIGN_DAYS:
            await _auto_reassign(num, title, url, assignees, tasks_ch)
            acted += 1

        elif age >= ESCALATE_DAYS:
            await _escalate(num, title, url, assignees, labels, guild, tasks_ch)
            acted += 1

        elif age >= REMIND_DAYS:
            await _remind(num, title, url, assignees, age, tasks_ch)
            acted += 1

    log.info("Deadline check: %d stale issues acted on", acted)
    return acted


async def _remind(
    num: int, title: str, url: str,
    assignees: list[str], age: int,
    tasks_ch: Optional[discord.TextChannel],
) -> None:
    msg = (
        f"⏰ **Reminder:** [#{num} {title}]({url}) has had no activity "
        f"for **{age} days**. Assigned to: {', '.join(f'`{a}`' for a in assignees)}\n"
        f"Use `/task done {num}` when complete, or comment on the issue if blocked."
    )
    if tasks_ch:
        await tasks_ch.send(msg)
    await add_comment(num, f"⏰ Automated reminder: no activity for {age} days.")
    log.info("Reminded issue #%d (age=%d days)", num, age)


async def _escalate(
    num: int, title: str, url: str,
    assignees: list[str], labels: list[str],
    guild: Optional[discord.Guild],
    tasks_ch: Optional[discord.TextChannel],
) -> None:
    domain = next((l for l in labels if l.startswith("domain:")), None)
    role_name = DOMAIN_ROLE.get(domain or "", "🏛️ Architect")

    mention = ""
    if guild:
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            mention = role.mention

    msg = (
        f"🚨 **Escalation** {mention}: [#{num} {title}]({url}) "
        f"has been stalled for ≥{ESCALATE_DAYS} days.\n"
        f"Assignee(s): {', '.join(f'`{a}`' for a in assignees)} — please intervene."
    )
    if tasks_ch:
        await tasks_ch.send(msg)
    await add_comment(num, f"🚨 Escalated to {role_name}: stalled ≥{ESCALATE_DAYS} days.")
    log.info("Escalated issue #%d to %s", num, role_name)


async def _auto_reassign(
    num: int, title: str, url: str,
    assignees: list[str],
    tasks_ch: Optional[discord.TextChannel],
) -> None:
    # Remove assignees via GitHub API
    try:
        async with httpx.AsyncClient() as client:
            await client.delete(
                f"{BASE}/repos/{settings.github_repo}/issues/{num}/assignees",
                headers=_auth_headers(),
                json={"assignees": assignees},
                timeout=15,
            )
    except Exception as exc:
        log.error("Could not unassign issue #%d: %s", num, exc)
        return

    msg = (
        f"🔄 **Auto-reassigned:** [#{num} {title}]({url}) was stalled ≥{REASSIGN_DAYS} days. "
        f"Previous assignee(s) `{'`, `'.join(assignees)}` removed — task is free to take.\n"
        f"Use `/task take {num}` to claim it."
    )
    if tasks_ch:
        await tasks_ch.send(msg)
    await add_comment(
        num,
        f"🔄 Auto-unassigned after {REASSIGN_DAYS}+ days of inactivity. Task is open for anyone to take."
    )
    log.info("Auto-reassigned issue #%d (was: %s)", num, assignees)
