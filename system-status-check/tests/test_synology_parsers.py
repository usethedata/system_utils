"""Unit tests for Synology package + OS parsers using captured fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from system_status_check.checks.synology_packages import _parse


FIXTURES = Path(__file__).parent / "fixtures"


def test_synopkg_empty():
    body = (FIXTURES / "synopkg-empty.json").read_text()
    assert _parse(body) == []


def test_synopkg_populated():
    body = (FIXTURES / "synopkg-populated.json").read_text()
    items = _parse(body)
    assert len(items) == 1
    assert items[0]["id"] == "ActiveBackup"
    assert items[0]["name"] == "Active Backup for Business"
    assert items[0]["available_version"] == "3.2.0-25053"
    assert items[0]["beta"] is False


def test_synopkg_rejects_non_array():
    with pytest.raises(ValueError):
        _parse('{"oops": "not a list"}')


def test_synopkg_rejects_malformed_json():
    with pytest.raises(Exception):  # JSONDecodeError subclass
        _parse("not json at all")


def test_synology_os_fixture_matches_expected_token():
    # The fixture captures real clean output with rc=255 marker appended.
    body = (FIXTURES / "synoupgrade-clean.txt").read_text()
    assert "UPGRADE_CHECKNEWDSM" in body
