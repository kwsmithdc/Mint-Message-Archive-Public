package com.example.mintmessagearchive

import java.net.Inet4Address
import java.net.Inet6Address
import java.net.InetAddress
import java.net.URI

/**
 * Enforces the archive's LAN-only data path.
 *
 * A configured archive server may resolve only to private/local addresses.
 * Public Internet destinations are rejected before an archive is opened or
 * uploaded. All resolved addresses must pass so a hostname cannot mix a
 * private address with a public fallback.
 */
object LocalNetworkValidator {

    fun validateServerUrl(server: String) {
        val uri = try {
            URI(server)
        } catch (e: Exception) {
            throw IllegalArgumentException("Invalid archive server URL", e)
        }

        require(uri.scheme.equals("http", ignoreCase = true)) {
            "Archive server must use local HTTP; Internet URLs are not supported"
        }

        val host = uri.host?.trim()?.removePrefix("[")?.removeSuffix("]")
        require(!host.isNullOrBlank()) {
            "Archive server URL must contain a hostname or IP address"
        }

        require(uri.userInfo == null) {
            "Archive server URL must not contain embedded credentials"
        }

        val port = uri.port
        require(port == -1 || port in 1..65535) {
            "Archive server URL contains an invalid port"
        }

        val addresses = try {
            InetAddress.getAllByName(host)
        } catch (e: Exception) {
            throw IllegalArgumentException(
                "Archive server could not be resolved on the local network",
                e
            )
        }

        require(addresses.isNotEmpty()) {
            "Archive server has no resolved addresses"
        }

        addresses.forEach { resolved ->
            require(isLocalAddress(resolved)) {
                "Archive server resolves to a non-local address: ${resolved.hostAddress}"
            }
        }
    }

    private fun isLocalAddress(address: InetAddress): Boolean {
        if (address.isLoopbackAddress) return true

        return when (address) {
            is Inet4Address -> isPrivateIpv4(address.address)
            is Inet6Address -> isPrivateIpv6(address.address)
            else -> false
        }
    }

    private fun isPrivateIpv4(bytes: ByteArray): Boolean {
        if (bytes.size != 4) return false
        val a = bytes[0].toInt() and 0xff
        val b = bytes[1].toInt() and 0xff

        return a == 10 ||
            (a == 172 && b in 16..31) ||
            (a == 192 && b == 168) ||
            (a == 169 && b == 254)
    }

    private fun isPrivateIpv6(bytes: ByteArray): Boolean {
        if (bytes.size != 16) return false

        val first = bytes[0].toInt() and 0xff
        val second = bytes[1].toInt() and 0xff

        val uniqueLocal = (first and 0xfe) == 0xfc
        val linkLocal = first == 0xfe && (second and 0xc0) == 0x80

        return uniqueLocal || linkLocal
    }
}
