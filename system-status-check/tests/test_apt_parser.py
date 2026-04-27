"""Unit tests for apt parser helpers, using captured fixtures."""

from __future__ import annotations

from pathlib import Path

from system_status_check.checks.apt import (
    _parse_deferred_packages,
    _parse_refresh_header,
    _parse_upgradable_block,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _simulate_combined(refresh_rc: int, stamp_age: int, upgradable_body: str) -> str:
    return (
        f"##APT-REFRESH rc={refresh_rc} stamp_age={stamp_age}##\n"
        f"##APT-UPGRADABLE##\n{upgradable_body}"
    )


def test_parse_refresh_header_basic():
    stdout = "##APT-REFRESH rc=0 stamp_age=120##\n##APT-UPGRADABLE##\nListing...\n"
    rc, age, err = _parse_refresh_header(stdout)
    assert rc == 0
    assert age == 120
    assert err == ""


def test_parse_refresh_header_with_error():
    stdout = (
        "##APT-REFRESH rc=1 stamp_age=99##\n"
        "##APT-REFRESH-ERR##\nsudo: a password is required\n##END##\n"
        "##APT-UPGRADABLE##\nListing...\n"
    )
    rc, age, err = _parse_refresh_header(stdout)
    assert rc == 1
    assert age == 99
    assert err == "sudo: a password is required"


def test_parse_upgradable_clean():
    body = "Listing...\n"
    assert _parse_upgradable_block(_simulate_combined(0, 0, body)) == []


def test_parse_upgradable_real_fixture_with_updates():
    body = (FIXTURES / "apt-with-updates.txt").read_text()
    items = _parse_upgradable_block(_simulate_combined(0, 0, body))
    assert len(items) >= 1
    # Spot-check one known entry
    by_name = {i["name"]: i for i in items if "name" in i}
    assert "jq" in by_name
    assert by_name["jq"]["candidate_version"].startswith("1.7.1-3ubuntu")
    assert by_name["jq"]["current_version"].startswith("1.7.1-3ubuntu")
    assert by_name["jq"]["arch"] == "amd64"
    assert "noble" in by_name["jq"]["origin"]


def test_parse_upgradable_real_fixture_no_updates():
    body = (FIXTURES / "apt-no-updates.txt").read_text()
    assert _parse_upgradable_block(_simulate_combined(0, 0, body)) == []


def test_parse_deferred_packages_none():
    # No simulate marker at all -> empty set.
    stdout = "##APT-REFRESH rc=0 stamp_age=0##\n##APT-UPGRADABLE##\nListing...\n"
    assert _parse_deferred_packages(stdout) == set()


def test_parse_deferred_packages_real_fixture():
    sim_body = (FIXTURES / "apt-simulate-deferred.txt").read_text()
    stdout = (
        "##APT-REFRESH rc=0 stamp_age=0##\n"
        "##APT-SIMULATE##\n" + sim_body +
        "##APT-UPGRADABLE##\nListing...\n"
    )
    assert _parse_deferred_packages(stdout) == {
        "ubuntu-pro-client",
        "ubuntu-pro-client-l10n",
    }


def test_parse_deferred_packages_multiline():
    # Synthetic multi-line wrap (apt wraps long package lists).
    sim_body = (
        "Calculating upgrade...\n"
        "The following upgrades have been deferred due to phasing:\n"
        "  pkg1 pkg2 pkg3\n"
        "  pkg4 pkg5\n"
        "0 upgraded, 0 newly installed, 0 to remove and 5 not upgraded.\n"
    )
    stdout = (
        "##APT-REFRESH rc=0 stamp_age=0##\n"
        "##APT-SIMULATE##\n" + sim_body +
        "##APT-UPGRADABLE##\nListing...\n"
    )
    assert _parse_deferred_packages(stdout) == {"pkg1", "pkg2", "pkg3", "pkg4", "pkg5"}


def test_parse_deferred_packages_no_phasing_section():
    # apt-get -s upgrade without any deferred packages.
    sim_body = (
        "Reading package lists...\n"
        "Building dependency tree...\n"
        "Calculating upgrade...\n"
        "The following packages will be upgraded:\n"
        "  jq libjq1\n"
        "2 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.\n"
    )
    stdout = (
        "##APT-REFRESH rc=0 stamp_age=0##\n"
        "##APT-SIMULATE##\n" + sim_body +
        "##APT-UPGRADABLE##\nListing...\n"
    )
    assert _parse_deferred_packages(stdout) == set()
