# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Intelligent wake-up scheduler for Claude Code. Registers projects, runs periodic audits (todo, git, Claude logs), detects stuck/drift, and spawns Claude workers on pending tasks. Exposed as an MCP server with 14 tools.

**Scope**: Only work within this repo. Stay out of other folders and projects.

## Running

```bash
# MCP server (used by Claude Code via stdio)
python smartloops_mcp.py

# Standalone wake-up loop (for Task Scheduler)
python -m smartloops.loop
```

## Architecture

```
smartloops_mcp.py          — FastMCP entry point, all 14 tool definitions
config.py                  — Env vars, DB path, threshold constants
smartloops/
  db.py                    — SQLite (WAL mode), tables: projects, audits, wake_history
  audit.py                 — Reads todo.md, CLAUDE.md, git log, claude_log → writes WORLD_MODEL.json
  claude_log.py            — Parses .smartloops/claude_log.md
  journal.py               — Reads/writes .smartloops/ralph_journal.md (Ralph = observer persona)
  wakeup.py                — Scores project state → calculates next wake-up time (10min–24h range)
  stuck.py                 — 6 signals: blocked status, low confidence, repeated tasks/errors, no commits, no progress
  drift.py                 — Keyword overlap between goal and recent Claude log tasks
  loop.py                  — run_cycle() iterates active projects; generate_status_report() composes full report
  notify.py                — Telegram notifications (needs env vars)
  git.py                   — Git velocity (commits/day, commits/week, trend)
  github.py                — GitHub API: issues, PRs, milestones (gh CLI → REST API fallback)
  executor.py              — Spawns Claude on pending todos (subprocess or subagent mode)
  recovery.py              — 4-level escalation: retry → re-plan → notify human → pause project
```

### Data Flow

1. **Loop wakes** a project when `next_wakeup` timestamp has passed
2. Runs **audit** (reads project files) → **stuck** (pattern detection) → **drift** (goal alignment)
3. If stuck: **recovery** escalation (level 1–4 based on severity)
4. If healthy with pending todos: **executor** spawns Claude on next task
5. **wakeup** calculates next check time based on confidence/risk/velocity
6. Everything logged to **Ralph journal** and **wake_history** DB table

### Per-project State (`.smartloops/` directory in each registered project)

- `claude_log.md` — Claude's work entries (timestamp, task, status, confidence, next, issue)
- `ralph_journal.md` — Observer entries (observed, action, next_wake, reason)
- `WORLD_MODEL.json` — Latest audit snapshot
- `next_wakeup.json` — Scheduled wake time
- `spawn.json` — Active worker info (PID, task, status)
- `claude_instructions.md` — Recovery instructions for next Claude session
- `worker.log` — Subprocess output when executor spawns Claude

### Wake-up Intervals (config.py)

| Condition | Interval |
|-----------|----------|
| Blocked/stuck/failed | 15 min |
| Very low confidence (<30%) | 10 min |
| Low confidence (<50%) | 30 min |
| High confidence + active | 6 hours |
| Large feature in progress | 3 hours |
| No activity, no todos | 24 hours |
| No activity, has todos | 10 min (triggers spawn) |

## Database

SQLite at `data/smartloops.db`, auto-created on first import. WAL mode. Three tables: `projects`, `audits`, `wake_history`.

## Environment Variables

- `SMARTLOOPS_TELEGRAM_TOKEN` — Telegram bot token (notifications)
- `SMARTLOOPS_TELEGRAM_CHAT_ID` — Telegram chat ID (notifications)
- `SMARTLOOPS_GITHUB_TOKEN` — GitHub API token (issues/PRs/milestones, optional)

## Key Patterns

- All subprocess calls use `subprocess.run(capture_output=True, stdin=subprocess.DEVNULL, timeout=10)` to avoid stdio deadlock on MCP transport
- MCP tools use **lazy imports** for heavy modules (only `db` imported at top level)
- `_get_next_task()` reads first `- [ ]` from project's `todo.md`
- Git operations use `-C <path>` to target the project directory
- Windows subprocess spawning uses `CREATE_NO_WINDOW` (0x08000000) flag

## Auto-wake Setup

```bash
schtasks /create /tn SmartLoops-Cycle /tr "C:\Python313\python.exe -m smartloops.loop" /sc minute /mo 15
```
