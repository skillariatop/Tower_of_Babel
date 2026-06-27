"""
Metrics engine — collects velocity, activity, and quality data.

Surfaces:
  /metrics          — Discord embed with key stats
  weekly digest     — appended to the regular digest
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from bot.config import settings
from integrations.github import BASE, _auth_headers

log = logging.getLogger("tower.metrics")


@dataclass
class ProjectMetrics:
    period_days: int = 7

    # Velocity
    issues_opened: int = 0
    issues_closed: int = 0
    prs_merged: int = 0
    prs_opened: int = 0

    # People
    active_contributors: set[str] = field(default_factory=set)
    new_contributors: set[str] = field(default_factory=set)
    all_time_contributors: set[str] = field(default_factory=set)

    # Governance
    decisions_made: int = 0
    votes_held: int = 0

    # Backlog health
    open_issues: int = 0
    stale_issues: int = 0          # open, no activity > 7 days
    unassigned_tasks: int = 0

    # Review quality (rough proxy)
    ai_reviews_posted: int = 0

    @property
    def close_rate(self) -> float:
        if self.issues_opened == 0:
            return 0.0
        return self.issues_closed / self.issues_opened

    @property
    def merge_rate(self) -> float:
        if self.prs_opened == 0:
            return 0.0
        return self.prs_merged / self.prs_opened

    def summary_lines(self) -> list[str]:
        lines = [
            f"**Velocity ({self.period_days}d)**",
            f"  Issues opened / closed: {self.issues_opened} / {self.issues_closed} "
            f"({self.close_rate:.0%})",
            f"  PRs opened / merged: {self.prs_opened} / {self.prs_merged} "
            f"({self.merge_rate:.0%})",
            "",
            f"**Contributors**",
            f"  Active this period: {len(self.active_contributors)}",
            f"  New this period: {len(self.new_contributors)}",
            f"  All-time: {len(self.all_time_contributors)}",
            "",
            f"**Backlog**",
            f"  Open issues: {self.open_issues}",
            f"  Stale (>7d): {self.stale_issues}",
            f"  Unassigned tasks: {self.unassigned_tasks}",
            "",
            f"**Governance**",
            f"  Decisions accepted: {self.decisions_made}",
        ]
        return lines


async def collect(period_days: int = 7) -> ProjectMetrics:
    m = ProjectMetrics(period_days=period_days)
    since = datetime.now(timezone.utc) - timedelta(days=period_days)
    since_str = since.isoformat()
    now = datetime.now(timezone.utc)

    async with httpx.AsyncClient(timeout=15) as client:

        # --- Recent issues ---
        r = await client.get(
            f"{BASE}/repos/{settings.github_repo}/issues",
            headers=_auth_headers(),
            params={"state": "all", "since": since_str, "per_page": "100"},
        )
        r.raise_for_status()
        for issue in r.json():
            if "pull_request" in issue:
                continue
            created = datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00"))
            if created >= since:
                m.issues_opened += 1
                login = issue["user"]["login"]
                m.active_contributors.add(login)
            if issue["state"] == "closed":
                closed_at = issue.get("closed_at") or ""
                if closed_at:
                    closed_dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                    if closed_dt >= since:
                        m.issues_closed += 1
                        for a in issue.get("assignees", []):
                            m.active_contributors.add(a["login"])

        # --- All-time contributors (from contributors endpoint) ---
        r2 = await client.get(
            f"{BASE}/repos/{settings.github_repo}/contributors",
            headers=_auth_headers(),
            params={"per_page": "100"},
        )
        if r2.status_code == 200:
            m.all_time_contributors = {c["login"] for c in r2.json()}

        # --- PRs ---
        r3 = await client.get(
            f"{BASE}/repos/{settings.github_repo}/pulls",
            headers=_auth_headers(),
            params={"state": "all", "per_page": "100", "sort": "updated", "direction": "desc"},
        )
        r3.raise_for_status()
        for pr in r3.json():
            created = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
            if created >= since:
                m.prs_opened += 1
                m.active_contributors.add(pr["user"]["login"])
            if pr.get("merged_at"):
                merged = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
                if merged >= since:
                    m.prs_merged += 1

        # --- Backlog health ---
        r4 = await client.get(
            f"{BASE}/repos/{settings.github_repo}/issues",
            headers=_auth_headers(),
            params={"state": "open", "per_page": "100"},
        )
        r4.raise_for_status()
        for issue in r4.json():
            if "pull_request" in issue:
                continue
            m.open_issues += 1
            updated = datetime.fromisoformat(issue["updated_at"].replace("Z", "+00:00"))
            if (now - updated).days > 7:
                m.stale_issues += 1
            labels = [l["name"] for l in issue.get("labels", [])]
            if "task" in labels and not issue.get("assignees"):
                m.unassigned_tasks += 1

    # --- Decisions from decisions/ ---
    decisions_dir = settings.decisions_dir
    if decisions_dir.exists():
        for f in decisions_dir.glob("[0-9][0-9][0-9][0-9]-*.yaml"):
            try:
                with open(f, encoding="utf-8") as fp:
                    doc: dict[str, Any] = yaml.safe_load(fp)
                decided_at_str = doc.get("decided_at", "")
                if not decided_at_str:
                    continue
                decided_at = datetime.fromisoformat(decided_at_str).replace(tzinfo=timezone.utc)
                if decided_at >= since and doc.get("status") == "accepted":
                    m.decisions_made += 1
            except Exception:
                continue

    # New contributors = active this period who weren't contributors before
    m.new_contributors = m.active_contributors - m.all_time_contributors

    log.info(
        "Metrics collected: %d issues, %d PRs, %d contributors",
        m.open_issues, m.prs_opened, len(m.active_contributors),
    )
    return m
