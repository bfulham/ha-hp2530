"""Front panel geometry."""

from __future__ import annotations

from custom_components.hp2530.faceplate import geometry

PORTS_48 = list(range(1, 53))
POE_48 = set(range(1, 49))


def _by_id(result: dict) -> dict[str, dict]:
    return {slot["id"]: slot for slot in result["ports"]}


def test_j9772a_matches_the_front_panel() -> None:
    result = geometry("J9772A", "2530-48G-PoEP", PORTS_48, POE_48)
    slots = _by_id(result)
    assert not result["generated"]
    assert (result["width"], result["height"]) == (780, 94)
    # Odd ports on top, even below, column by column
    assert (slots["1"]["x"], slots["1"]["y"]) == (26, 26)
    assert (slots["2"]["x"], slots["2"]["y"]) == (26, 50)
    assert slots["3"]["x"] == 52
    # Blocks of twelve with a wider gap between them
    assert slots["11"]["x"] == 156
    assert slots["13"]["x"] == 156 + 22 + 14
    assert slots["48"]["y"] == 50
    # Four SFP cages to the right: 49 and 51 on top, 50 and 52 below
    assert {n: slots[n]["kind"] for n in ("49", "50", "51", "52")} == dict.fromkeys(
        ("49", "50", "51", "52"), "sfp"
    )
    assert (slots["49"]["x"], slots["49"]["y"]) == (690, 26)
    assert (slots["50"]["x"], slots["50"]["y"]) == (690, 50)
    assert (slots["51"]["x"], slots["51"]["y"]) == (724, 26)
    assert slots["5"]["poe"] and not slots["49"]["poe"]


def test_unknown_model_draws_every_port_as_copper() -> None:
    result = geometry(None, None, list(range(1, 11)), set())
    assert result["generated"]
    assert {slot["kind"] for slot in result["ports"]} == {"rj45"}
    assert len(result["ports"]) == 10


def test_ports_that_do_not_fit_the_sku_fall_back() -> None:
    result = geometry("J9772A", "2530-48G-PoEP", list(range(1, 29)), set())
    assert result["generated"]
    assert all(slot["kind"] == "rj45" for slot in result["ports"])
