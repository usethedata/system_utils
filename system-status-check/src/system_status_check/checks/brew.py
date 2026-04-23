"""Homebrew outdated-package check (macOS hosts).

Uses `brew outdated --json=v2`, which emits a structured document with
separate `formulae` and `casks` arrays. No privileges required.

Supports a `flagged_packages` list from settings: package names matching
any entry in the list are annotated as "flagged" (e.g., `node`, `python@*`
may trigger macOS TCC re-grants after upgrade).
"""

from __future__ import annotations

import fnmatch
import json

from .. import ssh


NAME = "brew"


_REMOTE_SCRIPT = r"""
set +e
brew outdated --json=v2 2>/dev/null
"""


def _is_flagged(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def _parse(stdout: str, flagged_patterns: list[str]) -> tuple[list[dict], int]:
    """Return (items, flagged_count).

    items is a list of {name, type, installed_versions, current_version, pinned, flagged?}.
    Raises ValueError on invalid JSON.
    """
    if not stdout.strip():
        return ([], 0)

    data = json.loads(stdout)

    items: list[dict] = []
    flagged_count = 0

    for pkg_type, key in (("formula", "formulae"), ("cask", "casks")):
        for entry in data.get(key, []) or []:
            name = entry.get("name") or entry.get("full_name") or "(unknown)"
            flagged = _is_flagged(name, flagged_patterns)
            if flagged:
                flagged_count += 1
            item = {
                "name": name,
                "type": pkg_type,
                "installed_versions": entry.get("installed_versions", []),
                "current_version": entry.get("current_version"),
                "pinned": bool(entry.get("pinned", False)),
            }
            if flagged:
                item["flagged"] = True
            items.append(item)

    return (items, flagged_count)


def run(host_cfg: dict, settings: dict) -> dict:
    timeout = settings.get("per_check_timeout_seconds", 120)
    flagged_patterns = (settings.get("flagged_packages") or {}).get("brew", []) or []

    result = ssh.run(host_cfg, _REMOTE_SCRIPT, timeout=timeout)

    if result.timed_out:
        return {
            "status": "error",
            "items": [],
            "counts": {},
            "error": f"brew check timed out after {timeout}s",
        }

    if result.returncode != 0:
        return {
            "status": "error",
            "items": [],
            "counts": {},
            "error": f"brew outdated rc={result.returncode}",
            "raw_excerpt": ((result.stdout or "") + "\n---STDERR---\n" + (result.stderr or ""))[-1000:],
        }

    try:
        items, flagged_count = _parse(result.stdout, flagged_patterns)
    except json.JSONDecodeError as exc:
        return {
            "status": "error",
            "items": [],
            "counts": {},
            "error": f"brew outdated JSON parse failed: {exc}",
            "raw_excerpt": (result.stdout or "")[:500],
        }

    counts = {
        "outdated": len(items),
        "flagged": flagged_count,
    }
    status = "warn" if items else "ok"
    return {
        "status": status,
        "counts": counts,
        "items": items,
    }
