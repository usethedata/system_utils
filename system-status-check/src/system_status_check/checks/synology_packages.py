"""Synology package-update check (DSM hosts).

Uses `synopkg checkupdateall` (DSM 7.3+), which returns a JSON array of
entries with {id, name, version, beta}. Empty-list output is `[]`.

Note: earlier drafts of the plan referred to `synopkg checkupdate` as the
list-all command; that is incorrect — on DSM 7.3, `checkupdate` requires
a package-name argument. `checkupdateall` is the right list variant. No
privileges required.
"""

from __future__ import annotations

import json

from .. import ssh


NAME = "synology_packages"


_REMOTE_SCRIPT = r"""
set +e
synopkg checkupdateall
"""


def _parse(stdout: str) -> list[dict]:
    """Return a list of {id, name, version, beta}. Raises ValueError on bad JSON."""
    s = stdout.strip()
    if not s:
        return []
    data = json.loads(s)
    if not isinstance(data, list):
        raise ValueError(f"expected JSON array, got {type(data).__name__}")

    items = []
    for entry in data:
        if not isinstance(entry, dict):
            items.append({"raw": entry})
            continue
        items.append({
            "id": entry.get("id"),
            "name": entry.get("name"),
            "available_version": entry.get("version"),
            "beta": bool(entry.get("beta", False)),
        })
    return items


def run(host_cfg: dict, settings: dict) -> dict:
    timeout = settings.get("per_check_timeout_seconds", 120)
    result = ssh.run(host_cfg, _REMOTE_SCRIPT, timeout=timeout)

    if result.timed_out:
        return {
            "status": "error",
            "items": [],
            "counts": {},
            "error": f"synopkg check timed out after {timeout}s",
        }

    if result.returncode != 0:
        return {
            "status": "error",
            "items": [],
            "counts": {},
            "error": f"synopkg checkupdateall rc={result.returncode}",
            "raw_excerpt": ((result.stdout or "") + "\n---STDERR---\n" + (result.stderr or ""))[-500:],
        }

    try:
        items = _parse(result.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        # Parser drift rather than silent pass — surface the raw output.
        return {
            "status": "warn",
            "items": [],
            "counts": {},
            "error": f"synopkg checkupdateall: unparseable output ({exc})",
            "raw_excerpt": (result.stdout or "")[:500],
        }

    counts = {"available": len(items)}
    status = "warn" if items else "ok"
    return {
        "status": status,
        "counts": counts,
        "items": items,
    }
