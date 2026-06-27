"""
Decision decomposer — reads a decision YAML and uses the LLM to break it
into a list of GitHub Issues, then creates them.

Flow:
    decision YAML
        ↓ LLM prompt
    [{title, body, labels, estimate}]
        ↓ GitHub API
    Issues with labels and cross-references
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from integrations import github
from orchestrator.llm import llm

log = logging.getLogger("tower.decompose")

# Labels that must exist before decomposition runs
REQUIRED_LABELS = [
    {"name": "task",             "color": "0075ca", "description": "Development task"},
    {"name": "good first issue", "color": "7057ff", "description": "Good for newcomers"},
    {"name": "from-vote",        "color": "e4e669", "description": "Auto-created from a community vote"},
    {"name": "size:S",           "color": "c2e0c6", "description": "Small task (~2h)"},
    {"name": "size:M",           "color": "fef2c0", "description": "Medium task (~1 day)"},
    {"name": "size:L",           "color": "f9d0c4", "description": "Large task (~3+ days)"},
    {"name": "domain:bot",       "color": "d4c5f9", "description": "Discord bot"},
    {"name": "domain:orchestrator", "color": "bfd4f2", "description": "AI orchestrator"},
    {"name": "domain:infra",     "color": "e4e4e4", "description": "Infrastructure"},
    {"name": "domain:docs",      "color": "cfd3d7", "description": "Documentation"},
    {"name": "domain:integrations", "color": "b4a8d1", "description": "GitHub/Discord integrations"},
]

_DECOMPOSE_PROMPT = """
You are breaking down a community decision into concrete GitHub Issues.

Decision:
---
{decision_text}
---

Tasks hint from the decision author:
{tasks_hint}

Return a JSON array of issues to create. Each issue:
{{
  "title": "Short imperative title (verb + noun)",
  "body": "## Context\\n...\\n## Acceptance criteria\\n- [ ] ...",
  "labels": ["task", "domain:bot"],   // always include "task" + one domain label
  "estimate": "S" | "M" | "L",
  "good_first_issue": true | false    // true only if a newcomer can reasonably do it
}}

Rules:
- 2–7 issues max. If the decision is small, 1–2 is fine.
- Each issue must be independently completable.
- Titles must be unique and start with a verb (Add, Fix, Create, Implement, Write...).
- Body must have ## Context and ## Acceptance criteria sections.
- Only use these domain labels: domain:bot, domain:orchestrator, domain:infra, domain:docs, domain:integrations.
- Estimate S = ~2h, M = ~1 day, L = ~3+ days.
- Return ONLY the JSON array, no markdown fences.
"""


@dataclass
class DecomposedIssue:
    title: str
    body: str
    labels: list[str]
    estimate: str
    good_first_issue: bool
    github_issue: github.Issue | None = None


async def decompose_decision(decision_path: Path) -> list[DecomposedIssue]:
    """Read a decision YAML, call LLM, create GitHub Issues. Returns created issues."""

    with open(decision_path, encoding="utf-8") as f:
        doc: dict[str, Any] = yaml.safe_load(f)

    if doc.get("status") != "accepted":
        log.info("Skipping non-accepted decision: %s", decision_path.name)
        return []

    decision_text = (
        f"Title: {doc.get('title', '')}\n"
        f"Level: {doc.get('level', '')}\n"
        f"Decision: {doc.get('decision', '')}"
    )
    tasks_hint = doc.get("tasks_hint") or "No hint provided."

    prompt = _DECOMPOSE_PROMPT.format(
        decision_text=decision_text.strip(),
        tasks_hint=tasks_hint.strip(),
    )

    log.info("Decomposing decision: %s", decision_path.name)
    raw: list[dict[str, Any]] = await llm.complete_json(prompt)

    # Ensure required labels exist in the repo
    try:
        await github.ensure_labels(REQUIRED_LABELS)
    except Exception as exc:
        log.warning("Could not ensure labels: %s", exc)

    decision_id = doc.get("id", "?")
    discord_thread = doc.get("discord_thread", "")

    results: list[DecomposedIssue] = []
    for item in raw:
        title = item.get("title", "Untitled task")
        labels: list[str] = item.get("labels", ["task"])
        estimate = item.get("estimate", "M")
        is_gfi = item.get("good_first_issue", False)

        if f"size:{estimate}" not in labels:
            labels.append(f"size:{estimate}")
        if is_gfi and "good first issue" not in labels:
            labels.append("good first issue")
        labels.append("from-vote")

        body = item.get("body", "")
        footer = (
            f"\n\n---\n*Auto-decomposed from Decision #{decision_id}*"
            + (f" · [Discord thread]({discord_thread})" if discord_thread else "")
            + f"\n*Estimate: {estimate}*"
        )

        di = DecomposedIssue(
            title=title,
            body=body + footer,
            labels=labels,
            estimate=estimate,
            good_first_issue=is_gfi,
        )

        try:
            issue = await github.create_issue(title=title, body=di.body, labels=labels)
            di.github_issue = issue
            log.info("Created issue #%d: %s", issue.number, title)
        except Exception as exc:
            log.error("Failed to create issue '%s': %s", title, exc)

        results.append(di)

    return results


async def decompose_decision_text(title: str, decision_text: str, tasks_hint: str = "") -> list[DecomposedIssue]:
    """Decompose from raw text (used by the /orchestrate command)."""
    tmp_doc = {"title": title, "level": "routine", "decision": decision_text, "tasks_hint": tasks_hint}
    prompt = _DECOMPOSE_PROMPT.format(
        decision_text=f"Title: {title}\nDecision: {decision_text}",
        tasks_hint=tasks_hint or "No hint provided.",
    )
    raw: list[dict[str, Any]] = await llm.complete_json(prompt)

    try:
        await github.ensure_labels(REQUIRED_LABELS)
    except Exception as exc:
        log.warning("Could not ensure labels: %s", exc)

    results: list[DecomposedIssue] = []
    for item in raw:
        title_item = item.get("title", "Untitled task")
        labels: list[str] = item.get("labels", ["task"])
        estimate = item.get("estimate", "M")
        is_gfi = item.get("good_first_issue", False)
        if f"size:{estimate}" not in labels:
            labels.append(f"size:{estimate}")
        if is_gfi and "good first issue" not in labels:
            labels.append("good first issue")

        body = item.get("body", "") + f"\n\n---\n*Estimate: {estimate}*"
        di = DecomposedIssue(title=title_item, body=body, labels=labels, estimate=estimate, good_first_issue=is_gfi)
        try:
            issue = await github.create_issue(title=title_item, body=di.body, labels=labels)
            di.github_issue = issue
        except Exception as exc:
            log.error("Failed to create issue '%s': %s", title_item, exc)
        results.append(di)

    return results
