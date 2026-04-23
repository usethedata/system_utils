"""CLI entry point for system-status-check."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

from . import dispatch, render


_DEFAULT_CONFIG = "~/.config/system-status-check/hosts.yaml"


def _expand(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p)))


def _setup_logging(log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"system-status-check-{ts}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(sys.stderr),
        ],
    )
    return log_path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="system-status-check",
        description="Nightly status report for Bruce's managed *nix systems.",
    )
    p.add_argument(
        "--config", default=_DEFAULT_CONFIG,
        help=f"Path to hosts.yaml (default: {_DEFAULT_CONFIG})",
    )
    p.add_argument(
        "--host", default=None,
        help="Run checks for only this host alias.",
    )
    p.add_argument(
        "--check", default=None,
        help="Run only this check (reachability always runs as a gate).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Write reports to /tmp/ instead of the configured report_dir.",
    )
    return p.parse_args(argv)


def _resolve_dirs(config: dict, dry_run: bool) -> tuple[Path, Path]:
    settings = config.get("settings", {}) or {}
    log_dir = _expand(settings.get("log_dir", "~/Dropbox/BEWMain/Data/logs"))
    report_dir = _expand(settings.get("report_dir", "~/Dropbox/BEWMain/MainVault/Data/system-status"))
    if dry_run:
        report_dir = Path("/tmp") / "system-status-check-dryrun"
    return log_dir, report_dir


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    config_path = _expand(args.config)
    if not config_path.exists():
        print(f"Error: config not found at {config_path}", file=sys.stderr)
        return 2

    with config_path.open() as f:
        config = yaml.safe_load(f)

    log_dir, report_dir = _resolve_dirs(config, args.dry_run)
    log_path = _setup_logging(log_dir)
    log = logging.getLogger("system_status_check")
    log.info("system-status-check start (dry_run=%s)", args.dry_run)
    log.info("log: %s", log_path)

    report = dispatch.run_all(config, host_filter=args.host, check_filter=args.check)

    report_dir.mkdir(parents=True, exist_ok=True)
    date_str = report["run"]["started_at"][:10]
    json_path = report_dir / f"system-status-check-{date_str}.json"
    md_path = report_dir / f"system-status-check-{date_str}.md"

    json_path.write_text(json.dumps(report, indent=2) + "\n")
    md_path.write_text(render.render(report, log_path=log_path))

    log.info("wrote %s", json_path)
    log.info("wrote %s", md_path)
    log.info(
        "summary: ok=%d warn=%d error=%d unreachable=%d updates_pending=%d",
        report["summary"]["hosts_ok"],
        report["summary"]["hosts_warn"],
        report["summary"]["hosts_error"],
        report["summary"]["hosts_unreachable"],
        report["summary"]["updates_pending_total"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
