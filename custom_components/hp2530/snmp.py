"""Async SNMP client, read-only.

No Home Assistant imports, so it can be run and tested on its own:

    python3 custom_components/hp2530/snmp.py 192.0.2.10 public

Values come back as plain Python: int for every integer type (Integer32,
Counter32/64, Gauge32, TimeTicks), bytes for OCTET STRING, and a dotted str for
an OBJECT IDENTIFIER. The parser works on those, and so does the test replay.

Uses the pysnmp 7.1 that Home Assistant already ships for its own `snmp`
integration (7.1.21 from 2025.9, 7.1.27 from 2026.7), so installing this pulls
in nothing new.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

# pyasn1's base classes rather than pysnmp's rfc1902 ones: a decoded response
# value is often the base type, and an isinstance check on the subclass misses it.
from pyasn1.type.univ import ObjectIdentifier, OctetString
from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    bulk_cmd,
    get_cmd,
    usm3DESEDEPrivProtocol,
    usmAesCfb128Protocol,
    usmAesCfb192Protocol,
    usmAesCfb256Protocol,
    usmDESPrivProtocol,
    usmHMAC192SHA256AuthProtocol,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
    usmNoAuthProtocol,
    usmNoPrivProtocol,
)
from pysnmp.proto.rfc1905 import EndOfMibView, NoSuchInstance, NoSuchObject
from pysnmp.smi import view

_LOGGER = logging.getLogger(__name__)

type Value = int | bytes | str

AUTH_PROTOCOLS = {
    "none": usmNoAuthProtocol,
    "md5": usmHMACMD5AuthProtocol,
    "sha": usmHMACSHAAuthProtocol,
    "sha256": usmHMAC192SHA256AuthProtocol,
}
PRIV_PROTOCOLS = {
    "none": usmNoPrivProtocol,
    "des": usmDESPrivProtocol,
    "3des": usm3DESEDEPrivProtocol,
    "aes": usmAesCfb128Protocol,
    "aes192": usmAesCfb192Protocol,
    "aes256": usmAesCfb256Protocol,
}

# Rows per GETBULK. A 52-port ifTable column is 67 rows on a 2530 (ports, VLAN
# interfaces and eight loopbacks), so this reads one column in two round trips.
MAX_REPETITIONS = 40
# A walk that has not left its subtree after this many requests is looping.
MAX_CALLS = 200


class SnmpError(Exception):
    """The agent did not answer, refused the request, or returned an error."""


class Reader(Protocol):
    """What the poller needs. SnmpClient is one; the test replay is another."""

    async def walk(self, base: str) -> dict[str, Value]: ...

    async def get(self, oids: list[str]) -> dict[str, Value]: ...


@dataclass(slots=True)
class SnmpCredentials:
    host: str
    port: int = 161
    version: str = "2c"
    community: str = "public"
    username: str = ""
    auth_protocol: str = "none"
    auth_key: str = ""
    priv_protocol: str = "none"
    priv_key: str = ""
    timeout: float = 3.0
    retries: int = 2


def create_engine() -> SnmpEngine:
    """An engine with its MIB modules already loaded.

    Blocking: pysnmp reads its base MIB modules from disk the first time a
    request is built. Home Assistant runs this in the executor so that read
    does not happen in the event loop, the same way its own `snmp` integration
    does.
    """
    engine = SnmpEngine()
    controller = view.MibViewController(
        engine.message_dispatcher.mib_instrum_controller.get_mib_builder()
    )
    engine.cache["mibViewController"] = controller
    controller.mibBuilder.load_modules()
    return engine


def _auth_data(creds: SnmpCredentials) -> CommunityData | UsmUserData:
    if creds.version == "3":
        auth = AUTH_PROTOCOLS.get(creds.auth_protocol, usmNoAuthProtocol)
        priv = PRIV_PROTOCOLS.get(creds.priv_protocol, usmNoPrivProtocol)
        if auth is usmNoAuthProtocol:
            # USM has no privacy without authentication
            priv = usmNoPrivProtocol
        return UsmUserData(
            creds.username,
            authKey=(creds.auth_key or None) if auth is not usmNoAuthProtocol else None,
            privKey=(creds.priv_key or None) if priv is not usmNoPrivProtocol else None,
            authProtocol=auth,
            privProtocol=priv,
        )
    # mpModel 1 = v2c. v1 is left out on purpose: walks use GETBULK, which v1
    # does not have.
    return CommunityData(creds.community, mpModel=1)


def _plain(value: object) -> Value | None:
    """A pysnmp value as int, bytes or dotted str; None for the exceptions."""
    if isinstance(value, (NoSuchObject, NoSuchInstance, EndOfMibView)):
        return None
    if isinstance(value, ObjectIdentifier):
        return ".".join(str(part) for part in value)
    if isinstance(value, OctetString):
        # IpAddress and Opaque are octet strings too
        return bytes(value)
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


def _dotted(oid: object) -> str:
    return ".".join(str(part) for part in oid)  # type: ignore[attr-defined]


class SnmpClient:
    """One agent, for the lifetime of a config entry. Never sends a SET."""

    def __init__(self, creds: SnmpCredentials, engine: SnmpEngine | None = None) -> None:
        self._creds = creds
        self._engine = engine or SnmpEngine()
        self._own_engine = engine is None
        self._auth = _auth_data(creds)
        self._target: UdpTransportTarget | None = None

    async def _transport(self) -> UdpTransportTarget:
        if self._target is None:
            try:
                self._target = await UdpTransportTarget.create(
                    (self._creds.host, self._creds.port),
                    timeout=self._creds.timeout,
                    retries=self._creds.retries,
                )
            except Exception as err:  # noqa: BLE001 - DNS failures arrive in several shapes
                raise SnmpError(f"cannot resolve {self._creds.host}: {err}") from err
        return self._target

    def close(self) -> None:
        if not self._own_engine:
            return  # shared engine, owned by whoever made it
        try:
            self._engine.close_dispatcher()
        except Exception:  # noqa: BLE001 - closing must never raise
            _LOGGER.debug("closing the dispatcher failed", exc_info=True)

    async def get(self, oids: list[str]) -> dict[str, Value]:
        """GET several scalars at once. Missing ones are left out, not None."""
        target = await self._transport()
        err_ind, err_stat, err_idx, binds = await get_cmd(
            self._engine,
            self._auth,
            target,
            ContextData(),
            *(ObjectType(ObjectIdentity(oid)) for oid in oids),
            lookupMib=False,
        )
        if err_ind:
            raise SnmpError(str(err_ind))
        if err_stat:
            raise SnmpError(f"GET failed: {err_stat.prettyPrint()} at varbind {err_idx}")
        out: dict[str, Value] = {}
        for oid, value in binds:
            plain = _plain(value)
            if plain is not None:
                out[_dotted(oid)] = plain
        return out

    async def walk(self, base: str) -> dict[str, Value]:
        """Every instance under `base`, as {index suffix: value}.

        A subtree the agent does not have gives an empty dict, which is how
        the poller tells a PoE switch from one without PoE.
        """
        target = await self._transport()
        prefix = base + "."
        out: dict[str, Value] = {}
        cursor = base
        last: tuple[int, ...] = ()
        for _ in range(MAX_CALLS):
            err_ind, err_stat, err_idx, binds = await bulk_cmd(
                self._engine,
                self._auth,
                target,
                ContextData(),
                0,
                MAX_REPETITIONS,
                ObjectType(ObjectIdentity(cursor)),
                lookupMib=False,
            )
            if err_ind:
                raise SnmpError(str(err_ind))
            if err_stat:
                raise SnmpError(
                    f"walk {base} failed: {err_stat.prettyPrint()} at varbind {err_idx}"
                )
            if not binds:
                return out
            for oid, value in binds:
                numeric = _dotted(oid)
                if not numeric.startswith(prefix) or isinstance(value, EndOfMibView):
                    return out
                parts = tuple(oid)
                if parts <= last:
                    _LOGGER.debug("%s: agent returned a non-increasing OID", base)
                    return out
                last = parts
                plain = _plain(value)
                if plain is not None:
                    out[numeric[len(prefix):]] = plain
                cursor = numeric
        _LOGGER.warning("%s: walk stopped after %d requests", base, MAX_CALLS)
        return out


async def _selftest(host: str, community: str) -> None:
    client = SnmpClient(SnmpCredentials(host=host, community=community))
    try:
        print(await client.get(["1.3.6.1.2.1.1.1.0", "1.3.6.1.2.1.1.2.0", "1.3.6.1.2.1.1.5.0"]))
        rows = await client.walk("1.3.6.1.2.1.105.1.3.1.1")
        print(f"pethMainPseTable: {rows}")
    finally:
        client.close()


if __name__ == "__main__":
    import sys

    asyncio.run(_selftest(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "public"))
