# Smart Loops MCP — TODO

## Phase 1 — Foundation (MVP)

- [ ] Create project structure (`smartloops/` package, `data/` dir, `smartloops_mcp.py` entry point)
- [ ] `db.py` — SQLite schema and CRUD for projects table
  - [ ] Schema: projects (id, name, path, goal, status, created, last_audit)
  - [ ] Schema: audits (id, project_id, timestamp, assessment, confidence, next_wakeup)
  - [ ] Schema: wake_history (id, project_id, woke_at, reason, action_taken)
  - [ ] Functions: add_project, get_project, list_projects, update_project_status
  - [ ] Functions: add_audit, get_latest_audit, add_wake_record
- [ ] `smartloops_mcp.py` — MCP server entry point
  - [ ] Initialize FastMCP server
  - [ ] Register all Phase 1 tools
  - [ ] Handle startup/shutdown
- [ ] `claude_log.py` — Parse `.smartloops/claude_log.md`
  - [ ] Parse log entries (timestamp, task, status, actions, next, confidence)
  - [ ] Get latest entry
  - [ ] Get entries since a given time
- [ ] `journal.py` — Read/write Ralph journal
  - [ ] Append journal entry (observed, action, next_wake, reason)
  - [ ] Read recent entries
  - [ ] Read entries since a given time
- [ ] `audit.py` — Basic project audit
  - [ ] Read todo.md from project root
  - [ ] Read CLAUDE.md from project root
  - [ ] Read git log (last 10 commits)
  - [ ] Read claude_log.md from `.smartloops/`
  - [ ] Produce assessment: completed work, blocked work, next work, risk level, confidence
  - [ ] Write WORLD_MODEL.json snapshot
- [ ] MCP tools (Phase 1)
  - [ ] `project_register(name, path, goal)` — register a new project
  - [ ] `project_list()` — list all registered projects
  - [ ] `project_status(name)` — current project state and last audit
  - [ ] `audit_project(name)` — run a full audit
  - [ ] `read_claude_log(name)` — read Claude's work log
  - [ ] `read_ralph_journal(name)` — read Ralph's observations
- [ ] Initialize `.smartloops/` directory on project registration
- [ ] Test with a sample project

## Phase 2 — Smart Wake-Up Engine

- [ ] `wakeup.py` — Scoring engine
  - [ ] Input: task complexity, recent progress, commit frequency, confidence, failure history, blockers
  - [ ] Output: next wake-up timestamp, reason, confidence score
  - [ ] Rules: simple edit → 10min, large feature → 3hr, blocked → 15min, high confidence → 6hr, inactive → next day
  - [ ] Write `next_wakeup.json`
- [ ] `stuck.py` — Stuck detection
  - [ ] Detect: repeated errors, no commits in X hours, repeated log entries, low confidence (< 40%), long-running task
  - [ ] Output: stuck boolean, signals detected, severity
- [ ] `drift.py` — Drift detection
  - [ ] Compare current work (from claude_log) against registered project goal
  - [ ] Output: drift boolean, current focus, expected focus, suggestion
- [ ] Sleep/wake mechanism
  - [ ] Windows Task Scheduler integration (create/update scheduled task for next wake)
  - [ ] Or: simple `time.sleep()` loop as background process
- [ ] MCP tools (Phase 2)
  - [ ] `calculate_next_wakeup(name)` — run scoring and schedule
  - [ ] `detect_stuck(name)` — check if project is stuck
  - [ ] `detect_drift(name)` — check if project has drifted from goal

## Phase 3 — Integrations

- [ ] `git.py` — Git history analysis
  - [ ] Recent commits (last 10, 50)
  - [ ] Commit frequency (commits/day, commits/week)
  - [ ] Project velocity trend
  - [ ] Files changed analysis
- [ ] `github.py` — GitHub API (read-only)
  - [ ] List open issues
  - [ ] List milestones and completion %
  - [ ] List open PRs
  - [ ] Wire into audit scoring
- [ ] `generate_status_report(name)` — comprehensive status report
  - [ ] Project overview, progress summary, risk assessment, timeline estimate
  - [ ] Include git/github data
- [ ] Wire git + github data into audit and wake-up scoring

## Phase 4 — Notifications & Recovery

- [ ] `notify.py` — Telegram bot integration
  - [ ] Send message via Telegram Bot API (token: configured)
  - [ ] Only for: blocked, repeated failures, human decision needed, project complete
- [ ] Recovery system
  - [ ] Level 1: Instruct Claude to retry (write to claude instruction file)
  - [ ] Level 2: Instruct Claude to re-plan (write to claude instruction file)
  - [ ] Level 3: Notify human via Telegram
  - [ ] Level 4: Pause project, notify human
- [ ] MCP tools (Phase 4)
  - [ ] `notify_human(name, message)` — send Telegram notification
  - [ ] `pause_project(name)` — pause all wake-ups
  - [ ] `resume_project(name)` — resume wake-ups
  - [ ] `complete_project(name)` — generate final report, archive, stop wake-ups

## Phase 5 — Polish & Testing

- [ ] End-to-end test with a real project
- [ ] Edge cases: corrupt log files, missing `.smartloops/` dir, offline git, no github repo
- [ ] Performance: ensure audits complete in < 5 seconds
- [ ] Config file for Telegram token, GitHub token, notification preferences
- [ ] MCP config snippet for `.claude/.mcp.json`
- [ ] README.md with setup instructions
- [ ] Install as pip package or standalone script
