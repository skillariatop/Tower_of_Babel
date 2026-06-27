"""
Task assignment engine.

Priority order for suggesting an assignee:
  1. Volunteer (commented "I'll take this" on the Issue)
  2. Member with matching domain skills (based on past closed issues)
  3. Member with lowest current open-issue workload
"""

import logging
from dataclasses import dataclass, field

import httpx

from bot.config import settings
from integrations.github import BASE, _auth_headers, Issue, list_open_issues

log = logging.getLogger("tower.assign")


@dataclass
class MemberProfile:
    login: str
    closed_labels: list[str] = field(default_factory=list)   # labels of past closed issues
    open_count: int = 0                                       # current open issues assigned


async def build_profiles() -> dict[str, MemberProfile]:
    """Scan recent closed + open issues to build contributor profiles."""
    profiles: dict[str, MemberProfile] = {}

    async with httpx.AsyncClient() as client:
        # Closed issues — extract skills from labels
        r = await client.get(
            f"{BASE}/repos/{settings.github_repo}/issues",
            headers=_auth_headers(),
            params={"state": "closed", "per_page": "100", "assignee": "*"},
            timeout=15,
        )
        r.raise_for_status()
        for issue in r.json():
            if "pull_request" in issue:
                continue
            for assignee in issue.get("assignees", []):
                login = assignee["login"]
                p = profiles.setdefault(login, MemberProfile(login=login))
                p.closed_labels.extend(l["name"] for l in issue.get("labels", []))

        # Open issues — count current workload
        r2 = await client.get(
            f"{BASE}/repos/{settings.github_repo}/issues",
            headers=_auth_headers(),
            params={"state": "open", "per_page": "100", "assignee": "*"},
            timeout=15,
        )
        r2.raise_for_status()
        for issue in r2.json():
            if "pull_request" in issue:
                continue
            for assignee in issue.get("assignees", []):
                login = assignee["login"]
                p = profiles.setdefault(login, MemberProfile(login=login))
                p.open_count += 1

    return profiles


def suggest_assignees(
    issue: Issue,
    profiles: dict[str, MemberProfile],
    top_n: int = 3,
) -> list[str]:
    """Return up to top_n GitHub logins ranked by domain fit and low workload."""
    if not profiles:
        return []

    domain_labels = {l for l in issue.labels if l.startswith("domain:")}

    def score(p: MemberProfile) -> float:
        # +2 for each past closed issue in the same domain
        domain_score = sum(
            2 for l in p.closed_labels if l in domain_labels
        )
        # −1 for each open issue already assigned (workload penalty)
        workload_penalty = p.open_count
        return domain_score - workload_penalty

    ranked = sorted(profiles.values(), key=score, reverse=True)
    return [p.login for p in ranked[:top_n] if score(p) > -5]


async def auto_suggest_for_issue(issue: Issue) -> list[str]:
    """Build profiles and return suggestions for a single issue."""
    try:
        profiles = await build_profiles()
        return suggest_assignees(issue, profiles)
    except Exception as exc:
        log.error("Assignment suggestion failed for #%d: %s", issue.number, exc)
        return []
