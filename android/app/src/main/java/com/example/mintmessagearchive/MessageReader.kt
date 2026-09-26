package com.example.mintmessagearchive

import android.content.Context
import android.provider.Telephony
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.HashSet
import java.util.Locale
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

data class ScanResult(
    val smsCount: Int,
    val mmsCount: Int,
    val rcsProbe: String,
    val smsSample: String,
    val mmsSample: String,
    val mmsAttachments: Int,
    val summary: String
)

internal fun extensionForMimeType(contentType: String): String = when (contentType.lowercase(Locale.US)) {
    "image/jpeg" -> ".jpg"
    "image/png" -> ".png"
    "image/gif" -> ".gif"
    "image/webp" -> ".webp"
    "video/mp4" -> ".mp4"
    "audio/mpeg" -> ".mp3"
    "audio/amr" -> ".amr"
    else -> ".bin"
}

internal fun sanitizeAttachmentFilename(filename: String?): String? {
    return filename?.replace(Regex("[^A-Za-z0-9._-]"), "_")?.trim('_')?.take(100)
        ?.takeIf { it.isNotBlank() }
}

internal fun buildAttachmentFilename(
    dateString: String,
    messageId: String,
    partId: String,
    originalName: String?,
    extension: String
): String {
    val suffix = originalName?.let { "-$it" } ?: extension
    return "${dateString}-${messageId}-${partId}${suffix}"
}

internal fun mergeBackupState(
    state: JSONObject,
    pendingSmsIds: JSONArray,
    pendingMmsIds: JSONArray,
    pendingPartIds: JSONArray
) {
    val sms = state.optJSONArray("smsIds") ?: JSONArray()
    val mms = state.optJSONArray("mmsIds") ?: JSONArray()
    val parts = state.optJSONArray("partIds") ?: JSONArray()

    for (i in 0 until pendingSmsIds.length()) {
        val id = pendingSmsIds.getString(i)
        if (!containsJsonValue(sms, id)) sms.put(id)
    }
    for (i in 0 until pendingMmsIds.length()) {
        val id = pendingMmsIds.getString(i)
        if (!containsJsonValue(mms, id)) mms.put(id)
    }
    for (i in 0 until pendingPartIds.length()) {
        val id = pendingPartIds.getString(i)
        if (!containsJsonValue(parts, id)) parts.put(id)
    }

    state.put("smsIds", sms)
    state.put("mmsIds", mms)
    state.put("partIds", parts)
}

private fun containsJsonValue(array: JSONArray, value: String): Boolean {
    for (i in 0 until array.length()) {
        if (array.optString(i) == value) return true
    }
    return false
}

class MessageReader(private val context: Context) {
    private val backupStateFile = File(context.filesDir, "backup-state.json")
    private var pendingSmsIds = JSONArray()
    private var pendingMmsIds = JSONArray()
    private var pendingPartIds = JSONArray()

    fun scan(): ScanResult {
        var smsCount = 0
        var mmsCount = 0
        var smsSample = "SMS sample: none"
        var mmsSample = "MMS sample: none"
        var mmsAttachments = 0

        try {
            context.contentResolver.query(
                Telephony.Sms.CONTENT_URI,
                arrayOf(Telephony.Sms._ID, Telephony.Sms.ADDRESS, Telephony.Sms.BODY,
                    Telephony.Sms.DATE, Telephony.Sms.TYPE, Telephony.Sms.READ),
                null, null, "${Telephony.Sms.DATE} DESC"
            )?.use { cursor ->
                smsCount = cursor.count
                if (cursor.moveToFirst()) {
                    val address = cursor.getString(cursor.getColumnIndexOrThrow(Telephony.Sms.ADDRESS)) ?: ""
                    val body = cursor.getString(cursor.getColumnIndexOrThrow(Telephony.Sms.BODY)) ?: ""
                    smsSample = "Latest SMS: ${address.ifBlank { "(unknown sender)" }} — ${body.replace("\n", " ").take(120)}"
                }
            }
        } catch (e: Exception) {
            smsSample = "SMS scan error: ${e.javaClass.simpleName}: ${e.message}"
        }

        try {
            context.contentResolver.query(
                Telephony.Mms.CONTENT_URI,
                arrayOf(Telephony.Mms._ID, Telephony.Mms.THREAD_ID, Telephony.Mms.DATE,
                    Telephony.Mms.MESSAGE_BOX, Telephony.Mms.SUBJECT),
                null, null, "${Telephony.Mms.DATE} DESC"
            )?.use { cursor ->
                mmsCount = cursor.count
                if (cursor.moveToFirst()) {
                    val id = cursor.getString(cursor.getColumnIndexOrThrow(Telephony.Mms._ID))
                    val threadId = cursor.getString(cursor.getColumnIndexOrThrow(Telephony.Mms.THREAD_ID))
                    val subject = cursor.getString(cursor.getColumnIndexOrThrow(Telephony.Mms.SUBJECT))
                    mmsSample = "Latest MMS: id=$id, thread=$threadId, subject=${subject ?: "(none)"}"
                }
            }
        } catch (e: Exception) {
            mmsSample = "MMS scan error: ${e.javaClass.simpleName}: ${e.message}"
        }

        try {
            context.contentResolver.query(
                Telephony.Mms.Part.CONTENT_URI,
                arrayOf(Telephony.Mms.Part._ID), null, null, null
            )?.use { cursor -> mmsAttachments = cursor.count }
        } catch (_: Exception) {
            mmsAttachments = 0
        }

        val rcsProbe = probeRcsAccess()

        return ScanResult(
            smsCount, mmsCount, rcsProbe, smsSample, mmsSample, mmsAttachments,
            "Scan complete: $smsCount SMS, $mmsCount MMS, $mmsAttachments MMS parts. RCS archival is not available through the public Android message provider."
        )
    }

    /**
     * RCS support is deliberately reported rather than guessed from the
     * mms-sms conversation provider. Android exposes framework IMS/RCS
     * capability APIs, but the RCS message store is not a public application
     * data provider. Treating the legacy conversations provider as RCS would
     * risk silently misclassifying SMS/MMS as RCS.
     */
    private fun probeRcsAccess(): String {
        return try {
            val hasIms = context.packageManager.hasSystemFeature("android.hardware.telephony.ims")
            if (hasIms) {
                "IMS/RCS capability present; RCS message history is not exposed through the public Android message provider"
            } else {
                "No Android IMS/RCS telephony feature reported; RCS message history unavailable"
            }
        } catch (e: Exception) {
            "RCS capability probe unavailable: ${e.javaClass.simpleName}: ${e.message}"
        }
    }

    private fun loadBackupState(): JSONObject {
        if (!backupStateFile.exists()) return JSONObject()
        return try {
            JSONObject(backupStateFile.readText())
        } catch (_: Exception) {
            JSONObject()
        }
    }

    private fun saveBackupState(state: JSONObject) {
        backupStateFile.writeText(state.toString(2))
    }

    fun commitBackupState() {
        val state = loadBackupState()
        mergeBackupState(
            state,
            pendingSmsIds,
            pendingMmsIds,
            pendingPartIds
        )
        saveBackupState(state)

        pendingSmsIds = JSONArray()
        pendingMmsIds = JSONArray()
        pendingPartIds = JSONArray()
    }

    fun exportIncremental(): File {
        val state = loadBackupState()
        val backedUpSms = state.optJSONArray("smsIds") ?: JSONArray()
        val backedUpMms = state.optJSONArray("mmsIds") ?: JSONArray()
        val backedUpParts = state.optJSONArray("partIds") ?: JSONArray()

        val outputDir = File(context.cacheDir, "exports")
        if (!outputDir.exists()) outputDir.mkdirs()
        val outputFile = File(outputDir, "message-archive-${System.currentTimeMillis()}.zip")

        val smsArray = JSONArray()
        val mmsArray = JSONArray()
        val newSmsIds = JSONArray()
        val newMmsIds = JSONArray()
        val newPartIds = JSONArray()

        val backedUpSmsIds = HashSet<String>()
        for (i in 0 until backedUpSms.length()) backedUpSmsIds.add(backedUpSms.getString(i))
        val backedUpMmsIds = HashSet<String>()
        for (i in 0 until backedUpMms.length()) backedUpMmsIds.add(backedUpMms.getString(i))
        val backedUpPartIds = HashSet<String>()
        for (i in 0 until backedUpParts.length()) backedUpPartIds.add(backedUpParts.getString(i))

        val attachmentEntries = mutableListOf<Pair<File, String>>()

        context.contentResolver.query(
            Telephony.Sms.CONTENT_URI,
            arrayOf(Telephony.Sms._ID, Telephony.Sms.THREAD_ID, Telephony.Sms.ADDRESS,
                Telephony.Sms.BODY, Telephony.Sms.DATE, Telephony.Sms.TYPE, Telephony.Sms.READ),
            null, null, "${Telephony.Sms.DATE} ASC"
        )?.use { cursor ->
            val idIndex = cursor.getColumnIndexOrThrow(Telephony.Sms._ID)
            val threadIndex = cursor.getColumnIndexOrThrow(Telephony.Sms.THREAD_ID)
            val addressIndex = cursor.getColumnIndexOrThrow(Telephony.Sms.ADDRESS)
            val bodyIndex = cursor.getColumnIndexOrThrow(Telephony.Sms.BODY)
            val dateIndex = cursor.getColumnIndexOrThrow(Telephony.Sms.DATE)
            val typeIndex = cursor.getColumnIndexOrThrow(Telephony.Sms.TYPE)
            val readIndex = cursor.getColumnIndexOrThrow(Telephony.Sms.READ)

            while (cursor.moveToNext()) {
                val smsId = cursor.getString(idIndex)
                if (backedUpSmsIds.contains(smsId)) continue

                smsArray.put(JSONObject().apply {
                    put("id", smsId)
                    put("threadId", cursor.getString(threadIndex))
                    put("address", cursor.getString(addressIndex))
                    put("body", cursor.getString(bodyIndex))
                    put("date", cursor.getLong(dateIndex))
                    put("type", cursor.getInt(typeIndex))
                    put("read", cursor.getInt(readIndex))
                })
                newSmsIds.put(smsId)
            }
        }

        context.contentResolver.query(
            Telephony.Mms.CONTENT_URI,            arrayOf(Telephony.Mms._ID, Telephony.Mms.THREAD_ID, Telephony.Mms.DATE,
                Telephony.Mms.MESSAGE_BOX, Telephony.Mms.SUBJECT),
            null, null, "${Telephony.Mms.DATE} ASC"
        )?.use { cursor ->
            val idIndex = cursor.getColumnIndexOrThrow(Telephony.Mms._ID)
            val threadIndex = cursor.getColumnIndexOrThrow(Telephony.Mms.THREAD_ID)
            val dateIndex = cursor.getColumnIndexOrThrow(Telephony.Mms.DATE)
            val boxIndex = cursor.getColumnIndexOrThrow(Telephony.Mms.MESSAGE_BOX)
            val subjectIndex = cursor.getColumnIndexOrThrow(Telephony.Mms.SUBJECT)

            while (cursor.moveToNext()) {
                val mmsId = cursor.getString(idIndex)
                val mmsDate = cursor.getLong(dateIndex)
                val isNewMms = !backedUpMmsIds.contains(mmsId)
                var hasNewPart = false

                val message = JSONObject().apply {
                    put("id", mmsId)
                    put("threadId", cursor.getString(threadIndex))
                    put("date", mmsDate)
                    put("messageBox", cursor.getInt(boxIndex))
                    put("subject", cursor.getString(subjectIndex))
                }

                val addresses = readMmsAddresses(mmsId)
                if (addresses.length() > 0) message.put("addresses", addresses)

                val partsArray = JSONArray()
                context.contentResolver.query(
                    Telephony.Mms.Part.CONTENT_URI,
                    arrayOf(Telephony.Mms.Part._ID, Telephony.Mms.Part.MSG_ID,
                        Telephony.Mms.Part.CONTENT_TYPE, Telephony.Mms.Part.NAME,
                        Telephony.Mms.Part.FILENAME, Telephony.Mms.Part.TEXT),
                    "${Telephony.Mms.Part.MSG_ID}=?", arrayOf(mmsId), null
                )?.use { partCursor ->
                    val partIdIndex = partCursor.getColumnIndexOrThrow(Telephony.Mms.Part._ID)
                    val msgIdIndex = partCursor.getColumnIndexOrThrow(Telephony.Mms.Part.MSG_ID)
                    val contentTypeIndex = partCursor.getColumnIndexOrThrow(Telephony.Mms.Part.CONTENT_TYPE)
                    val nameIndex = partCursor.getColumnIndexOrThrow(Telephony.Mms.Part.NAME)
                    val filenameIndex = partCursor.getColumnIndexOrThrow(Telephony.Mms.Part.FILENAME)
                    val textIndex = partCursor.getColumnIndexOrThrow(Telephony.Mms.Part.TEXT)

                    while (partCursor.moveToNext()) {
                        val partId = partCursor.getString(partIdIndex)
                        if (backedUpPartIds.contains(partId)) continue

                        val contentType = partCursor.getString(contentTypeIndex)
                        val name = partCursor.getString(nameIndex)
                        val filename = partCursor.getString(filenameIndex)
                        val text = partCursor.getString(textIndex)
                        val partObject = JSONObject().apply {
                            put("id", partId)
                            put("msgId", partCursor.getString(msgIdIndex))
                            put("contentType", contentType)
                            put("name", name)
                            put("filename", filename)
                        }

                        if (contentType == null || contentType.startsWith("text/")) {
                            partObject.put("text", text)
                            hasNewPart = true
                            newPartIds.put(partId)
                        }

                        if (contentType != null && !contentType.startsWith("text/")) {
                            val dateString = SimpleDateFormat("yyyy-MM-dd_HHmmss", Locale.US)
                                .format(Date(mmsDate * 1000))
                            val extension = extensionForMimeType(contentType)
                            val originalName = filename?.takeIf { it.isNotBlank() }
                                ?: name?.takeIf { it.isNotBlank() }
                            val safeOriginalName = sanitizeAttachmentFilename(originalName)
                            val finalFilename = buildAttachmentFilename(
                                dateString, mmsId, partId, safeOriginalName, extension
                            )
                            val temporaryFile = File(outputDir, "attachment-$mmsId-$partId")

                            try {
                                context.contentResolver.openInputStream(
                                    android.net.Uri.parse("${Telephony.Mms.Part.CONTENT_URI}/$partId")
                                )?.use { input ->
                                    FileOutputStream(temporaryFile).use { output -> input.copyTo(output) }
                                    attachmentEntries.add(temporaryFile to finalFilename)
                                    hasNewPart = true
                                    newPartIds.put(partId)
                                    partObject.put("archiveFile", "attachments/$finalFilename")
                                    partObject.put("archiveFilename", finalFilename)
                                    partObject.put("archiveMimeType", contentType)
                                }
                            } catch (e: Exception) {
                                partObject.put("attachmentError", "${e.javaClass.simpleName}: ${e.message}")
                            }
                        }

                        partsArray.put(partObject)
                    }
                }

                message.put("parts", partsArray)
                if (isNewMms || hasNewPart) {
                    mmsArray.put(message)
                    newMmsIds.put(mmsId)
                }
            }
        }

        val manifest = JSONObject().apply {
            put("formatVersion", 4)
            put("createdAt", System.currentTimeMillis())
            put("smsCount", smsArray.length())
            put("mmsCount", mmsArray.length())
            put("attachmentCount", attachmentEntries.size)
            put("device", "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL} / Android ${android.os.Build.VERSION.RELEASE}")
            put("deviceId", Prefs.deviceId(context))
            put("deviceAlias", Prefs.deviceAlias(context))
            put("rcsStatus", "not-exported-public-api")
        }

        ZipOutputStream(BufferedOutputStream(FileOutputStream(outputFile))).use { zip ->
            writeZipEntry(zip, "manifest.json", manifest.toString(2))
            writeZipEntry(zip, "sms.json", smsArray.toString(2))
            writeZipEntry(zip, "mms.json", mmsArray.toString(2))
            for ((temporaryFile, finalFilename) in attachmentEntries) {
                if (!temporaryFile.exists()) continue
                zip.putNextEntry(ZipEntry("attachments/$finalFilename"))
                temporaryFile.inputStream().use { input -> input.copyTo(zip) }
                zip.closeEntry()
            }
        }

        for ((temporaryFile, _) in attachmentEntries) temporaryFile.delete()

        pendingSmsIds = newSmsIds
        pendingMmsIds = newMmsIds
        pendingPartIds = newPartIds
        return outputFile
    }

    /**
     * Read the MMS address table for one message. Android stores one row
     * for each sender/recipient, keyed by msg_id. The numeric type values
     * are the standard MMS PDU address types.
     */
    private fun readMmsAddresses(mmsId: String): JSONArray {
        val addresses = JSONArray()
        try {
            context.contentResolver.query(
                android.net.Uri.parse("content://mms/addr"),
                arrayOf("address", "type", "msg_id"),
                "msg_id=?",
                arrayOf(mmsId),
                null
            )?.use { cursor ->
                val addressIndex = cursor.getColumnIndexOrThrow("address")
                val typeIndex = cursor.getColumnIndexOrThrow("type")
                while (cursor.moveToNext()) {
                    val address = cursor.getString(addressIndex)?.trim().orEmpty()
                    if (address.isBlank()) continue
                    val type = cursor.getInt(typeIndex)
                    addresses.put(JSONObject().apply {
                        put("address", address)
                        put("role", mmsAddressRole(type))
                        put("type", type)
                    })
                }
            }
        } catch (e: Exception) {
            android.util.Log.w(
                "MintMessageArchive",
                "Unable to read MMS addresses for $mmsId: ${e.javaClass.simpleName}: ${e.message}"
            )
        }
        return addresses
    }

    private fun mmsAddressRole(type: Int): String = when (type) {
        137 -> "FROM"
        151 -> "TO"
        130 -> "CC"
        129 -> "BCC"
        else -> "TYPE_$type"
    }

    private fun writeZipEntry(zip: ZipOutputStream, name: String, text: String) {
        zip.putNextEntry(ZipEntry(name))
        zip.write(text.toByteArray(Charsets.UTF_8))
        zip.closeEntry()
    }

    private fun extensionForMimeType(contentType: String): String = when (contentType.lowercase(Locale.US)) {
        "image/jpeg" -> ".jpg"
        "image/png" -> ".png"
        "image/gif" -> ".gif"
        "image/webp" -> ".webp"
        "video/mp4" -> ".mp4"
        "audio/mpeg" -> ".mp3"
        "audio/amr" -> ".amr"
        else -> ".bin"
    }

    private fun sanitizeFilename(filename: String?): String? {
        return filename?.replace(Regex("[^A-Za-z0-9._-]"), "_")?.trim('_')?.take(100)
            ?.takeIf { it.isNotBlank() }
    }

    private fun buildAttachmentFilename(
        dateString: String,
        messageId: String,
        partId: String,
        originalName: String?,
        extension: String
    ): String {
        val suffix = originalName?.let { "-$it" } ?: extension
        return "${dateString}-${messageId}-${partId}$suffix"
    }
}