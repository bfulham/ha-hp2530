# HP 2530 Switch for Home Assistant

A Home Assistant integration for HP / Aruba 2530 switches (ArubaOS-Switch, formerly
ProCurve), built around **PoE power and energy**. It polls the switch over SNMP,
read-only, and creates entities from what the switch reports.

- PoE power per port in watts, from the switch's own per-port meter
- **PoE energy per port and in total, in kWh**, ready for the Energy dashboard. The
  integration accumulates it itself, so you don't need a Riemann sum helper per port.
  The total survives restarts.
- PoE status per port (delivering, searching, fault, ...), with PoE class and priority
- Total PoE power, budget and % of budget used
- Link state and speed per port, and receive/transmit rates (off by default)
- CPU, memory, last boot, and the power supply and fan sensors
- What is plugged in: each port's LLDP neighbour, else its description, else "Port N"
- A **faceplate card** that draws the front panel with link speed and PoE state

Tested against a J9772A 2530-48G-PoE+ on YA.15.10. The other 2530 models should
work: ports and PoE are discovered from the switch, not from a model list.

## Install

With [HACS](https://hacs.xyz): add `https://github.com/bfulham/ha-hp2530` as a
custom repository of type *Integration*, install **HP 2530 Switch**, and restart
Home Assistant.

By hand: copy `custom_components/hp2530` into your `config/custom_components/`
directory and restart.

Then go to **Settings → Devices & services → Add integration → HP 2530 Switch**
and enter the switch's address and SNMP settings.

## Switch setup

SNMP must be enabled with read access. For v2c:

```
snmp-server community "public" operator restricted
```

Use your own community name. The integration never writes to the switch. For
v3, create a user with authentication (MD5 or SHA) and, optionally, privacy
(DES or AES-128).

## Entities

| Entity | Notes |
|---|---|
| `binary_sensor.<switch>_port_N_link` | On when the link is up. Attributes: speed, description, LLDP neighbour |
| `sensor.<switch>_port_N_poe_power` | W. Only on PoE ports |
| `sensor.<switch>_port_N_poe_energy` | kWh, `total_increasing`. Only on PoE ports |
| `sensor.<switch>_port_N_poe_status` | Attributes: `power_class` (0-4), `priority`, `enabled` |
| `sensor.<switch>_port_N_receive_rate` / `transmit_rate` | Mbit/s, disabled by default |
| `sensor.<switch>_poe_power` / `poe_energy` | Total across all ports |
| `sensor.<switch>_poe_budget` / `poe_budget_used` | W and % |
| `sensor.<switch>_cpu`, `memory_used`, `last_boot` | Diagnostics |
| `binary_sensor.<switch>_power_supply`, `_fan` | On means a problem |
| `sensor.<switch>_faceplate` | Front panel geometry for the card |

Entity names stay "Port N …", so entity IDs don't change when a neighbour or a
port description changes. Each port entity has a `label` attribute that says
what's plugged in.

Energy is integrated from the power reading at every poll (trapezoidal rule).
Gaps longer than 10 minutes, such as a restart or the switch being unreachable,
aren't counted, so the total errs low rather than inventing power that wasn't
measured.

Ports are discovered when the integration loads. Reload it if the port set
changes.

## Faceplate card

The card is loaded automatically, with no Lovelace resource to add. To use it:

```yaml
type: custom:hp2530-faceplate-card
device: <device id>    # or: faceplate: sensor.my_switch_faceplate
title: Rack switch     # optional
```

Ports are coloured by link speed. An orange dot means PoE is delivering and a
red one means a PoE fault. Hover over a port for its details, or click it to
open the link entity. The 2530-48G-PoE+ layout is drawn from a photo of the
panel, and the 24-port and non-PoE 2530G layouts follow HP's data sheets. Other
hardware gets a generic two-row layout.

The card is adapted from the netviz card in
[gun4as/HP-HA](https://github.com/gun4as/HP-HA) (MIT; its notice is in
`custom_components/hp2530/www/LICENSE.netviz`).

## Development

```bash
pip install -r requirements_test.txt
pytest
```

The tests replay a recorded J9772A (`tests/fixtures/j9772a.json`). To add a fixture
for another model:

```bash
python3 tools/make_fixture.py --host 192.0.2.10 --community public --out tests/fixtures/<sku>.json
```

The tool keeps only the OIDs the integration reads, and replaces names, port
descriptions, LLDP neighbours, the serial number and MAC addresses. Read the
output before you open a pull request anyway.

`custom_components/hp2530/snmp.py` and `data.py` don't import Home Assistant.
`python3 custom_components/hp2530/snmp.py <host> <community>` runs a quick read
on its own.

See [docs/oids.md](docs/oids.md) for every OID read and what was verified on the
hardware.
