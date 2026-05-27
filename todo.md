# Smart Loops MCP — TODO

## Phase 1 — Foundation (MVP)

- [x] Create project structure (`smartloops/` package, `data/` dir, `smartloops_mcp.py` entry point)
- [x] `db.py` — SQLite schema and CRUD for projects table
  - [x] Schema: projects (id, name, path, goal, status, created, last_audit)
  - [x] Schema: audits (id, project_id, timestamp, assessment, confidence, next_wakeup)
  - [x] Schema: wake_history (id, project_id, woke_at, reason, action_taken)
  - [x] Functions: add_project, get_project, list_projects, update_project_status
  - [x] Functions: add_audit, get_latest_audit, add_wake_record
- [x] `smartloops_mcp.py` — MCP server entry point
  - [x] Initialize FastMCP server
  - [x] Register all Phase 1 tools
  - [x] Handle startup/shutdown
- [x] `claude_log.py` — Parse `.smartloops/claude_log.md`
  - [x] Parse log entries (timestamp, task, status, actions, next, confidence)
  - [x] Get latest entry
  - [x] Get entries since a given time
- [x] `journal.py` — Read/write Ralph journal
  - [x] Append journal entry (observed, action, next_wake, reason)
  - [x] Read recent entries
  - [x] Read entries since a given time
- [x] `audit.py` — Basic project audit
  - [x] Read todo.md from project root
  - [x] Read CLAUDE.md from project root
  - [x] Read git log (last 10 commits)
  - [x] Read claude_log.md from `.smartloops/`
  - [x] Produce assessment: completed work, blocked work, next work, risk level, confidence
  - [x] Write WORLD_MODEL.json snapshot
- [x] MCP tools (Phase 1)
  - [x] `project_register(name, path, goal)` — register a new project
  - [x] `project_list()` — list all registered projects
  - [x] `project_status(name)` — current project state and last audit
  - [x] `audit_project(name)` — run a full audit
  - [x] `read_claude_log(name)` — read Claude's work log
  - [x] `read_ralph_journal(name)` — read Ralph's observations
- [x] Initialize `.smartloops/` directory on project registration
- [x] Test with a sample project

## Phase 2 — Smart Wake-Up Engine

- [x] `wakeup.py` — Scoring engine
  - [x] Input: task complexity, recent progress, commit frequency, confidence, failure history, blockers
  - [x] Output: next wake-up timestamp, reason, confidence score
  - [x] Rules: simple edit → 10min, large feature → 3hr, blocked → 15min, high confidence → 6hr, inactive → next day
  - [x] Write `next_wakeup.json`
- [x] `stuck.py` — Stuck detection
  - [x] Detect: repeated errors, no commits in X hours, repeated log entries, low confidence (< 40%), long-running task
  - [x] Output: stuck boolean, signals detected, severity
- [x] `drift.py` — Drift detection
  - [x] Compare current work (from claude_log) against registered project goal
  - [x] Output: drift boolean, current focus, expected focus, suggestion
- [x] Sleep/wake mechanism
  - [x] Windows Task Scheduler integration (create/update scheduled task for next wake)
- [x] MCP tools (Phase 2)
  - [x] `calculate_next_wakeup(name)` — run scoring and schedule
  - [x] `detect_stuck(name)` — check if project is stuck
  - [x] `detect_drift(name)` — check if project has drifted from goal

## Phase 3 — Integrations

- [x] `git.py` — Git history analysis
  - [x] Recent commits (last 10, 50)
  - [x] Commit frequency (commits/day, commits/week)
  - [x] Project velocity trend
  - [x] Files changed analysis
- [x] `github.py` — GitHub API (read-only)
  - [x] List open issues
  - [x] List milestones and completion %
  - [x] List open PRs
  - [x] Wire into audit scoring
- [x] `generate_status_report(name)` — comprehensive status report
  - [x] Project overview, progress summary, risk assessment, timeline estimate
  - [x] Include git/github data
- [x] Wire git + github data into audit and wake-up scoring

## Phase 4 — Notifications & Recovery

- [x] `notify.py` — Telegram bot integration
  - [x] Send message via Telegram Bot API (token: configured)
  - [x] Only for: blocked, repeated failures, human decision needed, project complete
- [ ] Recovery system
  - [ ] Level 1: Instruct Claude to retry (write to claude instruction file)
  - [ ] Level 2: Instruct Claude to re-plan (write to claude instruction file)
  - [ ] Level 3: Notify human via Telegram
  - [ ] Level 4: Pause project, notify human
- [x] MCP tools (Phase 4)
  - [x] `notify_human(name, message)` — send Telegram notification
  - [x] `pause_project(name)` — pause all wake-ups
  - [x] `resume_project(name)` — resume wake-ups
  - [x] `complete_project(name)` — generate final report, archive, stop wake-ups

## Phase 5 — Polish & Testing

- [ ] End-to-end test with a real project
- [ ] Edge cases: corrupt log files, missing `.smartloops/` dir, offline git, no github repo
- [ ] Performance: ensure audits complete in < 5 seconds
- [x] Config file for Telegram token, GitHub token, notification preferences
- [x] MCP config snippet for `.claude/.mcp.json`
- [ ] README.md with setup instructions
- [ ] Install as pip package or standalone script

## Phase 6 — Executor

- [x] `executor.py` — Spawn Claude Code sessions to work on tasks
  - [x] `pick_next_task()` — parse todo.md, return first unchecked item
  - [x] `spawn_claude()` — launch `claude -p` as detached background process
  - [x] `is_claude_running()` — check if spawned process is alive via PID
  - [x] PID tracking in `.smartloops/spawn.json`
- [x] Loop integration — spawn Claude when todos pending and not stuck(high/critical)
- [x] Wakeup fix — use 10min interval for projects with pending todos (not 24h)
- [x] Audit exposes `next_task` in result for executor
- [x] Auto-wake scheduler task (schtasks SmartLoops-Cycle, every 15 min)
