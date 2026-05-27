# Smart Loops

stay out of the other folder and projects

Intelligent wake-up scheduler for Claude Code. Watches registered projects, detects stuck/drift, and calculates when to check next.

## Architecture

```
smartloops_mcp.py     — MCP server entry point (FastMCP)
config.py             — Environment config (Telegram, DB path, thresholds)
smartloops/
  db.py               — SQLite layer (projects, audits, wake_history)
  audit.py            — Project audit engine (todo, git, claude log)
  claude_log.py       — Parse .smartloops/claude_log.md
  journal.py          — Read/write .smartloops/ralph_journal.md
  wakeup.py           — Smart wake-up scoring engine
  stuck.py            — Stuck detection (repeated errors, no commits)
  drift.py            — Drift detection (work vs goal alignment)
  loop.py             — Wake-up loop (run_cycle)
  notify.py           — Telegram notifications
  git.py              — Git velocity metrics
  executor.py          — Spawns Claude Code sessions to work on tasks
```

## Running

```bash
# MCP server
python smartloops_mcp.py

# Wake-up loop (for task scheduler)
python -m smartloops.loop
```

## Database

SQLite at `data/smartloops.db` — auto-created on first use.

## Environment Variables

- `SMARTLOOPS_TELEGRAM_TOKEN` — Telegram bot token (required for notifications)
- `SMARTLOOPS_TELEGRAM_CHAT_ID` — Telegram chat ID (required for notifications)
