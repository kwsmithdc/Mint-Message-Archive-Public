package com.example.mintmessagearchive

import org.junit.Test

class LocalNetworkValidatorTest {

    @Test
    fun loopbackAndPrivateIpv4AddressesAreAccepted() {
        listOf(
            "http://127.0.0.1:8765",
            "http://10.0.0.5:8765",
            "http://172.16.0.5:8765",
            "http://172.31.255.254:8765",
            "http://192.168.1.50:8765",
            "http://169.254.1.10:8765",
        ).forEach(LocalNetworkValidator::validateServerUrl)
    }

    @Test
    fun privateIpv6AddressesAreAccepted() {
        listOf(
            "http://[fd00::1]:8765",
            "http://[fe80::1]:8765",
        ).forEach(LocalNetworkValidator::validateServerUrl)
    }

    @Test
    fun publicIpv4AddressesAreRejected() {
        listOf(
            "http://8.8.8.8:8765",
            "http://203.0.113.1:8765",
            "http://1.1.1.1:8765",
        ).forEach { url ->
            assertRejects(url)
        }
    }

    @Test
    fun publicIpv6AddressesAreRejected() {
        assertRejects("http://[2001:4860:4860::8888]:8765")
    }

    @Test
    fun httpsIsRejected() {
        assertRejects("https://192.168.1.50:8765")
    }

    @Test
    fun embeddedCredentialsAreRejected() {
        assertRejects("http://archive:test@192.168.1.50:8765")
    }

    @Test
    fun invalidPortsAreRejected() {
        assertRejects("http://192.168.1.50:0")
        assertRejects("http://192.168.1.50:65536")
    }

    @Test
    fun missingHostIsRejected() {
        assertRejects("http:///8765")
    }

    private fun assertRejects(url: String) {
        try {
            LocalNetworkValidator.validateServerUrl(url)
            throw AssertionError("Expected rejection for $url")
        } catch (_: IllegalArgumentException) {
            // Expected.
        }
    }
}
