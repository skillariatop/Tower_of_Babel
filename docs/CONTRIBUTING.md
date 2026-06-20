# Contributing to Tower of Babel

Welcome! This guide covers the full contribution loop from joining the project to getting your PR merged.

## Prerequisites

- You are a student at [Skillaria.Top](https://skillaria.top) who has reached the **Intern** level.
- You have the Discord invite link from your personal dashboard.
- You have a GitHub account.

## 1. Get access

1. Join the Discord server using the invite from your dashboard.
2. Introduce yourself in `#help` — you'll receive the 🧱 Apprentice role.
3. Fork this repository on GitHub.

## 2. Pick a task

- Browse Issues labelled [`good first issue`](https://github.com/skillariatop/Tower_of_Babel/labels/good%20first%20issue) for your first contribution.
- Claim it by commenting "I'll take this" — the Orchestrator (or a Mason+) will assign it to you.
- If you have your own idea, propose it in `#dev-general` or open an RFC in `#rfc`.

## 3. Work on it

```bash
# Clone your fork
git clone git@github.com:<your-username>/Tower_of_Babel.git
cd Tower_of_Babel

# Create a branch
git checkout -b feat/42-short-description   # Issue number first

# Set up the dev environment
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Copy env template and fill in your tokens (never commit this file)
cp .env.example .env
```

## 4. Code style

```bash
ruff check .       # lint
ruff format .      # format
mypy .             # type check
pytest             # tests
```

All four must pass before you open a PR. The CI checks the same things.

## 5. Open a PR

- Title format: `feat(scope): short description` / `fix(scope): …` / `docs: …`
- Reference the Issue: "Closes #42"
- Fill in the PR template — the Orchestrator will post a draft review.

## 6. Review process

- At least one ⚒️ Mason must approve.
- A 🏛️ Architect of the relevant domain merges.
- The Orchestrator may leave automated comments — these are suggestions, not verdicts.

## 7. Becoming a Mason

After 5 merged PRs, any Mason+ can nominate you. A simple-majority vote in `#voting` (48 h, Masons+) decides. You gain review rights and a voice in all votes.

## Rules to remember

- Never commit `.env` or any file containing secrets.
- Branch names: `feat/NNN-slug`, `fix/NNN-slug`, `docs/slug`, `chore/slug`.
- Keep PRs focused — one issue per PR.
- Be kind. Review the code, not the person.
