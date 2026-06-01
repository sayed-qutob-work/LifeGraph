"""Property-based test for the loopback guard classification (Property 1).

**Validates: Requirements 1.4**

For any network target address, the loopback guard SHALL permit the connection
if and only if the address resolves to a loopback address, and SHALL block every
non-loopback target without transmitting data.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from lifegraph.ollama_client import (
    ExternalConnectionError,
    _is_loopback,
    verify_loopback,
)


# ---------------------------------------------------------------------------
# Strategies for generating IP addresses
# ---------------------------------------------------------------------------

# IPv4 loopback: 127.0.0.0/8 (first octet is 127)
ipv4_loopback_st = st.tuples(
    st.just(127),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}.{t[3]}")

# IPv4 non-loopback: first octet is NOT 127 (and is valid 1-255 for first octet)
ipv4_non_loopback_st = st.tuples(
    st.integers(min_value=1, max_value=255).filter(lambda x: x != 127),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}.{t[3]}")

# IPv6 loopback: only ::1
ipv6_loopback_st = st.just("::1")

# IPv6 non-loopback: generate valid IPv6 addresses that are not ::1
# Use a strategy that generates 8 groups of 16-bit hex values, excluding all-zero-except-last-is-1
ipv6_non_loopback_st = st.tuples(
    st.integers(min_value=0, max_value=0xFFFF),
    st.integers(min_value=0, max_value=0xFFFF),
    st.integers(min_value=0, max_value=0xFFFF),
    st.integers(min_value=0, max_value=0xFFFF),
    st.integers(min_value=0, max_value=0xFFFF),
    st.integers(min_value=0, max_value=0xFFFF),
    st.integers(min_value=0, max_value=0xFFFF),
    st.integers(min_value=0, max_value=0xFFFF),
).filter(
    # Exclude ::1 which is (0,0,0,0,0,0,0,1)
    lambda t: not (t[0] == 0 and t[1] == 0 and t[2] == 0 and t[3] == 0
                   and t[4] == 0 and t[5] == 0 and t[6] == 0 and t[7] == 1)
).map(
    lambda t: ":".join(f"{g:x}" for g in t)
)

# Combined strategies
loopback_address_st = st.one_of(ipv4_loopback_st, ipv6_loopback_st)
non_loopback_address_st = st.one_of(ipv4_non_loopback_st, ipv6_non_loopback_st)
any_valid_address_st = st.one_of(loopback_address_st, non_loopback_address_st)


# ---------------------------------------------------------------------------
# Property test: _is_loopback classification
# ---------------------------------------------------------------------------


@settings(max_examples=20)
@given(address=loopback_address_st)
def test_is_loopback_accepts_all_loopback_addresses(address: str):
    """Property 1 (part A): _is_loopback returns True for any loopback address.

    **Validates: Requirements 1.4**

    For any IPv4 address in 127.0.0.0/8 or IPv6 ::1, _is_loopback SHALL
    classify it as loopback (return True).
    """
    assert _is_loopback(address) is True, (
        f"Expected loopback address {address!r} to be classified as loopback"
    )


@settings(max_examples=20)
@given(address=non_loopback_address_st)
def test_is_loopback_rejects_all_non_loopback_addresses(address: str):
    """Property 1 (part B): _is_loopback returns False for any non-loopback address.

    **Validates: Requirements 1.4**

    For any IPv4 address outside 127.0.0.0/8 or any IPv6 address other than ::1,
    _is_loopback SHALL classify it as non-loopback (return False).
    """
    assert _is_loopback(address) is False, (
        f"Expected non-loopback address {address!r} to be classified as non-loopback"
    )


# ---------------------------------------------------------------------------
# Property test: verify_loopback with mocked resolution
# ---------------------------------------------------------------------------


@settings(max_examples=20)
@given(address=loopback_address_st)
def test_verify_loopback_permits_loopback_resolved_addresses(address: str):
    """Property 1 (part C): verify_loopback permits when resolved address is loopback.

    **Validates: Requirements 1.4**

    For any hostname that resolves to a loopback address, verify_loopback SHALL
    permit the connection (not raise ExternalConnectionError).
    """
    fake_addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    with patch("lifegraph.ollama_client.socket.getaddrinfo", return_value=fake_addrinfo):
        # Should not raise any exception
        verify_loopback("any-hostname")


@settings(max_examples=20)
@given(address=non_loopback_address_st)
def test_verify_loopback_blocks_non_loopback_resolved_addresses(address: str):
    """Property 1 (part D): verify_loopback blocks when resolved address is non-loopback.

    **Validates: Requirements 1.4**

    For any hostname that resolves to a non-loopback address, verify_loopback SHALL
    block the connection by raising ExternalConnectionError without transmitting data.
    """
    fake_addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    with patch("lifegraph.ollama_client.socket.getaddrinfo", return_value=fake_addrinfo):
        with pytest.raises(ExternalConnectionError) as exc_info:
            verify_loopback("some-external-host")

        # Verify the error contains the resolved address info
        assert exc_info.value.resolved == address
        assert exc_info.value.host == "some-external-host"
