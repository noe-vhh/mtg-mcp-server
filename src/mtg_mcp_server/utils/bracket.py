"""Human-readable descriptions of Commander Spellbook bracket tags.

Spellbook labels every combo (and every estimated deck) with a one-letter
bracket tag. The meanings below come from Commander Spellbook's own syntax
guide (https://commanderspellbook.com/syntax-guide/, "Bracket" section). The
tags are a qualitative guideline, not a strict bracket classification.
"""

from __future__ import annotations

# tag -> (name, meaning)
_BRACKET_TAGS: dict[str, tuple[str, str]] = {
    "R": ("Ruthless", "competitive, bracket 4+"),
    "S": ("Spicy", "probably bracket 3 or 4"),
    "P": ("Powerful", "bracket 3+"),
    "O": ("Oddball", "probably bracket 2 or 3"),
    "C": ("Core", "bracket 2+"),
    "E": ("Exhibition", "any bracket, 1+"),
    "B": ("Banned", "not legal in Commander"),
}


def describe_bracket_tag(tag: str | None) -> str:
    """Return ``"P (Powerful: bracket 3+)"`` for a Spellbook bracket tag.

    Unknown tags are returned unchanged so new Spellbook tags still show up;
    a missing tag is reported as ``"Unknown"``.
    """
    if not tag:
        return "Unknown"
    entry = _BRACKET_TAGS.get(tag.upper())
    if entry is None:
        return tag
    name, meaning = entry
    return f"{tag.upper()} ({name}: {meaning})"
