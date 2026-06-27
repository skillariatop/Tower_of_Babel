"""
GitHub Events поллер — замена вебхукам для локального запуска.
Каждый час опрашивает GitHub на предмет новых issues, PR и релизов,
затем вызывает те же обработчики, что и вебхук-сервер.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx
from discord.ext import commands, tasks

from bot.config import settings
from integrations.github import BASE, _auth_headers

log = logging.getLogger("tower.poller")

_STATE_FILE = Path(".poller_state")


def _load_last_check() -> str:
    if _STATE_FILE.exists():
        val = _STATE_FILE.read_text().strip()
        if val:
            return val
    return datetime.now(timezone.utc).isoformat()


def _save_last_check(ts: str) -> None:
    _STATE_FILE.write_text(ts)


class GitHubPollerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._last_check = _load_last_check()
        self._poll_loop.start()

    def cog_unload(self) -> None:
        self._poll_loop.cancel()

    @tasks.loop(hours=1)
    async def _poll_loop(self) -> None:
        try:
            await self._poll()
        except Exception as exc:
            log.error("Poll failed: %s", exc)

    @_poll_loop.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()

    async def _poll(self) -> None:
        from integrations.webhooks import (
            _handle_issues,
            _handle_pull_request,
            _handle_release,
        )

        since = self._last_check
        now = datetime.now(timezone.utc).isoformat()
        log.info("Polling GitHub since %s", since)
        found = 0

        async with httpx.AsyncClient(timeout=15) as client:

            # ── Issues ────────────────────────────────────────────────────
            r = await client.get(
                f"{BASE}/repos/{settings.github_repo}/issues",
                headers=_auth_headers(),
                params={"state": "all", "since": since, "per_page": "50"},
            )
            if r.status_code == 200:
                for issue in r.json():
                    if "pull_request" in issue:
                        continue
                    created_at = issue.get("created_at", "")
                    closed_at = issue.get("closed_at") or ""
                    if created_at >= since:
                        await _handle_issues({"action": "opened", "issue": issue})
                        found += 1
                    elif closed_at >= since and issue["state"] == "closed":
                        await _handle_issues({"action": "closed", "issue": issue})
                        found += 1
                    # Detect assignment: check if assignee was set and issue is recent
                    elif issue.get("assignee") and issue.get("updated_at", "") >= since:
                        assignee = issue["assignee"]
                        await _handle_issues({
                            "action": "assigned",
                            "issue": issue,
                            "assignee": assignee,
                        })
                        found += 1

            # ── Pull Requests ─────────────────────────────────────────────
            r2 = await client.get(
                f"{BASE}/repos/{settings.github_repo}/pulls",
                headers=_auth_headers(),
                params={
                    "state": "all",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": "20",
                },
            )
            if r2.status_code == 200:
                for pr in r2.json():
                    if pr.get("updated_at", "") < since:
                        break
                    created_at = pr.get("created_at", "")
                    merged_at = pr.get("merged_at") or ""
                    if created_at >= since:
                        await _handle_pull_request({"action": "opened", "pull_request": pr})
                        found += 1
                    elif merged_at >= since:
                        pr_copy = dict(pr)
                        pr_copy["merged"] = True
                        await _handle_pull_request({"action": "closed", "pull_request": pr_copy})
                        found += 1

            # ── Latest Release ────────────────────────────────────────────
            r3 = await client.get(
                f"{BASE}/repos/{settings.github_repo}/releases/latest",
                headers=_auth_headers(),
            )
            if r3.status_code == 200:
                release = r3.json()
                published_at = release.get("published_at") or ""
                if published_at >= since:
                    await _handle_release({"action": "published", "release": release})
                    found += 1

        self._last_check = now
        _save_last_check(now)
        log.info("Poll complete — %d event(s) processed. Next check in 1 hour.", found)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GitHubPollerCog(bot))
