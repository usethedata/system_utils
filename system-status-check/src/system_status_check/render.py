"""Render a report dict as Markdown.

The Markdown is informational, not evaluative: no "OK / WARN / ERROR"
labels in the user-facing output. States of concern are conveyed by
typography leveraging Bruce's Obsidian theme (bold=red, italic=blue):

  Category labels (check names)          -> **bold**
  Clean / no updates                     -> plain text
  Notable counts or values               -> *italic*
  Strong alerts (Stale, Unreachable, ...) -> ***bold-italic***

The JSON report keeps the structured status fields; the daily brief
reads those. The Markdown renderer only looks at counts and raw data.
"""

from __future__ import annotations

from pathlib import Path


# Canonical check order across the report. Any check not listed falls
# through to "after the known ones" in its configured position.
_CHECK_ORDER = ("chezmoi", "synology_os", "synology_packages", "apt", "brew")

# Full label used in Details headings. Short label used in Summary line.
_LABELS = {
    "chezmoi":            ("Chezmoi",           "Chezmoi"),
    "apt":                ("Apt",               "Apt"),
    "brew":               ("Brew",              "Brew"),
    "synology_os":        ("Synology OS",       "OS"),
    "synology_packages":  ("Synology Packages", "Packages"),
}

_STAMP_STALE_SECONDS = 24 * 3600


def render(report: dict, log_path: str | Path | None = None) -> str:
    lines: list[str] = []

    run = report["run"]
    lines.append(f"- **Started**: {run['started_at']}")
    lines.append(f"- **Finished**: {run['finished_at']}")
    lines.append(f"- **Elapsed**: {_fmt_elapsed(run['elapsed_seconds'])}")
    lines.append(
        f"- **Orchestrator**: {run['orchestrator_host']} "
        f"(system-status-check {run['script_version']})"
    )
    if log_path:
        lines.append(f"- **Detailed Log**: {_log_link(log_path)}")
    lines.append("")

    hosts_sorted = sorted(report["hosts"], key=lambda h: h["alias"].lower())

    lines.append("# Summary")
    lines.append("")
    for h in hosts_sorted:
        lines.append(_summary_line(h))
    lines.append("")

    lines.append("# Details")
    lines.append("")
    for h in hosts_sorted:
        lines.extend(_detail_section(h))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Formatting primitives
# ---------------------------------------------------------------------------

def _bold(s: str) -> str:
    return f"**{s}**"


def _ital(s: str) -> str:
    return f"*{s}*"


def _bi(s: str) -> str:
    return f"***{s}***"


def _title_case_alias(alias: str) -> str:
    return alias[:1].upper() + alias[1:] if alias else alias


def _anchor(alias: str) -> str:
    return alias.lower()


def _fmt_elapsed(seconds: float) -> str:
    s = int(round(seconds))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _pluralize(n: int, singular: str, plural: str | None = None) -> str:
    if n == 1:
        return singular
    return plural if plural is not None else singular + "s"


def _log_link(log_path: str | Path) -> str:
    p = Path(log_path)
    name = p.name
    # The Markdown is read in Obsidian on a Mac, so the link must resolve
    # to the Mac-side Dropbox path even though this renderer runs on
    # grizzledbear.
    mac_path = str(p).replace(
        "/home/bruce/Dropbox",
        "/Users/bruce/Library/CloudStorage/Dropbox",
    )
    return f"[{name}](vscode://file{mac_path})"


# ---------------------------------------------------------------------------
# Host-level helpers
# ---------------------------------------------------------------------------

def _is_unreachable(host: dict) -> bool:
    reach = host.get("checks", {}).get("reachability", {})
    return reach.get("status") == "unreachable"


def _ordered_checks(host: dict) -> list[tuple[str, dict]]:
    """Return [(check_name, check_dict), ...] in canonical order.

    Skips reachability (handled separately). Unknown checks are placed
    after the known ones in their configured order.
    """
    checks = host.get("checks", {})
    ordered: list[tuple[str, dict]] = []
    for name in _CHECK_ORDER:
        if name in checks:
            ordered.append((name, checks[name]))
    for name, c in checks.items():
        if name in ("reachability",) or name in _CHECK_ORDER:
            continue
        ordered.append((name, c))
    return ordered


# ---------------------------------------------------------------------------
# Summary rendering
# ---------------------------------------------------------------------------

def _summary_line(host: dict) -> str:
    name = _title_case_alias(host["alias"])
    anchor = _anchor(host["alias"])
    prefix = f"- {_bold(f'[{name}](#{anchor})')}"

    if _is_unreachable(host):
        return f"{prefix} {_bi('Unreachable')}"

    parts = []
    for check_name, check in _ordered_checks(host):
        _, short = _LABELS.get(check_name, (check_name, check_name))
        state = _summary_state(check_name, check)
        parts.append(f"{short}: {state}")
    if not parts:
        return prefix
    return f"{prefix} " + ", ".join(parts)


def _summary_state(check_name: str, check: dict) -> str:
    if check.get("status") == "error":
        return _bi("error")

    counts = check.get("counts") or {}

    if check_name == "chezmoi":
        total = sum(v for v in counts.values() if isinstance(v, int))
        return "clean" if total == 0 else _ital("out of sync")

    if check_name == "apt":
        n = counts.get("upgradable", 0)
        stale = _is_apt_stale(check)
        parts = []
        if stale:
            parts.append(_bi("Stale"))
        if n > 0:
            parts.append(_ital(f"{n} {_pluralize(n, 'update')} pending"))
        if not parts:
            return "no updates pending"
        return " ".join(parts)

    if check_name == "brew":
        n = counts.get("outdated", 0)
        return "no updates pending" if n == 0 else _ital(f"{n} {_pluralize(n, 'update')} pending")

    if check_name == "synology_packages":
        n = counts.get("available", 0)
        return "no updates pending" if n == 0 else _ital(f"{n} {_pluralize(n, 'update')} pending")

    if check_name == "synology_os":
        n = counts.get("available", 0)
        return "no updates pending" if n == 0 else _ital("Update pending")

    return check.get("status", "")


def _is_apt_stale(check: dict) -> bool:
    counts = check.get("counts") or {}
    return (
        counts.get("refresh_rc", 0) != 0
        and counts.get("refresh_stale_seconds", 0) > _STAMP_STALE_SECONDS
    )


# ---------------------------------------------------------------------------
# Details rendering
# ---------------------------------------------------------------------------

def _detail_section(host: dict) -> list[str]:
    name = _title_case_alias(host["alias"])
    lines = [f"## {name}"]

    if _is_unreachable(host):
        lines.append(f"- {_bi('Unreachable')}")
        return lines

    for check_name, check in _ordered_checks(host):
        lines.extend(_detail_check(check_name, check))
    return lines


def _detail_check(check_name: str, check: dict) -> list[str]:
    full, _ = _LABELS.get(check_name, (check_name, check_name))
    bolded = _bold(full)

    if check.get("status") == "error":
        out = [f"- {bolded}: {_bi(check.get('error', 'error'))}"]
        raw = check.get("raw_excerpt")
        if raw:
            out.append(f"  - raw: `{raw}`")
        return out

    if check_name == "chezmoi":
        return _detail_chezmoi(bolded, check)

    if check_name == "apt":
        return _detail_apt(bolded, check)

    if check_name == "brew":
        return _detail_brew(bolded, check)

    if check_name == "synology_packages":
        return _detail_synology_packages(bolded, check)

    if check_name == "synology_os":
        return _detail_synology_os(bolded, check)

    return [f"- {bolded}: {check.get('status', '')}"]


def _detail_chezmoi(label: str, check: dict) -> list[str]:
    counts = check.get("counts") or {}
    total = sum(v for v in counts.values() if isinstance(v, int))
    if total == 0:
        return [f"- {label}: clean"]

    field_order = [
        ("local_drift",            "Local drift"),
        ("source_uncommitted",     "Source uncommitted"),
        ("source_ahead_of_remote", "Source ahead of remote"),
        ("source_behind_remote",   "Source behind remote"),
    ]
    parts = []
    for key, display in field_order:
        v = counts.get(key, 0)
        text = f"{display}={v}"
        parts.append(_ital(text) if v > 0 else text)
    head = f"- {label}: {_bold('Out of Sync')} " + ", ".join(parts)
    out = [head]

    items = check.get("items") or {}
    for entry in (items.get("local_drift") or [])[:30]:
        out.append(
            f"  - local: `{entry.get('source_state', '')}{entry.get('target_state', '')}` "
            f"{entry.get('path', '')}"
        )
    for entry in (items.get("source_repo") or [])[:30]:
        out.append(f"  - source uncommitted: `{entry.get('git_status', '')}` {entry.get('path', '')}")
    return out


def _detail_apt(label: str, check: dict) -> list[str]:
    counts = check.get("counts") or {}
    n = counts.get("upgradable", 0)
    stale = _is_apt_stale(check)

    head_parts = []
    if stale:
        stale_age = counts.get("refresh_stale_seconds", 0)
        head_parts.append(_bi(f"Stale by {_fmt_elapsed(stale_age)}"))
    if n > 0:
        head_parts.append(f"{n} {_pluralize(n, 'update')} pending")
    if not head_parts:
        return [f"- {label}: no updates pending"]

    out = [f"- {label}: " + " ".join(head_parts)]
    for entry in (check.get("items") or [])[:30]:
        if "raw" in entry:
            out.append(f"  - `{entry['raw']}`")
            continue
        out.append(
            f"  - `{entry['name']}`: "
            f"{entry.get('current_version') or '?'} → {entry['candidate_version']} "
            f"[{entry['origin']}]"
        )
    extra = len(check.get("items") or []) - 30
    if extra > 0:
        out.append(f"  - … and {extra} more")
    return out


def _detail_brew(label: str, check: dict) -> list[str]:
    counts = check.get("counts") or {}
    n = counts.get("outdated", 0)
    if n == 0:
        return [f"- {label}: no updates pending"]

    out = [f"- {label}: {n} {_pluralize(n, 'update')} pending"]
    for entry in (check.get("items") or [])[:30]:
        flag = " ⚑" if entry.get("flagged") else ""
        pin = " (pinned)" if entry.get("pinned") else ""
        installed = ",".join(entry.get("installed_versions", []))
        out.append(
            f"  - `{entry['name']}` ({entry.get('type', 'formula')}): "
            f"{installed} → {entry.get('current_version')}{pin}{flag}"
        )
    extra = n - 30
    if extra > 0:
        out.append(f"  - … and {extra} more")
    return out


def _detail_synology_packages(label: str, check: dict) -> list[str]:
    counts = check.get("counts") or {}
    n = counts.get("available", 0)
    if n == 0:
        return [f"- {label}: no updates pending"]

    out = [f"- {label}: {n} {_pluralize(n, 'update')} pending"]
    for entry in (check.get("items") or [])[:30]:
        if "raw" in entry:
            out.append(f"  - `{entry['raw']}`")
            continue
        beta = " (beta)" if entry.get("beta") else ""
        out.append(
            f"  - `{entry.get('id')}` — {entry.get('name')}: "
            f"available {entry.get('available_version')}{beta}"
        )
    extra = n - 30
    if extra > 0:
        out.append(f"  - … and {extra} more")
    return out


def _detail_synology_os(label: str, check: dict) -> list[str]:
    counts = check.get("counts") or {}
    n = counts.get("available", 0)
    if n == 0:
        return [f"- {label}: no updates pending"]

    out = [f"- {label}: Update Pending"]
    raw = check.get("raw")
    if raw:
        out.append(f"  - raw: `{raw}`")
    return out
