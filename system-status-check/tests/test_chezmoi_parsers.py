"""Unit tests for chezmoi parser helpers."""

from __future__ import annotations

import pytest

from system_status_check.checks.chezmoi import (
    _parse_git_status,
    _parse_status,
    _split_sections,
)


def test_parse_status_empty():
    assert _parse_status("") == []


def test_parse_status_basic():
    body = "MM dot_zshrc\n A dot_config/foo/bar\nD  dot_old"
    items = _parse_status(body)
    assert items == [
        {"source_state": "M", "target_state": "M", "path": "dot_zshrc"},
        {"source_state": " ", "target_state": "A", "path": "dot_config/foo/bar"},
        {"source_state": "D", "target_state": " ", "path": "dot_old"},
    ]


def test_parse_git_status_clean():
    body = "## main...origin/main"
    parsed = _parse_git_status(body)
    assert parsed["ahead"] == 0
    assert parsed["behind"] == 0
    assert parsed["entries"] == []


def test_parse_git_status_ahead_behind_dirty():
    body = (
        "## main...origin/main [ahead 2, behind 1]\n"
        " M dot_zshrc\n"
        "?? new_file.txt\n"
    )
    parsed = _parse_git_status(body)
    assert parsed["ahead"] == 2
    assert parsed["behind"] == 1
    assert parsed["entries"] == [
        {"git_status": " M", "path": "dot_zshrc"},
        {"git_status": "??", "path": "new_file.txt"},
    ]


def test_split_sections_roundtrip():
    stdout = (
        "\n##CMCHK-BEGIN-STATUS##\n"
        "MM a\n"
        "\n##CMCHK-END-STATUS rc=0##\n"
        "\n##CMCHK-BEGIN-GITSTATUS##\n"
        "## main...origin/main\n"
        "\n##CMCHK-END-GITSTATUS rc=0##\n"
    )
    sections = _split_sections(stdout)
    assert set(sections.keys()) == {"STATUS", "GITSTATUS"}
    assert sections["STATUS"] == ("MM a", 0)
    assert sections["GITSTATUS"] == ("## main...origin/main", 0)


def test_split_sections_captures_nonzero_rc():
    stdout = (
        "##CMCHK-BEGIN-STATUS##\n"
        "oops\n"
        "##CMCHK-END-STATUS rc=1##\n"
    )
    sections = _split_sections(stdout)
    assert sections["STATUS"][1] == 1
