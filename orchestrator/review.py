"""
AI PR reviewer — fetches the diff of a PR and posts a draft review comment.

The review is advisory only: it flags potential issues, does NOT approve or
request changes (that's for humans). The bot posts as a regular PR comment,
not a formal GitHub review, so it cannot block merges.
"""

import logging

import httpx

from bot.config import settings
from integrations.github import BASE, _auth_headers, add_comment
from orchestrator.llm import llm

log = logging.getLogger("tower.review")

MAX_DIFF_CHARS = 12_000  # truncate large diffs to stay within LLM context

_REVIEW_PROMPT = """You are doing a preliminary code review for a pull request.
Your role is advisory — a human reviewer makes the final call.

Pull Request: {title}
Author: {author}

Diff (may be truncated):
```diff
{diff}
```

Write a concise review comment in markdown. Structure:

### 🤖 AI Draft Review

**Summary** (1–2 sentences on what the PR does)

**Potential issues** (bugs, security concerns, broken logic — list only real problems)

**Suggestions** (optional improvements — keep it short, 2–3 max)

**Checklist**
- [ ] Tests cover the change
- [ ] No hardcoded secrets or credentials
- [ ] Error paths handled

If the diff is empty or trivial (docs/comments only), say so briefly and skip the checklist.
Be concise. Developers read fast. Max 300 words."""


async def review_pr(pr_number: int) -> str:
    """Fetch PR diff, run LLM review, post as comment. Returns comment URL."""
    async with httpx.AsyncClient() as client:
        # Get PR metadata
        r_meta = await client.get(
            f"{BASE}/repos/{settings.github_repo}/pulls/{pr_number}",
            headers=_auth_headers(),
            timeout=15,
        )
        r_meta.raise_for_status()
        meta = r_meta.json()

        # Get diff
        r_diff = await client.get(
            f"{BASE}/repos/{settings.github_repo}/pulls/{pr_number}",
            headers={**_auth_headers(), "Accept": "application/vnd.github.v3.diff"},
            timeout=30,
        )
        r_diff.raise_for_status()
        diff_text = r_diff.text

    title = meta.get("title", "")
    author = meta.get("user", {}).get("login", "?")

    if len(diff_text) > MAX_DIFF_CHARS:
        diff_text = diff_text[:MAX_DIFF_CHARS] + "\n\n... [diff truncated]"

    if not diff_text.strip():
        diff_text = "(empty diff)"

    prompt = _REVIEW_PROMPT.format(title=title, author=author, diff=diff_text)

    log.info("Running AI review for PR #%d", pr_number)
    review_text = await llm.complete(prompt)

    footer = (
        "\n\n---\n*🤖 Auto-generated draft review by Tower of Babel Orchestrator. "
        "This is advisory — a human reviewer makes the final decision.*"
    )
    await add_comment(pr_number, review_text + footer)
    log.info("Posted AI review for PR #%d", pr_number)
    return f"https://github.com/{settings.github_repo}/pull/{pr_number}"


async def review_pr_safe(pr_number: int) -> None:
    """Fire-and-forget wrapper that swallows errors."""
    try:
        await review_pr(pr_number)
    except Exception as exc:
        log.error("AI review failed for PR #%d: %s", pr_number, exc)
