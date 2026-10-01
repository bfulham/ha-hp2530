"""Shared fixtures: a recorded switch that answers like the real one."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hp2530.const import CONF_COMMUNITY, CONF_VERSION, DOMAIN
from custom_components.hp2530.snmp import SnmpError, Value

FIXTURES = Path(__file__).parent / "fixtures"

HP_POE_POWER_PORT5 = "1.3.6.1.4.1.11.2.14.11.1.9.1.1.1.8.1.5"
IF_HC_IN_PORT5 = "1.3.6.1.2.1.31.1.1.1.6.5"


def load_values(name: str) -> dict[str, Value]:
    """A fixture file as the values SnmpClient would return."""

    def decode(value: object) -> Value:
        if isinstance(value, dict):
            return bytes.fromhex(value["hex"]) if "hex" in value else value["oid"]
        if isinstance(value, str):
            return value.encode("utf-8")
        return value  # type: ignore[return-value]

    raw = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return {oid: decode(value) for oid, value in raw.items()}


class Replay:
    """Stands in for SnmpClient. Edit `values` between polls to change state."""

    def __init__(self, values: dict[str, Value]) -> None:
        self.values = values
        self.fail = False
        self.walked: list[str] = []

    async def get(self, oids: list[str]) -> dict[str, Value]:
        if self.fail:
            raise SnmpError("No SNMP response received before timeout")
        return {oid: self.values[oid] for oid in oids if oid in self.values}

    async def walk(self, base: str) -> dict[str, Value]:
        if self.fail:
            raise SnmpError("No SNMP response received before timeout")
        self.walked.append(base)
        prefix = base + "."
        return {
            oid[len(prefix):]: value
            for oid, value in self.values.items()
            if oid.startswith(prefix)
        }

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def replay() -> Replay:
    return Replay(load_values("j9772a.json"))


@pytest.fixture
def mock_switch(replay: Replay) -> Generator[Replay]:
    """Every SnmpClient the integration makes is the replay."""
    with (
        patch("custom_components.hp2530.create_engine", return_value=MagicMock()),
        patch("custom_components.hp2530.SnmpClient", return_value=replay),
        patch("custom_components.hp2530.config_flow.SnmpClient", return_value=replay),
    ):
        yield replay


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Switch",
        unique_id="SG00000000",
        data={
            "host": "192.0.2.10",
            "port": 161,
            CONF_VERSION: "2c",
            CONF_COMMUNITY: "public",
            "serial": "SG00000000",
            "mac": None,
        },
    )
