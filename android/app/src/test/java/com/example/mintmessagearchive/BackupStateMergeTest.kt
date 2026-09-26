package com.example.mintmessagearchive

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

class BackupStateMergeTest {

    @Test
    fun mergeAddsNewIdsWithoutDuplicatingExistingIds() {
        val state = JSONObject()
            .put("smsIds", JSONArray().put("sms-1"))
            .put("mmsIds", JSONArray().put("mms-1"))
            .put("partIds", JSONArray().put("part-1"))

        mergeBackupState(
            state,
            JSONArray().put("sms-1").put("sms-2"),
            JSONArray().put("mms-1").put("mms-2"),
            JSONArray().put("part-1").put("part-2")
        )

        assertJsonValues(state.getJSONArray("smsIds"), "sms-1", "sms-2")
        assertJsonValues(state.getJSONArray("mmsIds"), "mms-1", "mms-2")
        assertJsonValues(state.getJSONArray("partIds"), "part-1", "part-2")
    }

    @Test
    fun mergeCreatesMissingStateArrays() {
        val state = JSONObject()

        mergeBackupState(
            state,
            JSONArray().put("sms-10"),
            JSONArray().put("mms-20"),
            JSONArray().put("part-30")
        )

        assertJsonValues(state.getJSONArray("smsIds"), "sms-10")
        assertJsonValues(state.getJSONArray("mmsIds"), "mms-20")
        assertJsonValues(state.getJSONArray("partIds"), "part-30")
    }

    private fun assertJsonValues(array: JSONArray, vararg expected: String) {
        assertEquals(expected.size, array.length())
        expected.forEachIndexed { index, value ->
            assertEquals(value, array.getString(index))
        }
    }
}
