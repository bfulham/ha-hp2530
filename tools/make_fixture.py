#!/usr/bin/env python3
"""Build a sanitised test fixture from a switch, or from snmpwalk output.

From saved `snmpwalk -v2c -c <community> -On <host> <oid>` output:

    python3 tools/make_fixture.py --out tests/fixtures/j9772a.json dump/*.txt

Straight from a switch (read-only; needs pysnmp):

    python3 tools/make_fixture.py --out tests/fixtures/j9773a.json --host 192.0.2.10

Only the OIDs the integration reads are kept, and the identifying ones are
replaced: the system name, port descriptions, LLDP neighbour names and
addresses, the serial number and the base MAC address. Check the result
before publishing it anyway.

Fixture values: an int is an integer of any SNMP type, a str is a text OCTET
STRING, {"hex": ...} is a binary one, {"oid": ...} an OBJECT IDENTIFIER.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "hp2530"))

import data as d  # noqa: E402

SCALARS = (*d.STANDARD_SCALARS, *d.HP_SCALARS, d.BRIDGE_ADDRESS)
WALKS = (*d.STANDARD_WALKS, *d.HP_WALKS, d.ENT_CLASS, d.ENT_SERIAL)

_LINE = re.compile(r"^\.?(\d+(?:\.\d+)+) = (?:([A-Za-z0-9 -]+): ?)?(.*)$")


def _parse_value(kind: str | None, raw: str):
    raw = raw.rstrip("\n")
    if kind is None:  # `= ""`
        return raw.strip('"')
    kind = kind.strip()
    if kind in ("INTEGER", "Gauge32", "Counter32", "Counter64", "Unsigned32"):
        match = re.search(r"\((-?\d+)\)\s*$", raw) or re.match(r"^\s*(-?\d+)", raw)
        return int(match.group(1)) if match else None
    if kind == "Timeticks":
        match = re.match(r"^\((\d+)\)", raw)
        return int(match.group(1)) if match else None
    if kind == "OID":
        return {"oid": raw.strip().lstrip(".")}
    if kind == "Hex-STRING":
        return {"hex": raw.replace(" ", "").replace("\n", "").lower()}
    if kind == "STRING":
        text = raw
        if text.startswith('"') and text.endswith('"') and len(text) >= 2:
            text = text[1:-1]
        return text
    if kind == "IpAddress":
        return {"hex": "".join(f"{int(o):02x}" for o in raw.strip().split("."))}
    return None


def read_snmpwalk(paths: list[Path]) -> dict[str, object]:
    out: dict[str, object] = {}
    for path in paths:
        current: tuple[str, str | None, str] | None = None
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in [*lines, None]:
            match = _LINE.match(line) if line is not None else None
            if line is not None and match is None and current is not None:
                current = (current[0], current[1], current[2] + "\n" + line)
                continue
            if current is not None:
                value = _parse_value(current[1], current[2])
                if value is not None:
                    out[current[0]] = value
            current = (match.group(1), match.group(2), match.group(3)) if match else None
    return out


async def read_live(host: str, community: str, port: int) -> dict[str, object]:
    import snmp

    client = snmp.SnmpClient(snmp.SnmpCredentials(host=host, port=port, community=community))
    out: dict[str, object] = {}

    def encode(value):
        if isinstance(value, bytes):
            try:
                text = value.decode("utf-8")
            except UnicodeDecodeError:
                return {"hex": value.hex()}
            return text if text.isprintable() or not text else {"hex": value.hex()}
        if isinstance(value, str):
            return {"oid": value}
        return value

    try:
        for oid, value in (await client.get(list(SCALARS))).items():
            out[oid] = encode(value)
        for base in WALKS:
            for suffix, value in (await client.walk(base)).items():
                out[f"{base}.{suffix}"] = encode(value)
    finally:
        client.close()
    return out


def keep(oid: str) -> bool:
    return oid in SCALARS or any(oid.startswith(base + ".") for base in WALKS)


def sanitise(values: dict[str, object]) -> dict[str, object]:
    out = {oid: value for oid, value in values.items() if keep(oid)}
    if d.SYS_NAME in out:
        out[d.SYS_NAME] = "Test Switch"
    if d.BRIDGE_ADDRESS in out:
        out[d.BRIDGE_ADDRESS] = {"hex": "020000000000"}

    for oid, value in list(out.items()):
        if oid.startswith(d.IF_ALIAS + ".") and value:
            out[oid] = f"Alias {oid.rsplit('.', 1)[1]}"
        elif oid.startswith(d.ENT_SERIAL + ".") and value:
            out[oid] = "SG00000000"

    # LLDP: index is <column>.<timemark>.<local port>.<remote index>
    prefix = d.LLDP_REM + "."
    neighbours: dict[str, int] = {}
    for oid in sorted(o for o in out if o.startswith(prefix)):
        column, rest = oid[len(prefix):].split(".", 1)
        n = neighbours.setdefault(rest, len(neighbours) + 1)
        subtype = out.get(f"{prefix}{d.LLDP_CHASSIS_SUBTYPE}.{rest}")
        port_subtype = out.get(f"{prefix}6.{rest}")
        if column == d.LLDP_CHASSIS_ID:
            out[oid] = (
                {"hex": f"0200000000{n:02x}"} if subtype == 4 else f"neighbor-{n}.example.net"
            )
        elif column == d.LLDP_SYS_NAME and out[oid]:
            out[oid] = f"neighbor-{n}"
        elif column == d.LLDP_PORT_DESCR and out[oid]:
            out[oid] = "uplink"
        elif column == d.LLDP_PORT_ID and port_subtype == 3:
            out[oid] = {"hex": f"0200000001{n:02x}"}
    return dict(sorted(out.items(), key=lambda kv: [int(p) for p in kv[0].split(".")]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dumps", nargs="*", type=Path, help="snmpwalk -On output files")
    parser.add_argument("--host", help="read a switch instead of files")
    parser.add_argument("--community", default="public")
    parser.add_argument("--port", type=int, default=161)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if args.host:
        values = asyncio.run(read_live(args.host, args.community, args.port))
    elif args.dumps:
        values = read_snmpwalk(args.dumps)
    else:
        parser.error("give snmpwalk files or --host")

    fixture = sanitise(values)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(fixture)} values written to {args.out}")


if __name__ == "__main__":
    main()
