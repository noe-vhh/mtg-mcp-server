"""Tests for Commander Spellbook bracket-tag descriptions."""

from __future__ import annotations

import pytest

from mtg_mcp_server.utils.bracket import describe_bracket_tag


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("R", "R (Ruthless: competitive, bracket 4+)"),
        ("S", "S (Spicy: probably bracket 3 or 4)"),
        ("P", "P (Powerful: bracket 3+)"),
        ("O", "O (Oddball: probably bracket 2 or 3)"),
        ("C", "C (Core: bracket 2+)"),
        ("E", "E (Exhibition: any bracket, 1+)"),
        ("B", "B (Banned: not legal in Commander)"),
    ],
)
def test_known_tags_are_described(tag: str, expected: str) -> None:
    assert describe_bracket_tag(tag) == expected


def test_lowercase_is_accepted() -> None:
    assert describe_bracket_tag("p") == "P (Powerful: bracket 3+)"


def test_unknown_tag_is_returned_unchanged() -> None:
    assert describe_bracket_tag("ZZ") == "ZZ"


@pytest.mark.parametrize("tag", [None, ""])
def test_missing_tag_is_unknown(tag: str | None) -> None:
    assert describe_bracket_tag(tag) == "Unknown"
