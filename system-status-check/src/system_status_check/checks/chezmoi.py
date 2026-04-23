"""chezmoi drift check.

Two sub-commands, run remotely via one SSH call:
  1. Local drift:        `chezmoi status`
  2. Source-repo drift:  `chezmoi git -- fetch` (quietly, to refresh remote-tracking state),
                         then `chezmoi git -- status --porcelain=v1 --branch`

An earlier version also invoked `chezmoi update --dry-run`, but that command
prompts interactively when the target state has drifted locally (chezmoi
would overwrite the file during a real update). Non-interactive SSH has no
TTY, so the prompt fails. More fundamentally, the three sub-counts we get
from status + git-status already cover the "is this machine in sync?"
question along every axis we care about (target vs source, source vs
remote, uncommitted source changes). Removing the dry-run simplifies the
check and eliminates the TTY issue.
"""

from __future__ import annotations

import re

from .. import ssh


NAME = "chezmoi"


_REMOTE_SCRIPT = r"""
set +e
begin() { printf '\n##CMCHK-BEGIN-%s##\n' "$1"; }
end()   { printf '\n##CMCHK-END-%s rc=%s##\n' "$1" "$2"; }

begin STATUS
chezmoi status
status_rc=$?
end STATUS "$status_rc"

# Refresh remote-tracking state so the porcelain status below reports
# accurate ahead/behind counts. Errors are tolerated (e.g. offline); the
# porcelain status will just reflect stale tracking info.
chezmoi git -- fetch --quiet 2>/dev/null

begin GITSTATUS
chezmoi git -- status --porcelain=v1 --branch
gitstatus_rc=$?
end GITSTATUS "$gitstatus_rc"
"""


_SECTION_RE = re.compile(
    r"##CMCHK-BEGIN-(?P<name>[A-Z]+)##\n(?P<body>.*?)##CMCHK-END-(?P=name) rc=(?P<rc>-?\d+)##",
    re.DOTALL,
)


def _split_sections(stdout: str) -> dict:
    """Return {section_name: (body, rc)} for each sentinel-fenced section."""
    out = {}
    for m in _SECTION_RE.finditer(stdout):
        out[m.group("name")] = (m.group("body").strip("\n"), int(m.group("rc")))
    return out


def _parse_status(body: str) -> list:
    """Parse `chezmoi status` output.

    Format: two status-code columns (each a single char or space), then a
    space, then the target path. Example:
        MM entry.txt
         A new_entry.txt
        D  removed.txt
    """
    items = []
    for line in body.splitlines():
        if not line.strip():
            continue
        if len(line) < 3:
            continue
        source = line[0]
        target = line[1]
        path = line[3:] if len(line) > 3 else ""
        items.append({
            "source_state": source,
            "target_state": target,
            "path": path,
        })
    return items


def _parse_git_status(body: str) -> dict:
    """Parse `chezmoi git -- status --porcelain=v1 --branch` output.

    First line is `## branch...upstream [ahead N, behind M]`. Subsequent
    lines are porcelain-v1 entries (two-char status + space + path).
    """
    lines = body.splitlines()
    ahead = 0
    behind = 0
    branch_line = ""
    entries = []

    for i, line in enumerate(lines):
        if i == 0 and line.startswith("##"):
            branch_line = line
            m = re.search(r"ahead (\d+)", line)
            if m:
                ahead = int(m.group(1))
            m = re.search(r"behind (\d+)", line)
            if m:
                behind = int(m.group(1))
            continue
        if not line.strip():
            continue
        if len(line) < 3:
            continue
        git_status = line[:2]
        path = line[3:]
        entries.append({"git_status": git_status, "path": path})

    return {
        "branch_line": branch_line,
        "ahead": ahead,
        "behind": behind,
        "entries": entries,
    }




def run(host_cfg: dict, settings: dict) -> dict:
    """Run the chezmoi check bundle. Returns a CheckResult-shaped dict."""
    timeout = settings.get("per_check_timeout_seconds", 120)
    result = ssh.run(host_cfg, _REMOTE_SCRIPT, timeout=timeout)

    if result.timed_out:
        return {
            "status": "error",
            "items": [],
            "counts": {},
            "error": f"chezmoi check timed out after {timeout}s",
            "raw_excerpt": (result.stdout or "")[-500:],
        }

    sections = _split_sections(result.stdout)
    missing = [s for s in ("STATUS", "GITSTATUS") if s not in sections]
    if missing:
        return {
            "status": "error",
            "items": [],
            "counts": {},
            "error": f"chezmoi: missing output sections: {missing}",
            "raw_excerpt": ((result.stdout or "") + "\n---STDERR---\n" + (result.stderr or ""))[-1000:],
        }

    status_body, status_rc = sections["STATUS"]
    git_body, git_rc = sections["GITSTATUS"]

    # Any non-zero rc in a sub-check is a hard error — surface it so Bruce
    # knows chezmoi itself is unhappy (not just reporting drift).
    sub_errors = []
    if status_rc != 0:
        sub_errors.append(f"chezmoi status rc={status_rc}")
    if git_rc != 0:
        sub_errors.append(f"chezmoi git status rc={git_rc}")

    local_items = _parse_status(status_body)
    git_parsed = _parse_git_status(git_body)

    counts = {
        "local_drift": len(local_items),
        "source_uncommitted": len(git_parsed["entries"]),
        "source_ahead_of_remote": git_parsed["ahead"],
        "source_behind_remote": git_parsed["behind"],
    }

    if sub_errors:
        status_label = "error"
    elif any(counts.values()):
        status_label = "warn"
    else:
        status_label = "ok"

    out = {
        "status": status_label,
        "counts": counts,
        "items": {
            "local_drift": local_items,
            "source_repo": git_parsed["entries"],
        },
        "branch": git_parsed["branch_line"],
    }
    if sub_errors:
        out["error"] = "; ".join(sub_errors)
        out["raw_excerpt"] = ((result.stdout or "") + "\n---STDERR---\n" + (result.stderr or ""))[-1000:]
    return out
