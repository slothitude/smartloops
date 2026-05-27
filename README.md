# Smart Loops

Intelligent wake-up scheduler for Claude Code. Registers projects, runs periodic audits, detects stuck/drift conditions, and spawns Claude workers on pending tasks. Exposed as an MCP server with 20 tools.

## Quick Start

```bash
# 1. Install dependencies
pip install mcp

# 2. Register as MCP server in Claude Code
claude mcp add smartloops -s user -- C:\Python313\python.exe C:\Users\aaron\smartloops\smartloops_mcp.py

# 3. Verify it's loaded
claude mcp list
```

## What It Does

Smart Loops acts as a project manager for Claude Code sessions:

1. **Register projects** you're working on (path + goal)
2. **Audit** reads todo.md, CLAUDE.md, git log, and Claude's work log to assess project health
3. **Detect** when a project is stuck (repeated errors, no commits, low confidence) or drifted from its goal
4. **Wake up** at intelligent intervals (10min for stuck, 6hr for high-confidence, 24hr for inactive)
5. **Spawn** Claude Code workers on pending todo items when healthy
6. **Recover** via 4-level escalation: retry → re-plan → notify human → pause project
7. **Notify** you via Telegram when intervention is needed

## Architecture

```
smartloops_mcp.py          FastMCP entry point (20 tools)
config.py                  Env vars, DB path, thresholds
smartloops/
  db.py                    SQLite (WAL), tables: projects, audits, wake_history
  audit.py                 Reads todo, CLAUDE.md, git log, claude log → WORLD_MODEL.json
  claude_log.py            Parses .smartloops/claude_log.md
  journal.py               Ralph journal (observer persona)
  wakeup.py                Scores project state → next wake-up time
  stuck.py                 6 signals: blocked, low confidence, repeats, no commits, errors, no progress
  drift.py                 Goal vs current work keyword overlap
  loop.py                  run_cycle() for scheduled wake-ups; generate_status_report()
  notify.py                Telegram notifications
  git.py                   Git velocity (commits/day, trend)
  github.py                GitHub issues, PRs, milestones (optional)
  executor.py              Spawns Claude on pending todos
  recovery.py              4-level escalation pipeline
  bot.py                   Telegram question/answer relay
```

### Per-Project State (`.smartloops/` directory)

Each registered project gets a `.smartloops/` directory with:

| File | Purpose |
|------|---------|
| `claude_log.md` | Claude's work entries (task, status, confidence) |
| `ralph_journal.md` | Observer entries (assessment, action, next wake) |
| `WORLD_MODEL.json` | Latest audit snapshot |
| `next_wakeup.json` | Scheduled wake time |
| `spawn.json` | Active worker info (PID, task) |
| `claude_instructions.md` | Recovery instructions for next session |
| `worker.log` | Subprocess output from spawned workers |

## MCP Tools (20)

### Project Management
| Tool | Description |
|------|-------------|
| `project_register` | Register a project with name, path, and goal |
| `project_list` | List all registered projects |
| `project_status` | Detailed status including latest audit |
| `delete_project` | Remove project and all history |

### Audit & Monitoring
| Tool | Description |
|------|-------------|
| `audit_project` | Full audit: todo, CLAUDE.md, git log, claude log |
| `read_claude_log` | Read Claude's work entries |
| `read_ralph_journal` | Read observer journal |
| `detect_stuck` | Check for stuck signals |
| `detect_drift` | Check if work has drifted from goal |
| `status_report` | Comprehensive report (audit + stuck + drift + wakeup) |

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
| `complete_project` | Mark done, write final journal |

### Notifications
| Tool | Description |
|------|-------------|
| `notify_human` | Send Telegram notification |
| `ask_human` | Ask a question via Telegram |
| `check_answer` | Check if question was answered |

### Workers
| Tool | Description |
|------|-------------|
| `worker_status` | Check spawned Claude worker (PID, task, output) |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SMARTLOOPS_TELEGRAM_TOKEN` | No* | Telegram bot token for notifications |
| `SMARTLOOPS_TELEGRAM_CHAT_ID` | No* | Telegram chat ID for notifications |
| `SMARTLOOPS_GITHUB_TOKEN` | No | GitHub API token (issues/PRs, optional) |

*Required only for Telegram notifications and the `ask_human`/`notify_human` tools.

## Wake-Up Intervals

| Condition | Interval |
|-----------|----------|
| Blocked / stuck / failed | 15 min |
| Very low confidence (<30%) | 10 min |
| Low confidence (<50%) | 30 min |
| High confidence + active | 6 hours |
| Large feature in progress | 3 hours |
| No activity, no todos | 24 hours |
| No activity, has todos | 10 min (triggers spawn) |

## Auto-Wake Setup

To run periodic wake-up cycles automatically:

**Windows Task Scheduler:**
```bash
schtasks /create /tn SmartLoops-Cycle /tr "C:\Python313\python.exe -m smartloops.loop" /sc minute /mo 10
```

**Or manually:**
```bash
python -m smartloops.loop
```

The loop checks all active projects with past-due `next_wakeup` timestamps, runs audit/stuck/drift, and spawns workers if needed.

## Database

SQLite at `data/smartloops.db`, auto-created on first use. WAL mode for concurrent reads. Three tables: `projects`, `audits`, `wake_history`.

## Usage Examples

```
# Register a project
> project_register(name="my-app", path="C:/Users/me/my-app", goal="Build REST API")

# Check status
> project_status(name="my-app")

# Run a full audit
> audit_project(name="my-app")

# Get comprehensive report
> status_report(name="my-app")

# Run a wake-up cycle (checks all projects)
> run_cycle()
```
