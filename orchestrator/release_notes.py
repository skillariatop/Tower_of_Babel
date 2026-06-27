"""
Release notes generator.

Triggered when a tag/release is pushed (via GitHub webhook).
Collects merged PRs since last release, calls LLM to write notes,
posts to #announcements.
"""

import logging
from typing import Optional

import httpx

from bot.config import settings
from integrations.github import BASE, _auth_headers
from orchestrator.llm import llm

log = logging.getLogger("tower.release")

_RELEASE_PROMPT = """Write release notes for version {tag} of Tower of Babel.

Merged pull requests:
{pr_list}

Write in markdown. Structure:
## 🗼 Tower of Babel {tag}

**What's new** (group related PRs under sub-headings like Features, Fixes, Infra)

**Contributors** (list GitHub usernames who contributed)

Be specific and developer-friendly. Max 400 words. Use past tense."""


async def generate_release_notes(tag: str, since_tag: Optional[str] = None) -> str:
    """Fetch merged PRs since last tag, generate release notes string."""
    prs = await _get_prs_since(since_tag)

    if not prs:
        return f"## 🗼 Tower of Babel {tag}\n\nNo pull requests found for this release."

    pr_lines = "\n".join(
        f"- #{pr['number']} **{pr['title']}** by @{pr['user']}"
        for pr in prs
    )
    prompt = _RELEASE_PROMPT.format(tag=tag, pr_list=pr_lines)
    notes = await llm.complete(prompt)
    return notes


async def _get_prs_since(since_tag: Optional[str]) -> list[dict]:
    """Get merged PRs. If since_tag given, only PRs merged after that tag's date."""
    since_date: Optional[str] = None

    if since_tag:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{BASE}/repos/{settings.github_repo}/releases/tags/{since_tag}",
                    headers=_auth_headers(),
                    timeout=10,
                )
                if r.status_code == 200:
                    since_date = r.json().get("published_at")
        except Exception:
            pass

    async with httpx.AsyncClient() as client:
        params: dict = {"state": "closed", "per_page": "50", "sort": "updated", "direction": "desc"}
        r = await client.get(
            f"{BASE}/repos/{settings.github_repo}/pulls",
            headers=_auth_headers(),
            params=params,
            timeout=15,
        )
        r.raise_for_status()

    results = []
    for pr in r.json():
        if not pr.get("merged_at"):
            continue
        if since_date and pr["merged_at"] < since_date:
            break
        results.append({
            "number": pr["number"],
            "title": pr["title"],
            "user": pr["user"]["login"],
            "merged_at": pr["merged_at"],
        })
    return results
