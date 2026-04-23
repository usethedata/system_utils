"""Tests for dispatch._host_overall and _summarize rollup logic."""

from __future__ import annotations

from system_status_check.dispatch import _host_overall, _summarize


def _r(status, counts=None):
    return {"status": status, "counts": counts or {}, "items": []}


def test_all_ok():
    host_cfg = {"alias": "x", "os": "ubuntu", "checks": []}
    results = {"reachability": _r("ok"), "chezmoi": _r("ok")}
    assert _host_overall(host_cfg, results) == "ok"


def test_warn_from_chezmoi():
    host_cfg = {"alias": "x", "os": "ubuntu", "checks": []}
    results = {"reachability": _r("ok"), "chezmoi": _r("warn")}
    assert _host_overall(host_cfg, results) == "warn"


def test_error_dominates_warn():
    host_cfg = {"alias": "x", "os": "ubuntu", "checks": []}
    results = {"reachability": _r("ok"), "chezmoi": _r("warn"), "apt": _r("error")}
    assert _host_overall(host_cfg, results) == "error"


def test_unexpected_unreachable_is_unreachable():
    host_cfg = {"alias": "x", "os": "macos", "checks": []}
    results = {"reachability": _r("unreachable"), "chezmoi": _r("unreachable")}
    assert _host_overall(host_cfg, results) == "unreachable"


def test_expected_unreachable_is_warn():
    host_cfg = {"alias": "x", "os": "macos", "checks": [], "unreachable_is_expected": True}
    results = {"reachability": _r("unreachable"), "chezmoi": _r("unreachable")}
    assert _host_overall(host_cfg, results) == "warn"


def test_summary_buckets_mutually_exclusive():
    hosts = [
        {"alias": "a", "overall_status": "ok", "checks": {}},
        {"alias": "b", "overall_status": "warn", "checks": {"c": _r("warn", {"pending_remote": 3})}},
        {"alias": "c", "overall_status": "warn", "checks": {"c": _r("unreachable")}},
        {"alias": "d", "overall_status": "unreachable", "checks": {"c": _r("unreachable")}},
        {"alias": "e", "overall_status": "error", "checks": {"c": _r("error")}},
    ]
    s = _summarize(hosts)
    assert s["hosts_total"] == 5
    assert s["hosts_ok"] == 1
    assert s["hosts_warn"] == 2
    assert s["hosts_error"] == 1
    assert s["hosts_unreachable"] == 1
    assert s["updates_pending_total"] == 3
