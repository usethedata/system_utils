"""Thin wrapper around `ssh <alias> bash -s` (and local bash) with a shared PATH prelude."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass


# Shared PATH prelude: covers the union of locations where Bruce's managed
# tools live across macOS (homebrew intel + apple silicon), Ubuntu (snap),
# and Synology DSM (/usr/syno/{bin,sbin}). Prepended to every remote script
# so the non-login ssh shell can find chezmoi, synopkg, etc. without relying
# on the remote's login-shell PATH setup.
_PATH_PRELUDE = (
    'export PATH='
    '"$HOME/bin:'
    '$HOME/.local/bin:'
    '/usr/local/bin:'
    '/opt/homebrew/bin:'
    '/snap/bin:'
    '/usr/bin:'
    '/bin:'
    '/usr/syno/bin:'
    '/usr/syno/sbin:'
    '/usr/sbin:'
    '/sbin"'
)


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float
    timed_out: bool = False


def run(host_cfg: dict, script: str, timeout: int = 120, connect_timeout: int = 10) -> Result:
    """Run a bash script on a host (remote via SSH or local).

    The script is fed to `bash -s` on stdin, with the shared PATH prelude prepended.
    For hosts with `local: true` in config, runs locally without SSH.
    """
    full_script = _PATH_PRELUDE + "\n" + script

    alias = host_cfg["alias"]
    is_local = bool(host_cfg.get("local", False))

    if is_local:
        cmd = ["bash", "-s"]
    else:
        cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={connect_timeout}",
            alias,
            "bash", "-s",
        ]

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            input=full_script,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return Result(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            elapsed_seconds=time.monotonic() - t0,
        )
    except subprocess.TimeoutExpired as e:
        return Result(
            returncode=-1,
            stdout=(e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")),
            stderr=(e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")) +
                   f"\n[timed out after {timeout}s]",
            elapsed_seconds=time.monotonic() - t0,
            timed_out=True,
        )
