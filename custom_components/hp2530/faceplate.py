"""Front panel geometry for the faceplate card.

The card draws whatever the faceplate sensor's attributes describe: a viewbox
and one rectangle per port, keyed by the same port id the port entities carry
in their `port` attribute.

Every 2530 numbers its copper ports column by column in pairs, odd on top and
even below, in blocks of twelve. Where the SKU is known the trailing ports are
drawn as SFP cages to the right. Only the J9772A layout is checked against a
photo of the panel; the other rows of LAYOUTS come from HP's data sheets.
"""

from __future__ import annotations

RJ45_W, RJ45_H = 22, 18
SFP_W, SFP_H = 30, 18
GAP_X, GAP_Y = 4, 6
BLOCK_GAP = 14
MARGIN = 26
BLOCK_COLUMNS = 6

# SKU -> (copper ports, SFP ports)
LAYOUTS: dict[str, tuple[int, int]] = {
    "J9772A": (48, 4),  # 2530-48G-PoE+, checked against the front panel
    "J9775A": (48, 4),  # 2530-48G
    "J9773A": (24, 4),  # 2530-24G-PoE+
    "J9776A": (24, 4),  # 2530-24G
}


def _column_x(start: int, column: int, width: int) -> int:
    return start + column * (width + GAP_X)


def geometry(
    sku: str | None, display: str | None, ports: list[int], poe_ports: set[int]
) -> dict:
    """Geometry for the card. `ports` are port numbers, ascending."""
    copper_count, sfp_count = LAYOUTS.get(sku or "", (len(ports), 0))
    known = sku in LAYOUTS and ports == list(range(1, copper_count + sfp_count + 1))
    if not known:
        # Unknown hardware, or ports that do not match what the SKU should
        # have: draw every port as copper in the usual blocks of twelve,
        # rather than put an SFP cage where there is none.
        copper_count, sfp_count = len(ports), 0

    laid_out: list[dict] = []
    x = MARGIN
    copper = ports[:copper_count]
    for block_start in range(0, len(copper), BLOCK_COLUMNS * 2):
        block = copper[block_start : block_start + BLOCK_COLUMNS * 2]
        columns = (len(block) + 1) // 2
        for offset, number in enumerate(block):
            laid_out.append(
                _slot(number, "rj45", _column_x(x, offset // 2, RJ45_W), offset % 2, poe_ports)
            )
        x += columns * RJ45_W + (columns - 1) * GAP_X + BLOCK_GAP

    sfp = ports[copper_count:]
    if sfp:
        columns = (len(sfp) + 1) // 2
        for offset, number in enumerate(sfp):
            laid_out.append(
                _slot(number, "sfp", _column_x(x, offset // 2, SFP_W), offset % 2, poe_ports)
            )
        x += columns * SFP_W + (columns - 1) * GAP_X + BLOCK_GAP

    width = x - BLOCK_GAP + MARGIN if laid_out else 0
    height = 2 * MARGIN + 2 * RJ45_H + GAP_Y
    return {
        "model": sku,
        "display": display,
        "width": width,
        "height": height,
        "viewbox": f"0 0 {width} {height}",
        "generated": not known,
        "ports": laid_out,
    }


def _slot(number: int, kind: str, x: int, row: int, poe_ports: set[int]) -> dict:
    return {
        "id": str(number),
        "label": str(number),
        "kind": kind,
        "poe": number in poe_ports,
        "x": x,
        "y": MARGIN + row * (RJ45_H + GAP_Y),
        "w": SFP_W if kind == "sfp" else RJ45_W,
        "h": SFP_H if kind == "sfp" else RJ45_H,
    }
