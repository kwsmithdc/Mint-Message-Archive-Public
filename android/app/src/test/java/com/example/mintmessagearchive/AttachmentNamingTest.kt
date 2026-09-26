package com.example.mintmessagearchive

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AttachmentNamingTest {

    @Test
    fun mimeTypesUseExpectedExtensions() {
        assertEquals(".jpg", extensionForMimeType("image/jpeg"))
        assertEquals(".png", extensionForMimeType("IMAGE/PNG"))
        assertEquals(".mp4", extensionForMimeType("video/mp4"))
        assertEquals(".mp3", extensionForMimeType("audio/mpeg"))
        assertEquals(".amr", extensionForMimeType("audio/amr"))
        assertEquals(".bin", extensionForMimeType("application/octet-stream"))
    }

    @Test
    fun attachmentFilenameSanitizationRemovesUnsafeCharacters() {
        assertEquals("photo_2026-09-25.jpg", sanitizeAttachmentFilename(" photo/2026-09-25.jpg "))
        assertEquals(".._hidden", sanitizeAttachmentFilename("../hidden"))
        assertNull(sanitizeAttachmentFilename("___"))
        assertEquals(100, sanitizeAttachmentFilename("a".repeat(150))!!.length)
    }

    @Test
    fun attachmentFilenameIncludesStableMessageAndPartIdentity() {
        assertEquals(
            "2026-09-25_120000-42-7-photo.jpg",
            buildAttachmentFilename(
                "2026-09-25_120000",
                "42",
                "7",
                "photo.jpg",
                ".jpg"
            )
        )
        assertEquals(
            "2026-09-25_120000-42-7.bin",
            buildAttachmentFilename(
                "2026-09-25_120000",
                "42",
                "7",
                null,
                ".bin"
            )
        )
    }
}
