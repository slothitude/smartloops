This simplified version feels much stronger. The scope becomes focused around a single idea:

> **Smart Loops is an intelligent wake-up scheduler for Claude Code.**
>
> It watches projects, reads Claude's logs, decides if intervention is needed, calculates the next useful wake-up time, and then goes back to sleep.

# Smart Loops MCP

## Full Project Scope

### Vision

Smart Loops is a lightweight MCP server that acts as a persistent supervisory layer above Claude Code.

It does not replace Claude.

It does not perform coding work.

It does not manage complex workflows.

Its sole purpose is to periodically wake up, understand project state, decide if action is required, determine the next intelligent wake-up time, and then return to sleep.

The design is inspired by the "Ralph Wiggum Loop":

"What happened?"
"What are we doing?"
"Are we stuck?"
"When should I check again?"

---

# Core Philosophy

Claude Code is the worker.

Smart Loops is the watcher.

Claude writes code.

Smart Loops watches progress.

Claude solves problems.

Smart Loops notices when problems are not being solved.

Claude can disappear.

Smart Loops remembers the project.

---

# Primary Goal

Keep projects moving toward completion with minimal supervision.

Avoid:

* Fixed cron schedules
* Constant polling
* Complex orchestration
* Multi-agent management
* Large memory systems

Instead:

Observe

Reason

Schedule

Sleep

---

# Core Loop

The entire system revolves around one loop:

1. Wake up
2. Read project state
3. Read Claude logs
4. Audit progress
5. Decide if action is needed
6. Calculate next wake-up time
7. Sleep

Pseudo-code:

while True:

```
audit_project()

evaluate_progress()

determine_next_action()

determine_next_wakeup()

sleep()
```

---

# Project Registration

Each project contains:

name

path

goal

Example:

Project:
Smart Loops

Goal:
Build a persistent project supervisor MCP

Root:
~/projects/smartloops

---

# Project State Sources

Smart Loops only reads a small set of files.

Priority sources:

todo.md

CLAUDE.md

README.md

project-plan.md

Git history

GitHub issues

Claude activity logs

Nothing else is required.

---

# Claude Activity Logs

This is a major feature.

Every Claude loop is instructed to maintain a running log.

Example:

.smartloops/claude_log.md

Claude writes entries during work.

Example:

## 2026-05-27 10:00

Task:
Implement database layer

Status:
In Progress

Actions:

* Created schema
* Added migrations
* Added tests

Next:
Run integration tests

Confidence:
85%

---

## 2026-05-27 10:45

Task:
Database layer

Status:
Blocked

Issue:
Migration conflict

Attempted:

* Rebuild migration chain
* Reset test database

Next:
Investigate migration ordering

Confidence:
30%

Smart Loops reads these logs.

This is its primary source of understanding.

---

# Ralph Journal

Smart Loops maintains its own journal.

Example:

.smartloops/ralph_journal.md

Entries:

## 2026-05-27 11:00

Observed:
Claude blocked on migrations

Action:
Scheduled early review

Next Wake:
11:15

Reason:
Low confidence

---

## 2026-05-27 11:15

Observed:
Migration issue resolved

Action:
No intervention

Next Wake:
14:00

Reason:
Large feature implementation underway

The journal becomes the long-term project memory.

---

# Smart Wake-Up Engine

The core innovation.

Not cron.

Not polling.

Not fixed intervals.

Instead:

When should new information exist?

Smart Loops estimates:

Expected work duration

Risk level

Complexity

Current confidence

Project health

Then chooses a wake-up time.

Examples:

Simple file edit:

Wake:
10 minutes

Large feature:

Wake:
3 hours

Blocked task:

Wake:
15 minutes

High confidence autonomous work:

Wake:
6 hours

Project inactive:

Wake:
Tomorrow

The system attempts to minimize unnecessary wake-ups.

---

# Wake-Up Scoring

Inputs:

Task complexity

Recent progress

Commit frequency

Claude confidence

Failure history

Current blockers

Output:

Next wake-up timestamp

Reason

Confidence

Stored in:

next_wakeup.json

---

# Claude Interaction

Smart Loops primarily interacts through:

Claude loops

Claude logs

Claude prompts

When action is required:

Smart Loops creates a new instruction.

Example:

Review migration issue.

Focus on dependency ordering.

Update log when complete.

Then Claude continues working.

---

# Project Audit

When awake:

Read:

todo.md

CLAUDE.md

Git commits

GitHub issues

Claude logs

Determine:

Completed work

Blocked work

Next work

Risk level

Estimated completion

Store:

WORLD_MODEL.json

---

# Drift Detection

Question:

Is current work helping complete the project goal?

Example:

Goal:
Weather Dashboard

Current Work:
Plugin Framework

Result:

Drift Detected

Smart Loops alerts Claude and requests refocus.

---

# Stuck Detection

Signals:

Repeated errors

No commits

Repeated log entries

Low confidence

Long-running task

If stuck:

Early wake-up scheduled.

---

# Recovery

Level 1

Ask Claude to retry.

Level 2

Ask Claude to re-plan.

Level 3

Notify human.

Level 4

Pause project.

Recovery remains intentionally simple.

---

# Git Integration

Git provides:

Recent commits

Commit frequency

Project velocity

Checkpoint references

Smart Loops does not manage branches.

Smart Loops only observes.

Optional:

Create checkpoints before major work.

---

# GitHub Integration

Read only.

Monitor:

Issues

Milestones

Pull requests

Completion status

Used to improve audits.

---

# Human Notifications

Telegram integration.

Only used for:

Blocked projects

Repeated failures

Human decisions required

Project completion

Everything else remains autonomous.

---

# Completion Detection

Project is complete when:

No remaining todos

No blockers

Goal achieved

Human approval

Then:

Generate final report

Archive journals

Stop wake-ups

Mark project complete

Sleep forever

---

# MCP Tools

project_register

project_list

project_status

audit_project

read_claude_log

read_ralph_journal

calculate_next_wakeup

detect_stuck

detect_drift

notify_human

generate_status_report

pause_project

resume_project

complete_project

---

# File Structure

smartloops_mcp.py

smartloops/

```
audit.py

wakeup.py

drift.py

stuck.py

journal.py

claude_log.py

notify.py

github.py

git.py

db.py
```

data/

```
smartloops.db
```

Project Files:

.smartloops/

```
claude_log.md

ralph_journal.md

WORLD_MODEL.json

next_wakeup.json
```

---

# Success Criteria

Smart Loops should be able to:

Watch a project for weeks

Understand what Claude is doing

Notice when progress stops

Wake itself only when useful

Keep a concise history

Escalate only when necessary

Know when the project is finished

Without requiring constant human supervision

---

# One-Sentence Description

Smart Loops is a lightweight MCP supervisor that reads Claude Code's work log, periodically audits project progress, intelligently decides when it should next wake up, and keeps checking until the project is finished.

The Claude log is arguably the most important addition. Without it, Smart Loops is guessing from commits and files. With it, Claude effectively leaves breadcrumbs explaining what it was trying to do, what went wrong, how confident it is, and what it plans next. That gives the Ralph loop much better information for deciding whether to sleep for 10 minutes, 3 hours, or wake the human.
