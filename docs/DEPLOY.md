# Deploying Tower of Babel

This guide takes you from a fresh server to a running Tower of Babel instance in about 20 minutes.

## Prerequisites

| What | Where to get it |
|------|----------------|
| Python 3.12+ | [python.org](https://python.org) |
| Git | `apt install git` / `brew install git` |
| A Discord server where you have admin rights | [discord.com](https://discord.com) |
| A GitHub repo | [github.com/new](https://github.com/new) |
| OpenRouter account (free tier works) | [openrouter.ai](https://openrouter.ai) |

---

## Step 1 — Clone the repo

```bash
git clone https://github.com/skillariatop/Tower_of_Babel.git
cd Tower_of_Babel
```

---

## Step 2 — Create a Discord application

1. Go to <https://discord.com/developers/applications> → **New Application**.
2. Under **Bot** tab → **Add Bot** → copy the **Token** (you'll need it for `DISCORD_TOKEN`).
3. Under **Privileged Gateway Intents** enable:
   - **Server Members Intent**
   - **Message Content Intent**
4. Under **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: `Manage Roles`, `Manage Channels`, `Send Messages`, `Read Messages/View Channels`, `Add Reactions`, `Read Message History`
5. Copy the generated URL and open it to invite the bot to your server.
6. **Right-click your server icon → Copy Server ID** (enable Developer Mode in Discord settings first).

---

## Step 3 — Create a GitHub Personal Access Token

1. <https://github.com/settings/tokens> → **Fine-grained tokens** → **Generate new token**.
2. Select your repo, grant **Read and Write** access to: Issues, Pull requests, Contents, Metadata.
3. Copy the token.

---

## Step 4 — Get an OpenRouter API key

1. Sign up at <https://openrouter.ai>.
2. Go to **Keys** → **Create key**.
3. Free-tier models like `nvidia/nemotron-3-super-120b-a12b:free` are enough for full functionality.

---

## Step 5 — Run the setup script

```bash
bash infra/setup.sh
```

The script will:
1. Check Python version
2. Create a `.venv` virtual environment
3. Install all dependencies
4. Generate a `.env` template if it doesn't exist

Open `.env` and fill in your values:

```env
DISCORD_TOKEN=your-bot-token
DISCORD_GUILD_ID=your-server-id
GITHUB_TOKEN=github_pat_...
GITHUB_REPO=owner/repo
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free
WEBHOOK_PORT=8090
```

Re-run the script after filling in `.env`:

```bash
bash infra/setup.sh
```

When prompted, answer **y** to create Discord channels/roles and GitHub labels (one-time only).

---

## Step 6 — Start the bot

### Local / VPS

```bash
source .venv/bin/activate
python -m bot.main
```

You should see:
```
INFO  tower.bot   Logged in as Tower of Babel#1234 (guild: Your Server)
INFO  tower.bot   Synced 12 slash commands
INFO  tower.webhooks  Webhook receiver started on :8090
```

### Docker Compose

```bash
docker compose -f infra/docker-compose.yml up --build -d
docker compose -f infra/docker-compose.yml logs -f
```

---

## Step 7 — Set up GitHub Webhooks (optional)

To receive real-time PR / issue / CI notifications in Discord:

1. In your GitHub repo: **Settings → Webhooks → Add webhook**.
2. **Payload URL**: `http://your-server-ip:8090/github`
3. **Content type**: `application/json`
4. **Events**: Issues, Pull requests, Check runs, Releases.
5. Click **Add webhook**.

> If your bot runs behind NAT, use [ngrok](https://ngrok.com) or a reverse proxy to expose port 8090.

---

## Step 8 — Verify everything works

In your Discord server, type:

```
/admin status
```

The Orchestrator should reply with its current state and connected services.

Try creating a vote:

```
/vote start title:Test vote description:Does this work? level:routine
```

---

## Roles

| Role | Emoji | Description |
|------|-------|-------------|
| Observer | 👁️ | Can read everything, no voting rights |
| Apprentice | 🧱 | Can vote on routine decisions |
| Mason | ⚒️ | Can vote + take tasks, trigger orchestration |
| Architect | 🏛️ | Can open significant decisions, review issues |
| Keeper | 🛡️ | Full admin, veto rights, kill switch |

Assign roles manually in Discord or integrate with your onboarding flow.

---

## Decision levels

| Level | Duration | Quorum |
|-------|----------|--------|
| Routine | 24 h | Simple majority |
| Significant | 48 h | 2/3 |
| Critical | 72 h | 3/4 + at least one Keeper |

---

## Kill switch

If the AI Orchestrator behaves unexpectedly, a Keeper can stop all AI tasks immediately:

```
/admin stop
```

Resume with:

```
/admin resume
```

---

## Troubleshooting

**Bot doesn't respond to slash commands**
: Check that the bot was re-invited with `applications.commands` scope. Slash commands can take up to 1 hour to propagate globally; guild-scoped commands sync instantly.

**`PrivilegedIntentsRequired` error**
: Enable Server Members Intent and Message Content Intent in the Discord Developer Portal under your bot's settings.

**OpenRouter 429 / rate-limit errors**
: Switch to a different free model. Run `python3 -c "import httpx, asyncio; ..."` or check <https://openrouter.ai/models?q=free> for currently available models.

**Port 8090 already in use**
: Set `WEBHOOK_PORT=8091` (or any free port) in `.env`.

**Bot can't push to GitHub**
: Ensure the PAT has write access to Issues and Pull requests. Fine-grained tokens scope to a single repo — make sure you selected the right one.

---

## Updating

```bash
git pull
source .venv/bin/activate
pip install -r requirements.txt
# Restart the bot process
```

---

## Architecture overview

```
Discord ──── discord.py bot (bot/)
               ├── cogs/voting.py    ← community decisions
               ├── cogs/tasks.py     ← GitHub issue assignment
               ├── cogs/orchestrator.py ← AI orchestration commands
               ├── cogs/roles.py     ← role management
               ├── cogs/audit.py     ← audit log
               └── cogs/admin.py     ← Keeper admin + kill switch

GitHub ─────── integrations/
               ├── github.py         ← REST API client
               └── webhooks.py       ← FastAPI :8090

AI ─────────── orchestrator/
               ├── llm.py            ← OpenRouter / Ollama adapter
               ├── decompose.py      ← decision → GitHub Issues
               ├── review.py         ← PR code review
               ├── digest.py         ← weekly summaries
               ├── metrics.py        ← velocity / health stats
               ├── assign.py         ← smart task assignment
               ├── deadlines.py      ← overdue task escalation
               ├── release_notes.py  ← changelog generation
               └── projects.py       ← multi-project registry
```

The bot and the webhook server run in the same Python process via `asyncio.gather`.

---

_For questions, open an issue at [github.com/skillariatop/Tower_of_Babel](https://github.com/skillariatop/Tower_of_Babel)._
