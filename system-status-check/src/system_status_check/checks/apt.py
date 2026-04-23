"""apt upgradable-package check (Ubuntu hosts).

Tries a cache refresh via `sudo -n apt-get update -qq`; continues even if
that fails (degraded mode) so the check still reports something useful
when the sudoers drop-in isn't present. `apt list --upgradable` itself is
unprivileged.
"""

from __future__ import annotations

import os
import re
import time

from .. import ssh


NAME = "apt"


_REMOTE_SCRIPT = r"""
set +e

# Try a cache refresh. Continue on failure so we can still report on
# whatever the cache already knows. Success stamp path is used below to
# flag staleness when the refresh fails.
refresh_rc=0
refresh_err=""
if sudo -n apt-get update -qq 2>__APT_STDERR__; then
    refresh_rc=0
else
    refresh_rc=$?
    refresh_err=$(cat __APT_STDERR__ 2>/dev/null)
fi
rm -f __APT_STDERR__ 2>/dev/null

# Age of last successful refresh, in seconds (0 if unknown).
stamp_age=0
if [[ -f /var/lib/apt/periodic/update-success-stamp ]]; then
    now=$(date +%s)
    stamp_mtime=$(stat -c %Y /var/lib/apt/periodic/update-success-stamp 2>/dev/null || echo 0)
    if [[ "$stamp_mtime" -gt 0 ]]; then
        stamp_age=$(( now - stamp_mtime ))
    fi
fi

printf '##APT-REFRESH rc=%s stamp_age=%s##\n' "$refresh_rc" "$stamp_age"
if [[ -n "$refresh_err" ]]; then
    printf '##APT-REFRESH-ERR##\n%s\n##END##\n' "$refresh_err"
fi

# Simulate-upgrade tells us which packages Ubuntu's phased-update policy is
# holding back from this machine. Those have a newer version available but
# `apt upgrade` won't actually install them yet — not actionable, so the
# parser uses this to filter them out of the upgradable list.
printf '##APT-SIMULATE##\n'
apt-get -s upgrade 2>/dev/null

printf '##APT-UPGRADABLE##\n'
apt list --upgradable 2>/dev/null
"""


# Example line from `apt list --upgradable`:
#   gir1.2-gtk-4.0/noble-updates 4.14.5+ds-0ubuntu0.10 amd64 [upgradable from: 4.14.5+ds-0ubuntu0.9]
_LINE_RE = re.compile(
    r"^(?P<name>[^/\s]+)"
    r"/(?P<origin>[^\s]+)\s+"
    r"(?P<candidate>\S+)\s+"
    r"(?P<arch>\S+)"
    r"(?:\s+\[upgradable from:\s*(?P<current>[^\]]+)\])?"
)

_STAMP_STALE_SECONDS = 24 * 3600  # 24h


def _parse_refresh_header(stdout: str) -> tuple[int, int, str]:
    """Return (rc, stamp_age_seconds, refresh_err)."""
    m = re.search(r"##APT-REFRESH rc=(-?\d+) stamp_age=(-?\d+)##", stdout)
    if not m:
        return (0, 0, "")
    rc = int(m.group(1))
    stamp_age = int(m.group(2))
    err = ""
    err_m = re.search(r"##APT-REFRESH-ERR##\n(.*?)\n##END##", stdout, re.DOTALL)
    if err_m:
        err = err_m.group(1).strip()
    return (rc, stamp_age, err)


def _parse_deferred_packages(stdout: str) -> set[str]:
    """Names of packages held back by Ubuntu's phased-update policy.

    These show up in `apt list --upgradable` (a newer version exists in the
    archive) but `apt upgrade` won't actually install them yet — Ubuntu's
    rollout policy is gating them based on a per-machine phase. They're
    not actionable, so the caller filters them out of the items list.
    """
    sim = "##APT-SIMULATE##"
    upg = "##APT-UPGRADABLE##"
    sim_idx = stdout.find(sim)
    if sim_idx < 0:
        return set()
    upg_idx = stdout.find(upg, sim_idx)
    block = stdout[sim_idx + len(sim):upg_idx if upg_idx > 0 else None]

    deferred: set[str] = set()
    in_block = False
    for line in block.splitlines():
        if "deferred due to phasing" in line:
            in_block = True
            continue
        if not in_block:
            continue
        # Continuation lines start with whitespace and list space-separated
        # package names. The block ends when we hit a non-indented line
        # (typically the "X upgraded, ..." summary).
        if not line[:1].isspace():
            in_block = False
            continue
        for name in line.split():
            deferred.add(name)
    return deferred


def _parse_upgradable_block(stdout: str) -> list[dict]:
    """Parse the `apt list --upgradable` section of combined stdout."""
    marker = "##APT-UPGRADABLE##"
    idx = stdout.find(marker)
    if idx < 0:
        return []
    block = stdout[idx + len(marker):]

    items = []
    for line in block.splitlines():
        line = line.strip()
        if not line or line == "Listing..." or line.startswith("WARNING"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            # Unknown shape — surface as-is rather than losing it.
            items.append({"raw": line})
            continue
        items.append({
            "name": m.group("name"),
            "origin": m.group("origin"),
            "candidate_version": m.group("candidate"),
            "arch": m.group("arch"),
            "current_version": m.group("current") or "",
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
            "error": f"apt check timed out after {timeout}s",
            "raw_excerpt": (result.stdout or "")[-500:],
        }

    refresh_rc, stamp_age, refresh_err = _parse_refresh_header(result.stdout)
    all_items = _parse_upgradable_block(result.stdout)
    deferred = _parse_deferred_packages(result.stdout)
    # Filter out packages Ubuntu's phasing policy is holding back. They're
    # listed in `apt list --upgradable` but not actionable until the rollout
    # reaches this machine.
    items = [i for i in all_items if i.get("name") not in deferred]

    warnings = []
    if refresh_rc != 0:
        hint = ""
        if "password is required" in refresh_err or "a terminal is required" in refresh_err:
            hint = " (likely missing sudoers drop-in or !requiretty)"
        stamp_note = ""
        if stamp_age > _STAMP_STALE_SECONDS:
            hours = stamp_age // 3600
            stamp_note = f"; apt cache last refreshed {hours}h ago"
        elif stamp_age > 0:
            mins = stamp_age // 60
            stamp_note = f"; apt cache last refreshed {mins}m ago"
        warnings.append(f"sudo -n apt-get update failed rc={refresh_rc}{hint}{stamp_note}")

    counts = {
        "upgradable": len(items),
        "deferred_phased": len(deferred),
        "refresh_rc": refresh_rc,
        "refresh_stale_seconds": stamp_age,
    }

    # Status logic:
    #   - any upgradable package -> warn
    #   - refresh failed AND stamp stale (>24h) -> warn (data quality)
    #   - clean and fresh -> ok
    if items:
        status = "warn"
    elif refresh_rc != 0 and stamp_age > _STAMP_STALE_SECONDS:
        status = "warn"
    else:
        status = "ok"

    out = {
        "status": status,
        "counts": counts,
        "items": items,
    }
    if warnings:
        out["warnings"] = warnings
    return out
