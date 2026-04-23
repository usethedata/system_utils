"""Per-host orchestration and JSON aggregation."""

from __future__ import annotations

import logging
import socket
from datetime import datetime, timezone

from . import __version__
from .checks import apt, brew, chezmoi, reachability, synology_os, synology_packages


log = logging.getLogger(__name__)


# Registry of available check modules. Each module exposes NAME and run().
# Reachability is handled specially by the dispatcher (runs first, gates the rest).
_CHECKS = {
    chezmoi.NAME: chezmoi,
    apt.NAME: apt,
    brew.NAME: brew,
    synology_packages.NAME: synology_packages,
    synology_os.NAME: synology_os,
}


def _unreachable_placeholder() -> dict:
    return {"status": "unreachable", "items": [], "counts": {}}


def _skipped_placeholder() -> dict:
    return {"status": "skipped", "items": [], "counts": {}}


def _host_overall(host_cfg: dict, check_results: dict) -> str:
    """Compute the host's rollup status from its per-check statuses.

    Rules:
      - any check with "error"   → host "error"
      - any check "unreachable"  → host "warn" if unreachable_is_expected else "unreachable"
      - any check with "warn"    → host "warn"
      - otherwise                → host "ok"
    """
    statuses = [r["status"] for r in check_results.values()]
    if "error" in statuses:
        return "error"
    if "unreachable" in statuses:
        return "warn" if host_cfg.get("unreachable_is_expected") else "unreachable"
    if "warn" in statuses:
        return "warn"
    return "ok"


def run_host(host_cfg: dict, settings: dict, check_filter: str | None = None) -> dict:
    """Run all configured checks for one host. Returns the host's report entry."""
    alias = host_cfg["alias"]
    configured = list(host_cfg.get("checks", []))

    results: dict[str, dict] = {}

    # Reachability is always first and gates everything else.
    if "reachability" in configured:
        log.info("[%s] reachability probe", alias)
        reach = reachability.run(host_cfg, settings)
        results["reachability"] = reach
        unreachable = reach["status"] == "unreachable"
    else:
        # Reachability not configured — assume reachable and proceed.
        unreachable = False

    for check_name in configured:
        if check_name == "reachability":
            continue
        if check_filter is not None and check_name != check_filter:
            results[check_name] = _skipped_placeholder()
            continue

        if unreachable:
            results[check_name] = _unreachable_placeholder()
            continue

        module = _CHECKS.get(check_name)
        if module is None:
            log.warning("[%s] unknown check %r — skipping", alias, check_name)
            results[check_name] = {
                "status": "error",
                "items": [],
                "counts": {},
                "error": f"unknown check: {check_name}",
            }
            continue

        log.info("[%s] %s", alias, check_name)
        try:
            results[check_name] = module.run(host_cfg, settings)
        except Exception as exc:
            log.exception("[%s] %s raised", alias, check_name)
            results[check_name] = {
                "status": "error",
                "items": [],
                "counts": {},
                "error": f"{type(exc).__name__}: {exc}",
            }

    return {
        "alias": alias,
        "os": host_cfg["os"],
        "overall_status": _host_overall(host_cfg, results),
        "checks": results,
    }


def _summarize(host_entries: list[dict]) -> dict:
    """Compute summary counters across all hosts.

    Mutually exclusive buckets — each host lands in exactly one of ok/warn/error/unreachable.
    """
    buckets = {"ok": 0, "warn": 0, "error": 0, "unreachable": 0}
    updates_pending = 0
    for h in host_entries:
        buckets[h["overall_status"]] = buckets.get(h["overall_status"], 0) + 1
        for check in h["checks"].values():
            counts = check.get("counts") or {}
            # Per-check "updates pending" contribution: heuristic — sum
            # specific count keys that are known to represent pending work.
            for key in ("pending_remote", "outdated", "upgradable", "available"):
                if key in counts and isinstance(counts[key], int):
                    updates_pending += counts[key]

    return {
        "hosts_total": len(host_entries),
        "hosts_ok": buckets["ok"],
        "hosts_warn": buckets["warn"],
        "hosts_error": buckets["error"],
        "hosts_unreachable": buckets["unreachable"],
        "updates_pending_total": updates_pending,
    }


def run_all(config: dict, host_filter: str | None = None, check_filter: str | None = None) -> dict:
    """Run the full orchestration. Returns the top-level report dict."""
    settings = config.get("settings", {}) or {}
    hosts = config.get("hosts", []) or []

    if host_filter:
        hosts = [h for h in hosts if h["alias"] == host_filter]
        if not hosts:
            raise ValueError(f"no host matches --host {host_filter!r}")

    started = datetime.now().astimezone()
    host_entries = []
    for host_cfg in hosts:
        host_entries.append(run_host(host_cfg, settings, check_filter=check_filter))
    finished = datetime.now().astimezone()

    return {
        "schema_version": 1,
        "run": {
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": finished.isoformat(timespec="seconds"),
            "elapsed_seconds": round((finished - started).total_seconds(), 1),
            "orchestrator_host": socket.gethostname().split(".")[0],
            "script_version": __version__,
        },
        "summary": _summarize(host_entries),
        "hosts": host_entries,
        "errors": [],
    }
