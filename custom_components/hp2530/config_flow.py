"""Config flow: address and SNMP credentials, then a test read."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import async_get_engine
from .const import (
    AUTH_PROTOCOLS,
    CONF_AUTH_KEY,
    CONF_AUTH_PROTOCOL,
    CONF_COMMUNITY,
    CONF_PRIV_KEY,
    CONF_PRIV_PROTOCOL,
    CONF_VERSION,
    DEFAULT_COMMUNITY,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    PRIV_PROTOCOLS,
    SNMP_VERSIONS,
)
from .data import Identity, identify
from .snmp import SnmpClient, SnmpCredentials, SnmpError

_LOGGER = logging.getLogger(__name__)

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def credentials(data: dict[str, Any]) -> SnmpCredentials:
    return SnmpCredentials(
        host=data[CONF_HOST],
        port=int(data.get(CONF_PORT, DEFAULT_PORT)),
        version=data.get(CONF_VERSION, "2c"),
        community=data.get(CONF_COMMUNITY, DEFAULT_COMMUNITY),
        username=data.get(CONF_USERNAME, ""),
        auth_protocol=data.get(CONF_AUTH_PROTOCOL, "none"),
        auth_key=data.get(CONF_AUTH_KEY, ""),
        priv_protocol=data.get(CONF_PRIV_PROTOCOL, "none"),
        priv_key=data.get(CONF_PRIV_KEY, ""),
    )


def _connection_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Required(
                CONF_VERSION, default=defaults.get(CONF_VERSION, "2c")
            ): SelectSelector(
                SelectSelectorConfig(
                    options=SNMP_VERSIONS,
                    mode=SelectSelectorMode.LIST,
                    translation_key=CONF_VERSION,
                )
            ),
            vol.Optional(
                CONF_COMMUNITY, default=defaults.get(CONF_COMMUNITY, DEFAULT_COMMUNITY)
            ): _PASSWORD,
        }
    )


def _v3_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(
                CONF_AUTH_PROTOCOL, default=defaults.get(CONF_AUTH_PROTOCOL, "sha")
            ): SelectSelector(
                SelectSelectorConfig(
                    options=AUTH_PROTOCOLS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_AUTH_PROTOCOL,
                )
            ),
            vol.Optional(CONF_AUTH_KEY, default=defaults.get(CONF_AUTH_KEY, "")): _PASSWORD,
            vol.Required(
                CONF_PRIV_PROTOCOL, default=defaults.get(CONF_PRIV_PROTOCOL, "aes")
            ): SelectSelector(
                SelectSelectorConfig(
                    options=PRIV_PROTOCOLS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_PRIV_PROTOCOL,
                )
            ),
            vol.Optional(CONF_PRIV_KEY, default=defaults.get(CONF_PRIV_KEY, "")): _PASSWORD,
        }
    )


def _v3_errors(data: dict[str, Any]) -> dict[str, str]:
    """USM key rules, checked before anything is sent."""
    errors: dict[str, str] = {}
    if data.get(CONF_AUTH_PROTOCOL, "none") != "none" and len(data.get(CONF_AUTH_KEY, "")) < 8:
        errors[CONF_AUTH_KEY] = "key_too_short"
    if data.get(CONF_PRIV_PROTOCOL, "none") != "none":
        if data.get(CONF_AUTH_PROTOCOL, "none") == "none":
            errors[CONF_PRIV_PROTOCOL] = "priv_needs_auth"
        elif len(data.get(CONF_PRIV_KEY, "")) < 8:
            errors[CONF_PRIV_KEY] = "key_too_short"
    return errors


class Hp2530ConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return Hp2530OptionsFlow()

    async def _identify(self) -> tuple[Identity | None, str | None]:
        engine = await async_get_engine(self.hass)
        client = SnmpClient(credentials(self._data), engine)
        try:
            return await identify(client), None
        except SnmpError as err:
            _LOGGER.debug("%s did not answer: %s", self._data[CONF_HOST], err)
            return None, "cannot_connect"
        except Exception:
            _LOGGER.exception("unexpected error talking to %s", self._data[CONF_HOST])
            return None, "unknown"
        finally:
            client.close()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data = {**user_input, CONF_HOST: user_input[CONF_HOST].strip()}
            if self._data[CONF_VERSION] == "3":
                return await self.async_step_v3()
            result, error = await self._finish()
            if result is not None:
                return result
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _connection_schema(self._data), user_input or {}
            ),
            errors=errors,
        )

    async def async_step_v3(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _v3_errors(user_input)
            if not errors:
                self._data |= user_input
                result, error = await self._finish()
                if result is not None:
                    return result
                errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="v3",
            data_schema=self.add_suggested_values_to_schema(
                _v3_schema(self._data), user_input or {}
            ),
            errors=errors,
        )

    async def _finish(self) -> tuple[ConfigFlowResult | None, str | None]:
        identity, error = await self._identify()
        if identity is None:
            return None, error
        data = {**self._data, "serial": identity.serial, "mac": identity.mac}
        if self._data[CONF_VERSION] == "3":
            data.pop(CONF_COMMUNITY, None)
        unique_id = identity.unique_id or f"{self._data[CONF_HOST]}:{self._data[CONF_PORT]}"

        if self.source == "reconfigure":
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_mismatch(reason="wrong_device")
            return (
                self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(), data=data
                ),
                None,
            )

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._data[CONF_HOST]})
        return (
            self.async_create_entry(title=identity.name or self._data[CONF_HOST], data=data),
            None,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address or the credentials of a switch already set up."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data = {**entry.data, **user_input, CONF_HOST: user_input[CONF_HOST].strip()}
            if self._data[CONF_VERSION] == "3":
                return await self.async_step_v3()
            result, error = await self._finish()
            if result is not None:
                return result
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(dict(entry.data)),
            errors=errors,
        )


class Hp2530OptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=5,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
