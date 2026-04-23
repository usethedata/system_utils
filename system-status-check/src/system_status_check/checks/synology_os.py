"""Synology DSM OS-update check (DSM hosts).

Uses `sudo -n /usr/syno/sbin/synoupgrade --check`. Requires a sudoers
drop-in with NOPASSWD and `Defaults:<user> !requiretty` — see the plan's
"Tasks Bruce does manually (sudo required)" section.

Non-obvious behavior: `synoupgrade --check` returns **rc=255** (not 0) on
clean hosts when no DSM update is ready, along with stdout
`UPGRADE_CHECKNEWDSM`. The parser treats the literal presence of that
token as the authoritative "no update" signal regardless of rc. Any other
output (or absence of the token) is surfaced verbatim as "may be pending"
until we see real update output and can refine.

Independent fallback: each Synology is configured to email Bruce when a
DSM update is ready to install. If this check misbehaves, the email is
the authoritative signal.
"""

from __future__ import annotations

from .. import ssh


NAME = "synology_os"


_REMOTE_SCRIPT = r"""
set +e
sudo -n /usr/syno/sbin/synoupgrade --check
"""


_NO_UPDATE_TOKEN = "UPGRADE_CHECKNEWDSM"


def run(host_cfg: dict, settings: dict) -> dict:
    timeout = settings.get("per_check_timeout_seconds", 120)
    result = ssh.run(host_cfg, _REMOTE_SCRIPT, timeout=timeout)

    if result.timed_out:
        return {
            "status": "error",
            "items": [],
            "counts": {},
            "error": f"synoupgrade check timed out after {timeout}s",
        }

    combined = (result.stdout or "") + "\n" + (result.stderr or "")

    # "Password required" is the classic sign the sudoers drop-in or
    # !requiretty line is missing. Surface it as error.
    if "password is required" in combined or "a terminal is required" in combined:
        return {
            "status": "error",
            "items": [],
            "counts": {},
            "error": "sudo -n synoupgrade refused — check sudoers drop-in and Defaults !requiretty",
            "raw_excerpt": combined[:500].strip(),
        }

    if _NO_UPDATE_TOKEN in result.stdout:
        return {
            "status": "ok",
            "items": [],
            "counts": {"available": 0},
            "raw": result.stdout.strip(),
        }

    # Anything else: we don't know the format yet. Surface verbatim and
    # flag as warn (the DSM email notification is the authoritative
    # fallback signal, per the plan).
    return {
        "status": "warn",
        "items": [],
        "counts": {"available": 1},  # "maybe" — daily brief will add commentary
        "raw": result.stdout.strip(),
        "warnings": [
            "synoupgrade output did not contain UPGRADE_CHECKNEWDSM — update may be pending; confirm via DSM email / Control Panel."
        ],
    }
