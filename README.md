# Smart Loops

**Autonomous project manager for Claude Code.**

Register your projects. Smart Loops audits them, detects when they're stuck or drifting, spawns Claude workers on pending tasks, and escalates to you via Telegram when it needs a human decision. It runs on a loop — you don't have to.

```
You: "Build a REST API for my-app"
Smart Loops: registers the project, audits the codebase, finds the first todo,
             spawns a Claude worker, monitors its progress...

Worker: "Which ORM should I use?"
Smart Loops: relays the question to your Telegram, you tap "Prisma"
Smart Loops: kills the old worker, re-spawns with your answer injected

You: (didn't touch the keyboard once)
```

## How It Works

Smart Loops operates on a wake-up loop. Every cycle:

```
                        ┌─────────────┐
                        │  Wake Cycle  │
                        └──────┬──────┘
                               │
                    ┌──────────▼──────────┐
                    │  Check: is it time?  │
                    │  (next_wakeup DB)    │
                    └──────────┬──────────┘
                               │ Yes
                    ┌──────────▼──────────┐
                    │     Run Audit       │
                    │  todo.md, CLAUDE.md │
                    │  git log, claude_log│
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
     ┌────────▼───────┐ ┌─────▼──────┐ ┌───────▼───────┐
     │  Stuck?        │ │  Drifted?  │ │  Healthy?     │
     │  (6 signals)   │ │  (overlap) │ │               │
     └────────┬───────┘ └─────┬──────┘ └───────┬───────┘
              │               │                 │
     ┌────────▼───────┐       │        ┌────────▼────────┐
     │ 4-Level        │       │        │ Has pending     │
     │ Recovery       │       │        │ todos?          │
     │ ┌────────────┐ │       │        └──┬──────────┬───┘
     │ │ L1: Retry  │ │       │           │          │ No
     │ │ L2: Replan │ │  ┌────▼─────┐    │ Yes      │
     │ │ L3: Notify │ │  │ Telegram │    │     ┌────▼────────┐
     │ │ L4: Pause  │ │  │ question │    │     │ plan.md     │
     │ └────────────┘ │  └──────────┘    │     │ exists?     │
     └────────────────┘                  │     └─┬───────┬───┘
                                         │       │Yes    │No
                              ┌──────────▼──┐    │  ┌────▼─────────┐
                              │ Spawn Claude│    │  │ Interactive  │
                              │ Worker on   │    │  │ Web Terminal │
                              │ next todo   │    │  │ (xterm.js)   │
                              └──────┬──────┘    │  └──────┬───────┘
                                     │     ┌─────▼──────┐  │
                                     │     │ Spawn      │  │ Telegram
                                     │     │ Planner    │  │ notification
                                     │     │ Worker     │  │ with URL
                                     │     └────────────┘  │
                              ┌──────▼──────┐         ┌────▼────────┐
                              │ Worker runs │         │ You join    │
                              │ autonomously│         │ from phone  │
                              └──────┬──────┘         │ via Tailscale│
                                     │                └─────────────┘
                          ┌──────────▼──────────┐
                          │  Worker blocked?    │
                          │  Writes question    │
                          │  to worker_question │
                          │  .json              │
                          └──────────┬──────────┘
                                     │
                          ┌──────────▼──────────┐
                          │  Next cycle: relay  │
                          │  to Telegram.       │
                          │  Your answer re-    │
                          │  spawns the worker. │
                          └─────────────────────┘
```

### The Wake-Up Loop

Each registered project has a `next_wakeup` timestamp in the database. The loop (run via Task Scheduler or manually) checks all active projects — only those past their wake time get processed. After each cycle, a new wake time is calculated based on project health:

| Condition | Interval |
|-----------|----------|
| Blocked / stuck / failed | 15 min |
| Very low confidence (<30%) | 10 min |
| Low confidence (<50%) | 30 min |
| High confidence + active | 6 hours |
| Large feature in progress | 3 hours |
| No activity, all todos done | 24 hours |
| No activity, has todos | 10 min (triggers spawn) |
| No activity, no todo.md | 10 min (triggers planner/interactive) |

### The Audit

`audit_project()` reads four sources and merges them into a `WORLD_MODEL.json`:

1. **todo.md** — counts completed/remaining, extracts next unchecked task
2. **CLAUDE.md** — reads project-level instructions
3. **git log** — measures velocity (commits/day, trend, last commit age)
4. **claude_log.md** — latest worker entry (task, status, confidence, issues)

This produces a confidence score (0–100%), risk level (low/medium/high/critical), and an assessment paragraph.

### Stuck Detection

Six independent signals, each with severity low/medium/high/critical:

| Signal | What it checks |
|--------|---------------|
| Blocked status | Last log entry says "blocked" |
| Low confidence | Confidence < 40% |
| Repeated tasks | Same task appears 3+ times in log |
| Repeated errors | Same error appears 3+ times |
| No commits | No git commits in 4+ hours |
| No progress | Confidence unchanged across 5+ entries |

Multiple signals compound — severity escalates.

### Drift Detection

Compares the project's registered goal against Claude's recent work. Extracts keywords from both, measures overlap. Below 20% overlap = drifted. Suggests realignment.

### The Recovery Pipeline

When stuck is detected, severity determines the response:

```
Low      → Log it, keep monitoring
Medium   → Write recovery instructions + spawn worker (spawning IS the fix)
High     → Instruct re-plan + notify human via Telegram
Critical → Pause project + alert human (requires manual resume)
```

High and critical also send an interactive Telegram question with inline buttons: `re-plan`, `pause`, `ignore`.

### Worker Spawning

`executor.spawn_claude()` launches `claude -p "..." --output-format json` as a detached background process. The worker:

1. Reads the task from the prompt
2. Works on it autonomously
3. Checks off the todo item when done
4. Writes an entry to `claude_log.md`
5. Commits changes

Workers run with `stdin=DEVNULL` — they can't use `AskUserQuestion`. Instead, they use the **worker question relay**.

### Auto-Todo: Self-Bootstrapping Workers

When a project has no pending todos, Smart Loops doesn't just wait 24 hours — it bootstraps:

**Branch 1 — Planner Worker** (has `plan.md` but no todos):
Spawns a Claude worker that reads `plan.md`, breaks it into actionable checkbox items, and writes `todo.md`. The next cycle picks up the new todos and spawns workers normally.

**Branch 2 — Interactive Web Terminal** (no `plan.md`):
Starts a web terminal (xterm.js + WebSocket → PTY) so you can brainstorm a plan with Claude interactively. The URL is sent to your Telegram — open it on your phone via Tailscale and chat with Claude to define the project scope.

```
Project has no todos
  → Has plan.md?
     Yes → spawn_planner() → reads plan, creates todo.md
     No  → spawn_interactive() → web terminal → Telegram URL

Next cycle finds todos → spawns workers as usual
```

### Web Terminal

`webterm.py` is a single-file Flask server (~180 lines) that bridges a browser terminal to a Claude Code PTY session:

- **Frontend**: xterm.js with fit addon, dark theme, mobile-optimized viewport
- **Backend**: Flask + flask-sock, spawns `winpty.PTY` running `claude`
- **Protocol**: JSON over WebSocket (`{type: "input"|"output"|"resize"|"exit", payload: base64}`)
- **Access**: `http://<tailscale-ip>:8737/` from any device on your network
- **Auto-cleanup**: when the PTY exits, sends exit message and shuts down after 3 seconds

```bash
# Start manually
python webterm.py --project-path /path/to/project --port 8737

# Or via Telegram bot
/plan my-project
```

### PTY MCP — Infrastructure Workers

Workers can optionally get terminal access via `@so2liu/pty-mcp-server`. When enabled, spawned workers can SSH into machines, run Docker commands, and manage services — fully autonomously.

**How it works:**

1. `data/worker_mcp.json` defines the PTY MCP server config
2. `spawn_claude()` detects the file and adds `--mcp-config` + `--strict-mcp-config` flags
3. `--strict-mcp-config` isolates the worker — it only sees the PTY server, not your full `.mcp.json`
4. The worker prompt gets an infrastructure section with machine IPs and safety rules

**Enablement modes** (`SMARTLOOPS_PTY_ENABLED` env var):

| Mode | Behavior |
|------|----------|
| `auto` (default) | Enabled if `data/worker_mcp.json` exists |
| `true` | Force enable, warns if config missing |
| `false` | Disabled entirely, even if file exists |

**Graceful degradation** — if the file doesn't exist or is invalid JSON, workers spawn normally without MCP tools. Zero behavior change.

**Safety layers:**

| Layer | What it blocks |
|-------|---------------|
| `--strict-mcp-config` | Workers isolated from user's MCP servers |
| Prompt safety rules | `rm -rf`, `shutdown`, `dd`, firewall changes blocked |
| `worker_question.json` relay | Gates destructive ops for human approval |
| `kill_worker()` | Loop or `/worker` can kill at any time |
| `worker.log` + `claude_log.md` | Full audit trail, `Infra:` prefix for PTY ops |

**Setup:**

```bash
# Copy example config to data/ (created automatically on first use)
cp worker_mcp.json.example data/worker_mcp.json

# To disable: set SMARTLOOPS_PTY_ENABLED=false
# To customize: edit data/worker_mcp.json
```

### Worker Question Relay

This is the key feature for non-interactive autonomy:

```
Worker hits a blocker that needs a human decision
  → Writes .smartloops/worker_question.json:
    {"question": "Which DB?", "choices": ["Postgres", "SQLite"], ...}
  → Stops (sets status: waiting_for_answer)

Next loop cycle detects the question file
  → Sends it to Telegram (inline buttons if choices, force_reply if open-ended)
  → Clears the file

You answer on Telegram (tap a button, or type a reply)

Next loop cycle picks up the answer
  → Kills the old worker if still running
  → Writes .smartloops/worker_answer.json with your response
  → Re-spawns Claude with your answer injected into the prompt

New worker reads the answer and continues
```

## Quick Start

```bash
# 1. Install dependencies
pip install mcp pywinpty Flask flask-sock

# 2. Register as MCP server in Claude Code
claude mcp add smartloops -s user -- C:\Python313\python.exe C:\Users\aaron\smartloops\smartloops_mcp.py

# 3. Verify it's loaded
claude mcp list
```

Then in any Claude Code session:

```
> project_register(name="my-app", path="C:/Users/me/my-app", goal="Build REST API")
> run_cycle()
```

## Setup

### Environment Variables

Set as Windows user environment variables (or in your shell profile):

| Variable | Required | Description |
|----------|----------|-------------|
| `SMARTLOOPS_TELEGRAM_TOKEN` | No* | Telegram bot token |
| `SMARTLOOPS_TELEGRAM_CHAT_ID` | No* | Your Telegram chat ID |
| `SMARTLOOPS_GITHUB_TOKEN` | No | GitHub PAT for issues/PRs |

\* Without Telegram, the system still works — you just lose remote notifications and the worker question relay. Everything falls back gracefully.

### Auto-Wake (Windows Task Scheduler)

```bash
schtasks /create /tn SmartLoops-Cycle /tr "C:\Python313\python.exe -m smartloops.loop" /sc minute /mo 10
```

This runs the wake-up loop every 10 minutes. Each cycle only processes projects past their `next_wakeup` time, so most cycles are no-ops.

### Telegram Bot Setup

1. Message [@BotFather](https://t.me/BotFather) on Telegram, create a new bot
2. Get your chat ID by messaging your bot, then visiting `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Set the env vars and restart your shell

The bot supports commands: `/list`, `/status`, `/audit`, `/stuck`, `/drift`, `/pause`, `/resume`, `/cycle`, `/worker`, `/plan`, `/log`, `/questions`.

## Architecture

```
smartloops_mcp.py          FastMCP entry point (20 tools)
config.py                  Env vars, DB path, thresholds, worker MCP config
webterm.py                 Web terminal: Flask + xterm.js ↔ winpty PTY bridge
smartloops/
  db.py                    SQLite (WAL), tables: projects, audits, wake_history
  audit.py                 Reads todo, CLAUDE.md, git log, claude log → WORLD_MODEL.json
  claude_log.py            Parses .smartloops/claude_log.md
  journal.py               Ralph journal (observer persona)
  wakeup.py                Scores project state → next wake-up time (10min–24h range)
  stuck.py                 6 signals: blocked, low confidence, repeats, no commits, errors, no progress
  drift.py                 Goal vs current work keyword overlap
  loop.py                  run_cycle() for scheduled wake-ups; generate_status_report()
  notify.py                Telegram notifications
  git.py                   Git velocity (commits/day, trend)
  github.py                GitHub issues, PRs, milestones (optional)
  executor.py              Spawns Claude workers + planner + interactive web terminal
  recovery.py              4-level escalation pipeline
  bot.py                   Telegram polling, command dispatch, interactive questions
```

### Per-Project State (`.smartloops/` directory)

| File | Purpose |
|------|---------|
| `claude_log.md` | Worker entries: timestamp, task, status, confidence, next, issue |
| `ralph_journal.md` | Observer entries: assessment, action taken, next wake reason |
| `WORLD_MODEL.json` | Latest audit snapshot (confidence, risk, git velocity, etc.) |
| `next_wakeup.json` | Calculated wake time and reason |
| `spawn.json` | Active worker: PID, task, started, status, mcp_enabled |
| `worker_question.json` | Worker's question when blocked (consumed by loop) |
| `worker_answer.json` | Human's answer (written by loop before re-spawn) |
| `claude_instructions.md` | Recovery instructions for next worker session |
| `worker.log` | Subprocess stdout/stderr from spawned workers |

### Database

SQLite at `data/smartloops.db`, auto-created on first use. WAL mode for concurrent reads. Three tables:

- **projects** — name, path, goal, status, next_wakeup
- **audits** — confidence, risk_level, assessment, world_model JSON
- **wake_history** — timestamp, reason, action_taken, next_wakeup

## MCP Tools (20)

### Project Management
| Tool | Description |
|------|-------------|
| `project_register` | Register a project with name, path, and goal |
| `project_list` | List all registered projects with status |
| `project_status` | Detailed status including latest audit |
| `delete_project` | Remove project and all history |

### Audit & Monitoring
| Tool | Description |
|------|-------------|
| `audit_project` | Full audit: todo, CLAUDE.md, git log, claude log |
| `read_claude_log` | Read worker entries |
| `read_ralph_journal` | Read observer journal |
| `detect_stuck` | Check for stuck signals |
| `detect_drift` | Check goal alignment |
| `status_report` | Comprehensive report (audit + stuck + drift + wakeup) |
| `worker_status` | Check spawned worker (PID, task, output log) |

### Scheduling
| Tool | Description |
|------|-------------|
| `calculate_next_wakeup` | Score project state, calculate next wake time |
| `run_cycle` | Run one wake-up cycle for all active projects |

### Lifecycle
| Tool | Description |
|------|-------------|
| `pause_project` | Stop wake-ups temporarily |
| `resume_project` | Resume paused project |
| `complete_project` | Mark done, write final journal entry |

### Notifications & Interaction
| Tool | Description |
|------|-------------|
| `notify_human` | Send Telegram notification |
| `ask_human` | Ask a question via Telegram (inline buttons or free text) |
| `check_answer` | Check if a question has been answered |
| `spawn_interactive` | Start web terminal for interactive brainstorming |

## Usage Examples

```
# Register a project
> project_register(name="my-app", path="C:/Users/me/my-app", goal="Build REST API")

# Check health
> status_report(name="my-app")

# Run a full audit
> audit_project(name="my-app")

# Run a wake-up cycle (checks all projects)
> run_cycle()

# Ask yourself a question via Telegram
> ask_human(question="Should I use SQLite or Postgres?", choices="SQLite,Postgres", project="my-app")

# Check the answer
> check_answer(question_id=1779925544)
```

## Design Principles

- **Zero dependencies beyond `mcp`** — core system uses Python stdlib (sqlite3, urllib, subprocess). Web terminal requires `pywinpty`, `Flask`, `flask-sock` (optional — only needed for interactive planning).
- **Graceful degradation** — no Telegram? System works, just no remote alerts. No GitHub token? Skip GitHub data. Disk full? Don't lose the cycle result.
- **One bad project can't sink the cycle** — every project is wrapped in try/except, failures are isolated
- **Workers are fire-and-forget** — spawned with `stdin=DEVNULL`, output to `worker.log`, PID tracked in `spawn.json`
- **Questions flow one way** — worker writes file, loop relays to Telegram, answer comes back via next cycle, new worker picks it up. No webhooks, no threads, no complexity.
- **SQLite WAL mode** — concurrent reads from MCP tools while the loop writes, no locking issues
