#!/usr/bin/env bash
# Tower of Babel — one-shot setup script
# Usage: bash infra/setup.sh
# Run from the repo root.
set -euo pipefail

REQUIRED_PYTHON="3.12"
ENV_FILE=".env"

echo "============================================"
echo "  Tower of Babel — setup"
echo "============================================"

# ── Python version check ─────────────────────────────────────────────────
python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if [[ "$(printf '%s\n' "$REQUIRED_PYTHON" "$python_version" | sort -V | head -n1)" != "$REQUIRED_PYTHON" ]]; then
  echo "❌  Python $REQUIRED_PYTHON+ required (found $python_version)"
  exit 1
fi
echo "✅  Python $python_version"

# ── Virtual environment ───────────────────────────────────────────────────
if [[ ! -d ".venv" ]]; then
  echo "📦  Creating virtual environment…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip setuptools --quiet
echo "📦  Installing dependencies…"
pip install -r requirements.txt --quiet
echo "✅  Dependencies installed"

# ── .env file ────────────────────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
  echo ""
  echo "📝  Creating .env — fill in your tokens below"
  cat > "$ENV_FILE" <<'ENVEOF'
# Discord
DISCORD_TOKEN=           # Bot token from https://discord.com/developers/applications
DISCORD_GUILD_ID=        # Right-click your server → Copy Server ID

# GitHub
GITHUB_TOKEN=            # Fine-grained PAT with Issues + PRs + Contents write
GITHUB_REPO=             # owner/repo  e.g.  skillariatop/Tower_of_Babel

# OpenRouter (free tier is enough)
OPENROUTER_API_KEY=      # https://openrouter.ai/keys
OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free

# Optional
WEBHOOK_PORT=8090
ENVEOF
  echo "⚠️   Edit .env and re-run this script."
  exit 0
fi
echo "✅  .env found"

# ── Discord server channels (one-time) ───────────────────────────────────
echo ""
read -r -p "🛠️  Run one-time Discord server setup? (creates channels/roles) [y/N] " REPLY
if [[ "${REPLY,,}" == "y" ]]; then
  python3 infra/setup_discord.py
fi

# ── GitHub labels ─────────────────────────────────────────────────────────
echo ""
read -r -p "🏷️  Create GitHub labels on the repo? [y/N] " REPLY
if [[ "${REPLY,,}" == "y" ]]; then
  python3 - <<'PYEOF'
import asyncio
from integrations.github import ensure_labels
asyncio.run(ensure_labels())
print("Labels created.")
PYEOF
fi

# ── Smoke test ────────────────────────────────────────────────────────────
echo ""
echo "🧪  Running tests…"
python3 -m pytest tests/ -q

echo ""
echo "============================================"
echo "  All done!  Start the bot with:"
echo "    source .venv/bin/activate"
echo "    python -m bot.main"
echo "  Or with Docker:"
echo "    docker compose -f infra/docker-compose.yml up --build"
echo "============================================"
