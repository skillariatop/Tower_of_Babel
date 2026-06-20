# Onboarding: Your First Week in Tower of Babel

## Day 1 — Orientation

**Goal: understand the system before touching code.**

1. Read the [README](../README.md) top to bottom.
2. Browse `decisions/` — read the bootstrap decision. This is how every decision in the project is recorded.
3. Look at the open Issues on GitHub. Notice the labels and how tasks are structured.
4. Join the Discord channels in order: `#announcements` → `#rfc` → `#dev-general`.

## Day 2 — Environment

```bash
git clone git@github.com:<your-fork>/Tower_of_Babel.git
cd Tower_of_Babel
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Run `pytest` — all tests should pass (there are only a few smoke tests right now; that's expected at this stage).

## Day 3 — Your First Contribution

1. Pick a `good first issue`.
2. Comment "I'll take this" on the Issue.
3. Create a branch: `feat/<issue-number>-short-slug`.
4. Make the change, run `ruff check . && pytest`, open a PR.

## How the Orchestrator fits in

The bot reads `decisions/` and turns accepted decisions into GitHub Issues. Right now (Phase 1) the bot is being built — so the Orchestrator doesn't exist yet. Tasks are created and assigned manually. Your job is to help build the bot that will eventually do all this automatically.

## Useful commands (once the bot is running)

| Command | What it does |
|---|---|
| `/vote start "question"` | Opens a vote in `#voting` |
| `/task take <id>` | Assigns an Issue to yourself |
| `/task done <id>` | Marks an Issue as done |
| `/task status <id>` | Shows current task status |

## Where to ask for help

- Quick questions → `#help`
- Design discussions → `#dev-general`
- Big proposals → open an RFC in `#rfc`
- Stuck for more than 30 minutes → ask, don't suffer in silence
