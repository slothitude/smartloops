"""Smart Loops — Ralph journal read/write (.smartloops/ralph_journal.md)."""

import os
from datetime import datetime

from config import SMARTLOOPS_DIR, RALPH_JOURNAL_FILE


def _journal_path(project_path: str) -> str:
    return os.path.join(project_path, SMARTLOOPS_DIR, RALPH_JOURNAL_FILE)


def append_entry(project_path: str, observed: str, action: str,
                 next_wake: str, reason: str):
    """Append a new journal entry."""
    path = _journal_path(project_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    entry = (
        f"\n## {now}\n\n"
        f"Observed:\n{observed}\n\n"
        f"Action:\n{action}\n\n"
        f"Next Wake:\n{next_wake}\n\n"
        f"Reason:\n{reason}\n"
    )

    # Create file with header if it doesn't exist
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Ralph Journal\n")

    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)


def read_entries(project_path: str, limit: int = 20) -> list[dict]:
    """Parse journal entries, most recent last."""
    path = _journal_path(project_path)
    if not os.path.isfile(path):
        return []

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return []

    entries = []
    raw = content.split("## ")
    for chunk in raw[1:]:  # skip preamble
        lines = chunk.strip().splitlines()
        if not lines:
            continue

        timestamp = lines[0].strip()
        body = "\n".join(lines[1:])

        try:
            entry = {
                "timestamp": timestamp,
                "observed": _extract_section(body, "observed"),
                "action": _extract_section(body, "action"),
                "next_wake": _extract_section(body, "next wake"),
                "reason": _extract_section(body, "reason"),
            }
            entries.append(entry)
        except Exception:
            continue

    # Return last `limit` entries
    return entries[-limit:]


def read_entries_since(project_path: str, since: str) -> list[dict]:
    """Get entries since a given ISO timestamp."""
    entries = read_entries(project_path)
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


def _extract_section(body: str, section_name: str) -> str:
    """Extract text between section header and next section or end."""
    import re
    # Match "Section Name:\n<content>" until next "Section Name:" or end
    pattern = rf"(?i){section_name}:\s*\n(.*?)(?=\n\S+:|\Z)"
    m = re.search(pattern, body, re.DOTALL)
    return m.group(1).strip() if m else ""
