"""
Thin async GitHub REST client.
Covers what the bot needs: Issues, labels, assignees, project status.
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from bot.config import settings

log = logging.getLogger("tower.github")

BASE = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


@dataclass
class Issue:
    number: int
    title: str
    url: str
    state: str
    assignees: list[str]
    labels: list[str]
    body: str


def _auth_headers() -> dict[str, str]:
    return {**HEADERS, "Authorization": f"Bearer {settings.github_token}"}


async def create_issue(
    title: str,
    body: str,
    labels: Optional[list[str]] = None,
    assignees: Optional[list[str]] = None,
) -> Issue:
    payload: dict[str, Any] = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    if assignees:
        payload["assignees"] = assignees

    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{BASE}/repos/{settings.github_repo}/issues",
            headers=_auth_headers(),
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

    log.info("Created issue #%d: %s", data["number"], title)
    return _parse_issue(data)


async def get_issue(number: int) -> Issue:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE}/repos/{settings.github_repo}/issues/{number}",
            headers=_auth_headers(),
            timeout=15,
        )
        r.raise_for_status()
    return _parse_issue(r.json())


async def assign_issue(number: int, assignees: list[str]) -> Issue:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{BASE}/repos/{settings.github_repo}/issues/{number}/assignees",
            headers=_auth_headers(),
            json={"assignees": assignees},
            timeout=15,
        )
        r.raise_for_status()
    log.info("Assigned issue #%d to %s", number, assignees)
    return _parse_issue(r.json())


async def close_issue(number: int, reason: str = "completed") -> Issue:
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            f"{BASE}/repos/{settings.github_repo}/issues/{number}",
            headers=_auth_headers(),
            json={"state": "closed", "state_reason": reason},
            timeout=15,
        )
        r.raise_for_status()
    log.info("Closed issue #%d (%s)", number, reason)
    return _parse_issue(r.json())


async def add_comment(number: int, body: str) -> None:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{BASE}/repos/{settings.github_repo}/issues/{number}/comments",
            headers=_auth_headers(),
            json={"body": body},
            timeout=15,
        )
        r.raise_for_status()


async def list_open_issues(label: Optional[str] = None) -> list[Issue]:
    params: dict[str, str] = {"state": "open", "per_page": "50"}
    if label:
        params["labels"] = label
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE}/repos/{settings.github_repo}/issues",
            headers=_auth_headers(),
            params=params,
            timeout=15,
        )
        r.raise_for_status()
    return [_parse_issue(i) for i in r.json() if "pull_request" not in i]


async def ensure_labels(labels: list[dict[str, str]]) -> None:
    """Create labels that don't exist yet. labels = [{"name": "...", "color": "rrggbb"}]"""
    async with httpx.AsyncClient() as client:
        existing_r = await client.get(
            f"{BASE}/repos/{settings.github_repo}/labels",
            headers=_auth_headers(),
            params={"per_page": "100"},
            timeout=15,
        )
        existing_r.raise_for_status()
        existing = {l["name"] for l in existing_r.json()}

        for label in labels:
            if label["name"] not in existing:
                await client.post(
                    f"{BASE}/repos/{settings.github_repo}/labels",
                    headers=_auth_headers(),
                    json=label,
                    timeout=15,
                )
                log.info("Created label: %s", label["name"])


def _parse_issue(data: dict[str, Any]) -> Issue:
    return Issue(
        number=data["number"],
        title=data["title"],
        url=data["html_url"],
        state=data["state"],
        assignees=[a["login"] for a in data.get("assignees", [])],
        labels=[l["name"] for l in data.get("labels", [])],
        body=data.get("body") or "",
    )
