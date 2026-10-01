"""Value conversion in the SNMP layer."""

from __future__ import annotations

from pyasn1.type import univ
from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    UsmUserData,
    usmAesCfb128Protocol,
    usmHMACSHAAuthProtocol,
    usmNoAuthProtocol,
    usmNoPrivProtocol,
)
from pysnmp.proto import rfc1902, rfc1905

from custom_components.hp2530.snmp import SnmpCredentials, _auth_data, _plain


def test_plain_values() -> None:
    assert _plain(rfc1902.Integer32(5)) == 5
    assert _plain(rfc1902.Counter64(2**40)) == 2**40
    assert _plain(rfc1902.TimeTicks(840768515)) == 840768515
    assert _plain(rfc1902.OctetString(b"Test Switch")) == b"Test Switch"
    assert _plain(rfc1902.IpAddress("192.0.2.1")) == bytes([192, 0, 2, 1])


def test_plain_oid_of_the_base_type() -> None:
    # A decoded sysObjectID arrives as pyasn1's ObjectIdentifier, not pysnmp's
    # subclass. Checking for the subclass silently dropped it.
    assert _plain(univ.ObjectIdentifier("1.3.6.1.4.1.11.2.3.7.11.136")) == (
        "1.3.6.1.4.1.11.2.3.7.11.136"
    )


def test_plain_exceptions_are_none() -> None:
    assert _plain(rfc1905.NoSuchObject("")) is None
    assert _plain(rfc1905.NoSuchInstance("")) is None
    assert _plain(rfc1905.EndOfMibView("")) is None


def test_v2c_auth() -> None:
    assert isinstance(_auth_data(SnmpCredentials(host="x")), CommunityData)


def test_v3_auth_and_privacy() -> None:
    auth = _auth_data(
        SnmpCredentials(
            host="x",
            version="3",
            username="ha",
            auth_protocol="sha",
            auth_key="authpass1",
            priv_protocol="aes",
            priv_key="privpass1",
        )
    )
    assert isinstance(auth, UsmUserData)
    assert auth.authentication_protocol == usmHMACSHAAuthProtocol
    assert auth.privacy_protocol == usmAesCfb128Protocol


def test_v3_without_auth_has_no_privacy() -> None:
    # USM cannot encrypt without authenticating
    auth = _auth_data(
        SnmpCredentials(host="x", version="3", username="ha", priv_protocol="aes", priv_key="12345678")
    )
    assert auth.authentication_protocol == usmNoAuthProtocol
    assert auth.privacy_protocol == usmNoPrivProtocol
