"""
Weekly digest generator.

Collects the past 7 days of activity:
  - Accepted decisions (from decisions/ directory)
  - Closed GitHub Issues
  - Merged PRs
  - New contributors

Then calls the LLM to write a human-friendly summary and posts it to #announcements.
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from bot.config import settings
from integrations import github
from orchestrator.llm import llm

log = logging.getLogger("tower.digest")

_DIGEST_PROMPT = """
Write a weekly project digest for Tower of Babel — a collaborative open-source
development system built by students of Skillaria.Top school.

Activity data for the past 7 days:
---
{activity}
---

Write a concise, friendly digest in markdown. Structure:
## 🗼 Tower of Babel — Weekly Digest

### ✅ Decisions made
(list accepted decisions, 1 line each)

### 🚀 Completed tasks
(list closed issues, 1 line each)

### 🔀 Merged PRs
(list merged PRs, 1 line each)

### 🧱 New contributors
(list new contributors if any, otherwise skip section)

### 📋 What's next
(2–3 most important open tasks based on the data)

Keep the tone encouraging and energetic. Max 400 words total.
If a section has no items, skip it entirely.
"""


async def generate_weekly_digest() -> str:
    """Generate a weekly digest string. Returns markdown text."""
    since = datetime.now(timezone.utc) - timedelta(days=7)

    # --- Decisions from decisions/ ---
    decisions_dir = settings.decisions_dir
    recent_decisions: list[str] = []
    if decisions_dir.exists():
        for f in sorted(decisions_dir.glob("[0-9][0-9][0-9][0-9]-*.yaml")):
            try:
                with open(f, encoding="utf-8") as fp:
                    doc: dict[str, Any] = yaml.safe_load(fp)
                decided_at_str = doc.get("decided_at", "")
                if not decided_at_str:
                    continue
                decided_at = datetime.fromisoformat(decided_at_str).replace(tzinfo=timezone.utc)
                if decided_at >= since and doc.get("status") == "accepted":
                    recent_decisions.append(f"- [{doc.get('title')}] ({doc.get('level')})")
            except Exception:
                continue

    # --- GitHub: closed issues ---
    closed_issues: list[str] = []
    try:
        issues = await _get_recently_closed_issues(since)
        for i in issues:
            closed_issues.append(f"- #{i['number']} {i['title']} (by {i['user']})")
    except Exception as exc:
        log.warning("Could not fetch closed issues: %s", exc)

    # --- GitHub: merged PRs ---
    merged_prs: list[str] = []
    new_contributors: list[str] = []
    try:
        prs = await _get_recently_merged_prs(since)
        for pr in prs:
            merged_prs.append(f"- #{pr['number']} {pr['title']} (by {pr['user']})")
        # New contributors = authors who appear in merged PRs but not before
        new_contributors = list({pr["user"] for pr in prs})[:5]
    except Exception as exc:
        log.warning("Could not fetch merged PRs: %s", exc)

    # --- Open tasks ---
    open_tasks: list[str] = []
    try:
        issues = await github.list_open_issues(label="task")
        for i in issues[:5]:
            open_tasks.append(f"- #{i.number} {i.title}")
    except Exception as exc:
        log.warning("Could not fetch open tasks: %s", exc)

    activity = "\n".join(
        [f"Accepted decisions ({len(recent_decisions)}):"]
        + (recent_decisions or ["  (none)"])
        + ["", f"Closed issues ({len(closed_issues)}):"]
        + (closed_issues or ["  (none)"])
        + ["", f"Merged PRs ({len(merged_prs)}):"]
        + (merged_prs or ["  (none)"])
        + ["", f"Recent contributors: {', '.join(new_contributors) or 'none'}"]
        + ["", "Open tasks (top 5):"]
        + (open_tasks or ["  (none)"])
    )

    digest = await llm.complete(_DIGEST_PROMPT.format(activity=activity))
    return digest


async def _get_recently_closed_issues(since: datetime) -> list[dict[str, Any]]:
    import httpx
    from integrations.github import BASE, _auth_headers
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE}/repos/{settings.github_repo}/issues",
            headers=_auth_headers(),
            params={
                "state": "closed",
                "since": since.isoformat(),
                "per_page": "30",
            },
            timeout=15,
        )
        r.raise_for_status()
    return [
        {"number": i["number"], "title": i["title"], "user": i["user"]["login"]}
        for i in r.json()
        if "pull_request" not in i
    ]


async def _get_recently_merged_prs(since: datetime) -> list[dict[str, Any]]:
    import httpx
    from integrations.github import BASE, _auth_headers
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE}/repos/{settings.github_repo}/pulls",
            headers=_auth_headers(),
            params={"state": "closed", "per_page": "30", "sort": "updated", "direction": "desc"},
            timeout=15,
        )
        r.raise_for_status()
    return [
        {"number": pr["number"], "title": pr["title"], "user": pr["user"]["login"]}
        for pr in r.json()
        if pr.get("merged_at")
        and datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00")) >= since
    ]
