"""Unit tests for brew parser using captured fixtures."""

from __future__ import annotations

from pathlib import Path

from system_status_check.checks.brew import _parse


FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_empty_string_is_empty():
    assert _parse("", []) == ([], 0)


def test_parse_empty_json_shape():
    items, flagged = _parse('{"formulae": [], "casks": []}', [])
    assert items == []
    assert flagged == 0


def test_parse_real_superbear_fixture():
    body = (FIXTURES / "brew-superbear.json").read_text()
    items, flagged = _parse(body, [])
    assert len(items) == 15
    assert flagged == 0
    names = {i["name"] for i in items}
    assert "deno" in names
    deno = next(i for i in items if i["name"] == "deno")
    assert deno["type"] == "formula"
    assert deno["installed_versions"] == ["2.7.12"]
    assert deno["current_version"] == "2.7.13"
    assert deno["pinned"] is False
    assert "flagged" not in deno


def test_parse_flagged_pattern_matches():
    # Construct a minimal doc that includes a name matching a pattern.
    body = (
        '{"formulae": ['
        '{"name":"python@3.12","installed_versions":["3.12.1"],"current_version":"3.12.2","pinned":false},'
        '{"name":"cmake","installed_versions":["3.29"],"current_version":"3.30","pinned":false}'
        '], "casks": []}'
    )
    items, flagged = _parse(body, ["python@*"])
    assert flagged == 1
    py = next(i for i in items if i["name"] == "python@3.12")
    assert py.get("flagged") is True
    cm = next(i for i in items if i["name"] == "cmake")
    assert cm.get("flagged") is None
