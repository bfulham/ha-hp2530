"""Constants."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "hp2530"

CONF_VERSION: Final = "snmp_version"
CONF_COMMUNITY: Final = "community"
CONF_AUTH_PROTOCOL: Final = "auth_protocol"
CONF_AUTH_KEY: Final = "auth_key"
CONF_PRIV_PROTOCOL: Final = "priv_protocol"
CONF_PRIV_KEY: Final = "priv_key"

DEFAULT_PORT: Final = 161
DEFAULT_COMMUNITY: Final = "public"
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 300

SNMP_VERSIONS: Final = ["2c", "3"]
AUTH_PROTOCOLS: Final = ["none", "md5", "sha", "sha256"]
PRIV_PROTOCOLS: Final = ["none", "des", "3des", "aes", "aes192", "aes256"]

# Served out of the integration directory, so the card needs no HACS entry or
# Lovelace resource of its own.
CARD_FILENAME: Final = "hp2530-faceplate-card.js"
CARD_URL: Final = f"/{DOMAIN}/{CARD_FILENAME}"
DATA_ENGINE: Final = f"{DOMAIN}_snmp_engine"
DATA_CARD: Final = f"{DOMAIN}_card_registered"
