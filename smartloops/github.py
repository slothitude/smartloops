"""Smart Loops — GitHub API (read-only).

Fetches issues, milestones, and PRs from GitHub repos.
Uses the gh CLI or falls back to the REST API with urllib.
"""

import json
import os
import subprocess
import urllib.request
import urllib.error

from config import GITHUB_TOKEN


def _get_repo_slug(project_path: str) -> str | None:
    """Extract 'owner/repo' from git remote origin URL."""
    try:
        result = subprocess.run(
            ["git", "-C", project_path, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10,
            stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace",
        )
        url = result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return None

    if not url:
        return None

    # Handle https://github.com/owner/repo.git
    if "github.com" in url:
        parts = url.split("github.com")[-1].lstrip(":/").removesuffix(".git")
        if "/" in parts:
            return parts
    # Handle git@github.com:owner/repo.git
    if url.startswith("git@github.com:"):
        parts = url.removeprefix("git@github.com:").removesuffix(".git")
        if "/" in parts:
            return parts
    return None


def _api_get(path: str) -> dict | list | None:
    """Make an authenticated GitHub API request. Returns parsed JSON or None."""
    url = f"https://api.github.com{path}"
    headers = {
        "Accept": "application/vnd.github+json",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError, ConnectionError):
        return None


def _gh_cli(args: list[str]) -> str | None:
    """Run a gh CLI command, return stdout or None on failure."""
    try:
        env = os.environ.copy()
        if GITHUB_TOKEN:
            env["GH_TOKEN"] = GITHUB_TOKEN
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True, text=True, timeout=15,
            stdin=subprocess.DEVNULL, env=env,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def get_open_issues(project_path: str) -> list[dict]:
    """List open issues. Returns list of {number, title, labels, created_at}."""
    slug = _get_repo_slug(project_path)
    if not slug:
        return []

    # Try gh CLI first, fall back to API
    output = _gh_cli(["issue", "list", "-R", slug, "--state", "open",
                       "--limit", "50", "--json", "number,title,labels,createdAt"])
    if output:
        try:
            items = json.loads(output)
            return [
                {
                    "number": i["number"],
                    "title": i["title"],
                    "labels": [l["name"] for l in i.get("labels", [])],
                    "created_at": i.get("createdAt", ""),
                }
                for i in items
            ]
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback: REST API
    data = _api_get(f"/repos/{slug}/issues?state=open&per_page=50")
    if isinstance(data, list):
        return [
            {
                "number": i["number"],
                "title": i["title"],
                "labels": [l["name"] for l in i.get("labels", [])],
                "created_at": i.get("created_at", ""),
            }
            for i in data
            if "pull_request" not in i  # issues endpoint includes PRs
        ]
    return []


def get_milestones(project_path: str) -> list[dict]:
    """List milestones with completion %. Returns list of {title, open, closed, completion_pct}."""
    slug = _get_repo_slug(project_path)
    if not slug:
        return []

    data = _api_get(f"/repos/{slug}/milestones?state=all&per_page=30")
    if not isinstance(data, list):
        return []

    results = []
    for m in data:
        total = m.get("open_issues", 0) + m.get("closed_issues", 0)
        closed = m.get("closed_issues", 0)
        pct = round(closed / total * 100) if total > 0 else 0
        results.append({
            "title": m.get("title", ""),
            "open": m.get("open_issues", 0),
            "closed": closed,
            "completion_pct": pct,
            "due_on": m.get("due_on") or "",
        })
    return results


def get_open_prs(project_path: str) -> list[dict]:
    """List open PRs. Returns list of {number, title, author, created_at, draft}."""
    slug = _get_repo_slug(project_path)
    if not slug:
        return []

    # Try gh CLI first
    output = _gh_cli(["pr", "list", "-R", slug, "--state", "open",
                       "--limit", "50", "--json", "number,title,author,createdAt,isDraft"])
    if output:
        try:
            items = json.loads(output)
            return [
                {
                    "number": i["number"],
                    "title": i["title"],
                    "author": i.get("author", {}).get("login", ""),
                    "created_at": i.get("createdAt", ""),
                    "draft": i.get("isDraft", False),
                }
                for i in items
            ]
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback: REST API
    data = _api_get(f"/repos/{slug}/pulls?state=open&per_page=50")
    if isinstance(data, list):
        return [
            {
                "number": pr["number"],
                "title": pr["title"],
                "author": pr.get("user", {}).get("login", ""),
                "created_at": pr.get("created_at", ""),
                "draft": pr.get("draft", False),
            }
            for pr in data
        ]
    return []


def get_github_summary(project_path: str) -> dict:
    """Get a combined GitHub summary for audit integration.

    Returns dict with: open_issues, open_prs, milestones, has_github.
    Safely handles no github repo, offline network, and API failures.
    """
    slug = _get_repo_slug(project_path)
    if not slug:
        return {"has_github": False}

    # All three calls can fail independently — don't let one kill the summary
    issues = []
    prs = []
    milestones = []
    try:
        issues = get_open_issues(project_path)
    except Exception:
        pass
    try:
        prs = get_open_prs(project_path)
    except Exception:
        pass
    try:
        milestones = get_milestones(project_path)
    except Exception:
        pass

    return {
        "has_github": True,
        "repo": slug,
        "open_issues": issues,
        "open_issues_count": len(issues),
        "open_prs": prs,
        "open_prs_count": len(prs),
        "milestones": milestones,
    }
