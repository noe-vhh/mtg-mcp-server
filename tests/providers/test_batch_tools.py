"""Tests for batch lookup, collection filtering, richer search, Spellbook limits, deep ping."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from fastmcp import Client

from mtg_mcp_server.providers.scryfall import scryfall_mcp
from mtg_mcp_server.providers.scryfall_bulk import scryfall_bulk_mcp
from mtg_mcp_server.providers.spellbook import spellbook_mcp
from mtg_mcp_server.types import Card

FIXTURES = Path(__file__).parent.parent / "fixtures"
SCRYFALL = "https://api.scryfall.com"
SPELLBOOK = "https://backend.commanderspellbook.com"


def _card(name: str, identity: list[str], type_line: str, text: str, legal: str = "legal") -> Card:
    return Card(
        id=f"id-{name}",
        name=name,
        mana_cost="{1}{B}",
        type_line=type_line,
        oracle_text=text,
        color_identity=identity,
        legalities={"commander": legal},
    )


POOL = {
    "Markov Purifier": _card("Markov Purifier", ["W", "B"], "Creature — Vampire", "Lifelink"),
    "Gifted Aetherborn": _card(
        "Gifted Aetherborn", ["B"], "Creature — Aetherborn Vampire", "Deathtouch, lifelink"
    ),
    "Anje, Maid of Dishonor": _card(
        "Anje, Maid of Dishonor",
        ["B", "R"],
        "Legendary Creature — Vampire",
        "{2}, Sacrifice another creature: Each opponent loses 2 life.",
    ),
    "Banned Thing": _card("Banned Thing", ["B"], "Creature — Vampire", "Flying", legal="banned"),
}


@pytest.fixture
async def bulk_client():
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    mock.start_background_refresh = lambda: None

    async def get_cards(names: list[str]) -> dict[str, Card | None]:
        return {n: POOL.get(n) for n in names}

    mock.get_cards = AsyncMock(side_effect=get_cards)

    async def suggest_names(name: str, n: int = 3) -> list[str]:
        return ["Markov Purifier"] if name == "Markov Purifer" else []

    mock.suggest_names = AsyncMock(side_effect=suggest_names)
    with patch("mtg_mcp_server.providers.scryfall_bulk.ScryfallBulkClient", return_value=mock):
        async with Client(transport=scryfall_bulk_mcp) as c:
            yield c


class TestBulkCardsLookupSuggestions:
    async def test_misses_get_did_you_mean(self, bulk_client: Client):
        result = await bulk_client.call_tool(
            "cards_lookup", {"names": ["Markov Purifer", "Zzzz Nothing"]}
        )
        text = result.content[0].text
        assert "Markov Purifer -> did you mean: Markov Purifier" in text
        assert "Zzzz Nothing" in text
        assert result.structured_content["suggestions"] == {"Markov Purifer": ["Markov Purifier"]}


class TestBulkCardsLookup:
    async def test_batch_returns_text_and_reports_missing(self, bulk_client: Client):
        result = await bulk_client.call_tool(
            "cards_lookup", {"names": ["Markov Purifier", "Not A Card"]}
        )
        text = result.content[0].text
        assert "Found 1 of 2" in text
        assert "CI: WB" in text
        assert "Lifelink" in text
        assert "Not found (1): Not A Card" in text
        assert result.structured_content["not_found"] == ["Not A Card"]

    async def test_empty_names_is_an_error(self, bulk_client: Client):
        result = await bulk_client.call_tool("cards_lookup", {"names": []}, raise_on_error=False)
        assert result.is_error


NAMES = [*POOL, "Typo Card"]


class TestCollectionFilter:
    async def test_identity_filter_excludes_off_colour_and_banned(self, bulk_client: Client):
        result = await bulk_client.call_tool(
            "collection_filter", {"names": NAMES, "color_identity": "B"}
        )
        text = result.content[0].text
        assert "Gifted Aetherborn" in text
        assert "Markov Purifier" not in text  # W/B does not fit mono-B
        assert "Banned Thing" not in text  # not Commander-legal
        assert "Unresolved names (1): Typo Card" in text

    async def test_type_and_text_filters_are_anded(self, bulk_client: Client):
        result = await bulk_client.call_tool(
            "collection_filter",
            {
                "names": NAMES,
                "color_identity": "rakdos",
                "type_contains": ["Vampire"],
                "text_contains": ["sacrifice"],
            },
        )
        cards = result.structured_content["cards"]
        assert [c["name"] for c in cards] == ["Anje, Maid of Dishonor"]

    async def test_bad_identity_is_an_error(self, bulk_client: Client):
        result = await bulk_client.call_tool(
            "collection_filter",
            {"names": ["Markov Purifier"], "color_identity": "purple"},
            raise_on_error=False,
        )
        assert result.is_error


@pytest.fixture
async def scryfall_client():
    async with Client(transport=scryfall_mcp) as c:
        yield c


def _scryfall_card_json(name: str) -> dict:
    return {
        "id": f"id-{name}",
        "object": "card",
        "name": name,
        "mana_cost": "{2}{B}",
        "type_line": "Legendary Creature — Vampire",
        "oracle_text": "Haste",
        "color_identity": ["B"],
        "legalities": {"commander": "legal"},
    }


class TestScryfallCardsCollection:
    @respx.mock
    async def test_batches_in_chunks_of_75(self, scryfall_client: Client):
        names = [f"Card {i}" for i in range(80)]
        route = respx.post(f"{SCRYFALL}/cards/collection").mock(
            side_effect=lambda request: httpx.Response(
                200,
                json={
                    "data": [
                        _scryfall_card_json(i["name"])
                        for i in json.loads(request.content)["identifiers"]
                        if i["name"] != "Card 3"
                    ],
                    "not_found": [{"name": "Card 3"}]
                    if "Card 3" in request.content.decode()
                    else [],
                },
            )
        )
        result = await scryfall_client.call_tool("cards_collection", {"names": names})
        assert route.call_count == 2  # 75 + 5
        text = result.content[0].text
        assert "Found 79 of 80" in text
        assert "Not found (1): Card 3" in text

    async def test_rejects_more_than_150(self, scryfall_client: Client):
        result = await scryfall_client.call_tool(
            "cards_collection", {"names": [f"c{i}" for i in range(151)]}, raise_on_error=False
        )
        assert result.is_error


class TestSearchIncludeText:
    @respx.mock
    async def test_include_text_shows_rules_and_identity(self, scryfall_client: Client):
        respx.get(f"{SCRYFALL}/cards/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "object": "list",
                    "total_cards": 1,
                    "has_more": False,
                    "data": [_scryfall_card_json("Test Vampire")],
                },
            )
        )
        plain = await scryfall_client.call_tool("search_cards", {"query": "t:vampire"})
        rich = await scryfall_client.call_tool(
            "search_cards", {"query": "t:vampire", "include_text": True}
        )
        assert "Haste" not in plain.content[0].text
        assert "Haste" in rich.content[0].text
        assert "CI: B" in rich.content[0].text


@pytest.fixture
async def spellbook_client():
    async with Client(transport=spellbook_mcp) as c:
        yield c


class TestDecklistCombosLimits:
    @respx.mock
    async def test_names_missing_cards_and_sorts_fewest_first(self, spellbook_client: Client):
        fixture = json.loads((FIXTURES / "spellbook" / "find_my_combos_response.json").read_text())
        respx.post(f"{SPELLBOOK}/find-my-combos").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        result = await spellbook_client.call_tool(
            "find_decklist_combos",
            {"commanders": ["Muldrotha, the Gravetide"], "decklist": ["Sol Ring"]},
        )
        text = result.content[0].text
        assert "Missing (" in text
        sc = result.structured_content
        counts = [len(c["missing"]) for c in sc["almost_included"]]
        assert counts == sorted(counts)
        assert all("Sol Ring" not in c["missing"] for c in sc["almost_included"])

    @respx.mock
    async def test_limit_and_max_missing(self, spellbook_client: Client):
        fixture = json.loads((FIXTURES / "spellbook" / "find_my_combos_response.json").read_text())
        respx.post(f"{SPELLBOOK}/find-my-combos").mock(
            return_value=httpx.Response(200, json=fixture)
        )
        limited = await spellbook_client.call_tool(
            "find_decklist_combos",
            {"commanders": ["X"], "decklist": ["Sol Ring"], "limit": 1},
        )
        assert len(limited.structured_content["almost_included"]) <= 1
        none = await spellbook_client.call_tool(
            "find_decklist_combos",
            {"commanders": ["X"], "decklist": ["Sol Ring"], "max_missing": 0},
        )
        assert none.structured_content["almost_included"] == []


class TestDeepPing:
    async def test_plain_ping_unchanged(self):
        from mtg_mcp_server.server import mcp

        async with Client(transport=mcp) as c:
            assert (await c.call_tool("ping", {})).content[0].text == "pong"

    async def test_deep_health_reports_bulk_ok(self):
        from mtg_mcp_server.server import _deep_health

        fake = AsyncMock()
        fake.status = lambda: {"loaded": True, "card_count": 30000, "age_seconds": 5}
        with patch("mtg_mcp_server.providers.scryfall_bulk._client", fake):
            text = await _deep_health(True)
        assert text == "bulk: OK (30000 cards, loaded 5s ago)"

    async def test_deep_health_reports_bulk_failure(self):
        from mtg_mcp_server.server import _deep_health

        fake = AsyncMock()
        fake.ensure_loaded = AsyncMock(side_effect=RuntimeError("download blocked"))
        with patch("mtg_mcp_server.providers.scryfall_bulk._client", fake):
            text = await _deep_health(True)
        assert text == "bulk: FAILED (download blocked)"

    async def test_deep_health_disabled(self):
        from mtg_mcp_server.server import _deep_health

        assert await _deep_health(False) == "bulk: disabled"
