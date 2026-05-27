# Smart Loops MCP — Implementation Plan

## What It Is

A lightweight MCP server that acts as a persistent supervisory layer above Claude Code. It wakes up, reads project state, decides if action is needed, schedules its next wake-up, and goes back to sleep.

## Core Loop

```
Wake → Read State → Audit → Decide → Schedule Next Wake → Sleep
```

That's it. No orchestration, no agents, no complex workflows.

---

## Architecture

### Single MCP Server (`smartloops_mcp.py`)

Entry point. Registers 14 MCP tools. Manages the main event loop and sleep/wake cycle.

### Module Breakdown (`smartloops/`)

| Module | Responsibility |
|--------|---------------|
| `db.py` | SQLite database — projects, audits, wake history, state |
| `audit.py` | Read project files (todo.md, CLAUDE.md, git log, issues) and produce a progress assessment |
| `claude_log.py` | Parse `.smartloops/claude_log.md` entries |
| `journal.py` | Read/write Ralph journal entries |
| `wakeup.py` | Smart wake-up scoring engine — the core innovation |
| `drift.py` | Detect if current work aligns with project goal |
| `stuck.py` | Detect stalled progress from repeated errors, no commits, low confidence |
| `notify.py` | Telegram notifications for escalations (Level 3+) |
| `git.py` | Read-only git history (commits, frequency, velocity) |
| `github.py` | Read-only GitHub API (issues, milestones, PRs) |

### Data Layer

- **`data/smartloops.db`** — SQLite database for projects, audits, wake history
- **`.smartloops/`** per-project directory with:
  - `claude_log.md` — Claude's work log (Claude writes, Smart Loops reads)
  - `ralph_journal.md` — Smart Loops' own observations
  - `WORLD_MODEL.json` — current project state snapshot
  - `next_wakeup.json` — scheduled wake-up + reasoning

---

## Implementation Phases

### Phase 1 — Foundation (MVP)

Get the skeleton running with database, project registration, and basic audit.

**Scope:**
- `db.py` — schema, CRUD for projects
- `smartloops_mcp.py` — MCP server entry point with tool registration
- `audit.py` — read todo.md, CLAUDE.md, git log, produce basic assessment
- `claude_log.py` — parse claude_log.md entries
- `journal.py` — read/write ralph_journal.md
- MCP tools: `project_register`, `project_list`, `project_status`, `audit_project`, `read_claude_log`, `read_ralph_journal`

**Deliverable:** Can register a project, run a manual audit, read Claude logs, and write journal entries.

### Phase 2 — Smart Wake-Up Engine

The core innovation — intelligent scheduling.

**Scope:**
- `wakeup.py` — scoring engine based on task complexity, confidence, progress, risk
- `stuck.py` — detect stalled work from log patterns, commit gaps, low confidence
- `drift.py` — compare current work vs registered project goal
- MCP tools: `calculate_next_wakeup`, `detect_stuck`, `detect_drift`
- Sleep/wake mechanism using OS scheduler or simple timer loop

**Deliverable:** System wakes itself at calculated times, detects stuck/drift conditions.

### Phase 3 — Integrations

Connect to external sources for richer audits.

**Scope:**
- `git.py` — commit history, frequency analysis, velocity metrics
- `github.py` — issues, milestones, PRs (read-only)
- MCP tools: `generate_status_report`
- Wire git/github data into audit scoring

**Deliverable:** Audits use git history and GitHub data for better progress assessment.

### Phase 4 — Notifications & Recovery

Human-in-the-loop when needed.

**Scope:**
- `notify.py` — Telegram integration
- Recovery levels (retry → re-plan → notify human → pause)
- MCP tools: `notify_human`, `pause_project`, `resume_project`, `complete_project`

**Deliverable:** System escalates to humans via Telegram, handles project lifecycle.

### Phase 5 — Polish & Testing

**Scope:**
- End-to-end testing with real projects
- Edge case handling (corrupt logs, missing files, offline git)
- Performance tuning (keep it lightweight)
- Documentation
- MCP config for `.claude/.mcp.json`

**Deliverable:** Production-ready MCP server.

---

## Key Design Decisions

1. **SQLite, not JSON** — projects need queryable history, not flat files
2. **Read-only git/github** — Smart Loops observes, never modifies repos
3. **Claude writes logs, Ralph reads them** — clean separation of concerns
4. **No LLM inside Smart Loops** — scoring is rule-based, not AI-powered (keep it lightweight)
5. **One `.smartloops/` dir per project** — project state lives with the project
6. **Wake-up = OS-level** — use task scheduler (Windows) or cron (Linux), not an always-on daemon

## Success Criteria

- Can watch a project for weeks without human intervention
- Understands what Claude is doing from logs
- Notices when progress stops
- Wakes itself only when useful
- Escalates only when necessary
- Knows when the project is finished
