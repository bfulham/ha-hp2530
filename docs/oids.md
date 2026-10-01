# OIDs read, and what was verified

Everything here was checked against a J9772A 2530-48G-PoE+ on firmware
YA.15.10.0003 (ROM YA.15.09), sysObjectID `1.3.6.1.4.1.11.2.3.7.11.136`. Column
meanings come from the MIBs (HP-ICF-POE-MIB, NETSWITCH-MIB, HP-ICF-CHASSIS)
unless noted. Numeric OIDs throughout, so no MIB files are needed.

Per-port tables are indexed by port number, which on the 2530 is also the
ifIndex: 1-48 copper, 49-52 SFP. The PoE tables put a group in front: `1.<port>`.

## Interfaces

| ifIndex | What |
|---|---|
| 1-52 | Ports, ifType 6 (ethernetCsmacd) |
| 102, 111, ... | VLAN interfaces, ifType 53 (propVirtual) |
| 12516-12523 | `lo0`-`lo7`, ifType 24 (softwareLoopback) |

Ports are found by ifType rather than by index range.

| OID | Meaning |
|---|---|
| `1.3.6.1.2.1.2.2.1.3` | ifType |
| `1.3.6.1.2.1.2.2.1.7` / `.8` | ifAdminStatus / ifOperStatus |
| `1.3.6.1.2.1.31.1.1.1.1` | ifName (just the port number) |
| `1.3.6.1.2.1.31.1.1.1.6` / `.10` | ifHCInOctets / ifHCOutOctets |
| `1.3.6.1.2.1.31.1.1.1.15` | ifHighSpeed, Mb/s |
| `1.3.6.1.2.1.31.1.1.1.18` | ifAlias, the port description |

A port that is down still reports a speed of 10 Mb/s in both ifSpeed and
ifHighSpeed, so the integration reports 0 for a down port. ifSpeed also caps at
4.29 Gb/s, so ifHighSpeed is the one read.

## PoE, switch-wide (POWER-ETHERNET-MIB, RFC 3621)

| OID | Meaning |
|---|---|
| `1.3.6.1.2.1.105.1.3.1.1.2.1` | Budget, W (764 on the J9772A) |
| `1.3.6.1.2.1.105.1.3.1.1.3.1` | Oper status |
| `1.3.6.1.2.1.105.1.3.1.1.4.1` | Consumption, **whole watts only** |
| `1.3.6.1.2.1.105.1.3.1.1.5.1` | Usage alert threshold, % |

The total the integration reports is the sum of the per-port meters below,
which is finer than the whole-watt consumption.

## PoE, per port, standard (`1.3.6.1.2.1.105.1.1.1.<col>.1.<port>`)

| Col | Meaning |
|---|---|
| 3 | Admin enable: 1 enabled, 2 disabled |
| 6 | Detection: 1 disabled, 2 searching, 3 delivering, 4 fault, 5 test, 6 otherFault |
| 7 | Priority: 1 critical, 2 high, 3 low |
| 10 | Class: 1 = class 0 ... 5 = class 4 |

The standard MIB has no per-port power.

## PoE, per port, HP (`1.3.6.1.4.1.11.2.14.11.1.9.1.1.1.<col>.1.<port>`)

| Col | MIB name | Observed |
|---|---|---|
| 1 | Current, mA | e.g. 125 |
| 2 | Voltage, 0.1 V | 551 = 55.1 V |
| 3 | Power, mW | Same as col 8 when read together |
| 8 | **ActualPower, mW**, which the integration reads | e.g. 6887 |
| 9 | OperStatus: deny(1)/off(2)/on(3) in the MIB | **This firmware returns the RFC 3621 detection codes instead** (2, 3, 6). Not used; col 6 of the standard table is |
| 10 | PowerMode: enable(1)/disable(2) | |
| 11 | AveragePower ("watts" in the MIB) | Reads as mW. Stays non-zero on ports that have stopped drawing |
| 12 | PeakPower ("watts" in the MIB) | 14875 on every port that has ever drawn power, so not a real peak. Not used |

An earlier capture showed cols 3 and 8 slightly apart. Reading them together
shows they're the same value; the gap came from separate walks.

## System and health

| OID | Meaning |
|---|---|
| `1.3.6.1.2.1.1.1.0` | sysDescr: SKU, model name and firmware are parsed from it |
| `1.3.6.1.2.1.1.2.0` | sysObjectID. HP OIDs are read only under `1.3.6.1.4.1.11` |
| `1.3.6.1.2.1.1.3.0` | sysUpTime |
| `1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0` | CPU % |
| `1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.5.1` / `.6.1` / `.7.1` | Memory total / free / allocated, bytes (hpLocalMem) |
| `1.3.6.1.4.1.11.2.14.11.5.1.1.3.0` / `.4.0` | Firmware / ROM version |
| `1.3.6.1.4.1.11.2.14.11.1.2.6.1` | Chassis sensors: `.4.<row>` status (1 unknown, 2 bad, 3 warning, 4 good, 5 notPresent), `.7.<row>` description. Row 1 "Power Supply Sensor", row 2 "Fan Sensor" |
| `1.3.6.1.2.1.47.1.1.1.1.5` / `.11` | ENTITY-MIB class and serial. The chassis (class 3) is row 1 on a 2530 and 1001 on a 2540; the serial has a trailing space |
| `1.3.6.1.2.1.17.1.1.0` | Bridge base MAC, the fallback unique ID |

## LLDP (`1.0.8802.1.1.2.1.4.1.1.<col>.<timemark>.<local port>.<remote index>`)

Col 4 chassis ID subtype, 5 chassis ID, 7 port ID, 8 port description, 9 system
name, 10 system description. Some access points send their hostname as a
locally assigned chassis ID (subtype 7) and leave the system name empty. The
integration uses that as the neighbour's name.

## Not polled

- `1.3.6.1.4.1.11.2.14.11.5.1.9` is the bridge forwarding table and port
  counters (large, MAC-indexed). It isn't a PoE table.
- `1.3.6.1.4.1.11.2.14.11.1.9.1.6.1.4` reads as the maximum, not the power
  remaining (per netviz, on a 2540). Remaining power is budget minus used.
