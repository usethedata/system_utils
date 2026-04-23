"""Reachability probe. Gates all other checks for a host."""

from __future__ import annotations

from .. import ssh


NAME = "reachability"


def run(host_cfg: dict, settings: dict) -> dict:
    """Probe the host. Returns a CheckResult-shaped dict.

    status:
      - "ok" if the SSH/local probe succeeds
      - "unreachable" if it fails for any reason (connect timeout, auth, refused, ...)

    The dispatcher is responsible for mapping "unreachable" into the correct
    host-level bucket (warn if unreachable_is_expected, else unreachable).
    """
    connect_timeout = settings.get("ssh_connect_timeout_seconds", 10)
    # Give the overall subprocess a small cushion over the connect timeout
    # so BatchMode auth failures still return quickly rather than hitting our
    # own timeout.
    overall_timeout = connect_timeout + 5

    result = ssh.run(host_cfg, "true\n", timeout=overall_timeout, connect_timeout=connect_timeout)

    if result.returncode == 0:
        return {
            "status": "ok",
            "items": [],
            "counts": {},
            "elapsed_seconds": round(result.elapsed_seconds, 3),
        }

    return {
        "status": "unreachable",
        "items": [],
        "counts": {},
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "error": (result.stderr or "").strip()[:500] or f"ssh exit {result.returncode}",
    }
