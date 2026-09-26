package com.example.mintmessagearchive

import android.content.Context
import java.io.DataOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

class ServerClient(private val context: Context) {
    fun upload(zip: java.io.File) {
        val base = Prefs.server(context)
        val token = Prefs.token(context)
        require(base.isNotBlank()) { "Server URL is empty" }
        LocalNetworkValidator.validateServerUrl(base)

        val boundary = "----MintArchive${UUID.randomUUID()}"
        val url = URL("$base/upload")
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = 10_000
            readTimeout = 120_000
            setRequestProperty("Authorization", "Bearer $token")
            setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        }

        DataOutputStream(conn.outputStream).use { out ->
            out.writeBytes("--$boundary\r\n")
            out.writeBytes("Content-Disposition: form-data; name=\"file\"; filename=\"${zip.name}\"\r\n")
            out.writeBytes("Content-Type: application/zip\r\n\r\n")
            zip.inputStream().use { it.copyTo(out) }
            out.writeBytes("\r\n--$boundary--\r\n")
        }

        val code = conn.responseCode
        if (code !in 200..299) {
            throw IllegalStateException("Server returned HTTP $code")
        }
        zip.delete()
    }
}
