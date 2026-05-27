"""Smart Loops — Parse Claude's work log (.smartloops/claude_log.md)."""

import os
import re
from datetime import datetime

from config import SMARTLOOPS_DIR, CLAUDE_LOG_FILE


def _log_path(project_path: str) -> str:
    return os.path.join(project_path, SMARTLOOPS_DIR, CLAUDE_LOG_FILE)


def log_exists(project_path: str) -> bool:
    return os.path.isfile(_log_path(project_path))


def parse_entries(project_path: str) -> list[dict]:
    """Parse all entries from claude_log.md.

    Returns list of dicts with keys: timestamp, task, status, actions, next, confidence
    """
    path = _log_path(project_path)
    if not os.path.isfile(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    return _parse_content(content)


def _parse_content(content: str) -> list[dict]:
    entries = []
    # Split on ## YYYY-MM-DD HH:MM headers
    raw_entries = re.split(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2})", content, flags=re.MULTILINE)

    # raw_entries: [preamble, timestamp1, body1, timestamp2, body2, ...]
    for i in range(1, len(raw_entries), 2):
        timestamp_str = raw_entries[i]
        body = raw_entries[i + 1] if i + 1 < len(raw_entries) else ""

        entry = {
            "timestamp": timestamp_str,
            "task": _extract_field(body, "task"),
            "status": _extract_field(body, "status"),
            "actions": _extract_list(body, "actions"),
            "next": _extract_field(body, "next"),
            "confidence": _extract_confidence(body),
            "issue": _extract_field(body, "issue"),
            "attempted": _extract_list(body, "attempted"),
        }
        entries.append(entry)

    return entries


def _extract_field(body: str, field_name: str) -> str:
    """Extract a 'Field:' value from markdown body."""
    pattern = rf"(?i)^{field_name}:\s*(.+)$"
    for line in body.strip().splitlines():
        m = re.match(pattern, line.strip())
        if m:
            return m.group(1).strip()
    return ""


def _extract_list(body: str, field_name: str) -> list[str]:
    """Extract a bullet list under a 'Field:' header."""
    lines = body.strip().splitlines()
    items = []
    collecting = False
    for line in lines:
        stripped = line.strip()
        if re.match(rf"(?i)^{field_name}:\s*$", stripped):
            collecting = True
            continue
        if collecting:
            if stripped.startswith("* ") or stripped.startswith("- "):
                items.append(stripped[2:].strip())
            elif stripped == "":
                continue
            else:
                collecting = False
    return items


def _extract_confidence(body: str) -> int:
    """Extract confidence percentage."""
    val = _extract_field(body, "confidence")
    if val:
        # Handle "85%" or "85"
        return int(re.sub(r"[^\d]", "", val))
    return 50


def get_latest_entry(project_path: str) -> dict | None:
    """Get the most recent log entry."""
    entries = parse_entries(project_path)
    return entries[-1] if entries else None


def get_entries_since(project_path: str, since: str) -> list[dict]:
    """Get entries since a given ISO timestamp string."""
    entries = parse_entries(project_path)
    since_dt = datetime.fromisoformat(since)
    result = []
    for e in entries:
        try:
            ts = datetime.fromisoformat(e["timestamp"])
            if ts >= since_dt:
                result.append(e)
        except (ValueError, TypeError):
            continue
    return result
