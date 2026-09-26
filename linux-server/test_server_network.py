#!/usr/bin/env python3

import ipaddress
import unittest

from server import is_local_client


class LocalClientSecurityTests(unittest.TestCase):
    def assert_allowed(self, address):
        self.assertTrue(
            is_local_client(address),
            f"expected local address to be allowed: {address}",
        )

    def assert_rejected(self, address):
        self.assertFalse(
            is_local_client(address),
            f"expected non-local address to be rejected: {address}",
        )

    def test_loopback_ipv4_and_ipv6_are_allowed(self):
        self.assert_allowed("127.0.0.1")
        self.assert_allowed("127.255.255.254")
        self.assert_allowed("::1")

    def test_rfc1918_ipv4_private_ranges_are_allowed(self):
        for address in (
            "10.0.0.1",
            "10.255.255.254",
            "172.16.0.1",
            "172.31.255.254",
            "192.168.0.1",
            "192.168.255.254",
        ):
            self.assert_allowed(address)

    def test_ipv4_link_local_is_allowed(self):
        self.assert_allowed("169.254.1.1")
        self.assert_allowed("169.254.255.254")

    def test_ipv6_ula_is_allowed(self):
        self.assert_allowed("fc00::1")
        self.assert_allowed("fd12:3456:789a::1")

    def test_ipv6_link_local_is_allowed(self):
        self.assert_allowed("fe80::1")
        self.assert_allowed("fe80::abcd")

    def test_public_ipv4_is_rejected(self):
        for address in (
            "8.8.8.8",
            "1.1.1.1",
            "93.184.216.34",
        ):
            self.assert_rejected(address)

    def test_public_ipv6_is_rejected(self):
        for address in (
            "2001:4860:4860::8888",
            "2606:4700:4700::1111",
            "2001:db8::1",
        ):
            self.assert_rejected(address)

    def test_non_lan_special_ipv4_ranges_are_rejected(self):
        for address in (
            "0.0.0.0",
            "100.64.0.1",
            "192.0.2.1",
            "198.51.100.1",
            "203.0.113.1",
            "224.0.0.1",
            "255.255.255.255",
        ):
            self.assert_rejected(address)

    def test_non_lan_special_ipv6_ranges_are_rejected(self):
        for address in (
            "::",
            "ff02::1",
        ):
            self.assert_rejected(address)

    def test_invalid_addresses_are_rejected(self):
        for address in ("not-an-ip", "", "192.168.1.999"):
            self.assert_rejected(address)


if __name__ == "__main__":
    unittest.main()
