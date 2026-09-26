package com.example.mintmessagearchive

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.delay

private val MintGreen = Color(0xFF2E7D5B)
private val MintGreenDark = Color(0xFF205A41)
private val MintBackground = Color(0xFFF6F8F7)
private val MintSurface = Color.White
private val MintText = Color(0xFF17201B)
private val MintMuted = Color(0xFF64736A)
private val MintSuccess = Color(0xFF2E7D5B)
private val MintError = Color(0xFFB3261E)
private val MintWarning = Color(0xFF8A6500)

private val MintColors = lightColorScheme(
    primary = MintGreen,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD7F0E3),
    onPrimaryContainer = MintGreenDark,
    background = MintBackground,
    surface = MintSurface,
    onBackground = MintText,
    onSurface = MintText,
    outline = Color(0xFFD7DED9)
)

class MainActivity : ComponentActivity() {
    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val perms = buildList {
            add(Manifest.permission.READ_SMS)
            add(Manifest.permission.READ_PHONE_STATE)
            if (android.os.Build.VERSION.SDK_INT >= 33) {
                add(Manifest.permission.READ_MEDIA_IMAGES)
                add(Manifest.permission.READ_MEDIA_VIDEO)
                add(Manifest.permission.READ_MEDIA_AUDIO)
            }
        }.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (perms.isNotEmpty()) permissionLauncher.launch(perms.toTypedArray())

        setContent {
            MaterialTheme(colorScheme = MintColors) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MintBackground
                ) {
                    AppScreen()
                }
            }
        }
    }

    @Composable
    private fun AppScreen() {
        var server by remember { mutableStateOf(Prefs.server(this@MainActivity)) }
        var token by remember { mutableStateOf(Prefs.token(this@MainActivity)) }
        var deviceAlias by remember {
            mutableStateOf(Prefs.deviceAlias(this@MainActivity))
        }
        val deviceId = remember { Prefs.deviceId(this@MainActivity) }

        var status by remember { mutableStateOf("Ready") }
        var sms by remember { mutableStateOf("-") }
        var mms by remember { mutableStateOf("-") }
        var rcs by remember { mutableStateOf("Not tested") }
        var smsSample by remember { mutableStateOf("") }
        var mmsSample by remember { mutableStateOf("") }
        var attachmentCount by remember { mutableStateOf("0") }
        var backupWorkId by remember { mutableStateOf<UUID?>(null) }

        LaunchedEffect(backupWorkId) {
            val workId = backupWorkId ?: return@LaunchedEffect

            WorkManager.getInstance(this@MainActivity)
                .getWorkInfoByIdFlow(workId)
                .collect { workInfo ->
                    workInfo ?: return@collect
                    when (workInfo.state) {
                        WorkInfo.State.SUCCEEDED -> {
                            status = "Backup completed"
                            delay(3000)
                            status = "Ready"
                            backupWorkId = null
                        }
                        WorkInfo.State.FAILED -> {
                            val error = workInfo.outputData.getString("error")
                            status = if (error.isNullOrBlank()) {
                                "Backup failed"
                            } else {
                                "Backup failed: $error"
                            }
                            delay(5000)
                            status = "Ready"
                            backupWorkId = null
                        }
                        WorkInfo.State.CANCELLED -> {
                            status = "Backup cancelled"
                            delay(3000)
                            status = "Ready"
                            backupWorkId = null
                        }
                        else -> Unit
                    }
                }
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Header()

            SectionTitle("Phone")
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                colors = CardDefaults.cardColors(containerColor = MintSurface),
                elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
            ) {
                Column(
                    modifier = Modifier.padding(18.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    OutlinedTextField(
                        value = deviceAlias,
                        onValueChange = { deviceAlias = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Phone alias") },
                        placeholder = { Text("Example: My Phone") },
                        singleLine = true
                    )

                    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Text(
                            "Device ID",
                            style = MaterialTheme.typography.labelMedium,
                            color = MintMuted
                        )
                        Text(
                            deviceId,
                            style = MaterialTheme.typography.bodySmall,
                            color = MintText
                        )
                    }
                }
            }

            SectionTitle("Archive server")

            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                colors = CardDefaults.cardColors(containerColor = MintSurface),
                elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
            ) {
                Column(
                    modifier = Modifier.padding(18.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    OutlinedTextField(
                        value = server,
                        onValueChange = { server = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Linux server URL") },
                        placeholder = { Text("http://192.168.1.96:8765") },
                        singleLine = true
                    )

                    OutlinedTextField(
                        value = token,
                        onValueChange = { token = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Server token") },
                        visualTransformation = PasswordVisualTransformation(),
                        singleLine = true
                    )
                }
            }

            StatusCard(status)

            SectionTitle("Backup")

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                OutlinedButton(
                    onClick = {
                        Prefs.save(this@MainActivity, server, token)
                        Prefs.saveDeviceAlias(this@MainActivity, deviceAlias)

                        val result = MessageReader(this@MainActivity).scan()
                        sms = result.smsCount.toString()
                        mms = result.mmsCount.toString()
                        rcs = result.rcsProbe
                        smsSample = result.smsSample
                        mmsSample = result.mmsSample
                        attachmentCount = result.mmsAttachments.toString()
                        status = result.summary
                    },
                    modifier = Modifier.weight(1f),
                    shape = RoundedCornerShape(12.dp)
                ) {
                    Text("Scan Messages")
                }

                Button(
                    onClick = {
                        Prefs.save(this@MainActivity, server, token)
                        Prefs.saveDeviceAlias(this@MainActivity, deviceAlias)

                        status = "Backup scheduled..."
                        backupWorkId = BackupRunner.runNow(this@MainActivity)
                    },
                    modifier = Modifier.weight(1f),
                    shape = RoundedCornerShape(12.dp)
                ) {
                    Text("Backup Now")
                }
            }

            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                colors = CardDefaults.cardColors(containerColor = MintSurface),
                elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
            ) {
                Column(
                    modifier = Modifier.padding(18.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Text(
                        "Archive summary",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold
                    )

                    SummaryRow("SMS visible", sms)
                    SummaryRow("MMS visible", mms)
                    SummaryRow("RCS probe", rcs)
                    SummaryRow("MMS attachments", attachmentCount)

                    if (smsSample.isNotBlank() || mmsSample.isNotBlank()) {
                        HorizontalDivider(color = Color(0xFFE5EAE7))
                        if (smsSample.isNotBlank()) {
                            Text(smsSample, style = MaterialTheme.typography.bodySmall)
                        }
                        if (mmsSample.isNotBlank()) {
                            Text(mmsSample, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }

            SectionTitle("Automatic backups")

            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                colors = CardDefaults.cardColors(containerColor = MintSurface),
                elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
            ) {
                Column(
                    modifier = Modifier.padding(18.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    Text(
                        "Daily backup",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold
                    )
                    Text(
                        "Automatically create an incremental archive when an unmetered network connection is available.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MintMuted
                    )
                    Button(
                        onClick = {
                            Prefs.save(this@MainActivity, server, token)
                            Prefs.saveDeviceAlias(this@MainActivity, deviceAlias)
                            BackupScheduler.schedule(this@MainActivity)
                            status = "Daily automatic backup scheduled."
                        },
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp)
                    ) {
                        Text("Enable Daily Backup")
                    }
                }
            }

            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                colors = CardDefaults.cardColors(containerColor = Color(0xFFEAF4EF)),
                elevation = CardDefaults.cardElevation(defaultElevation = 0.dp)
            ) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    Text(
                        "Privacy & security",
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold,
                        color = MintGreenDark
                    )
                    Text(
                        "Your archive stays under your control. The app does not bypass Android or Google Messages security boundaries. Keep the Linux archive server on a trusted network.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MintGreenDark
                    )
                }
            }

            Spacer(Modifier.height(8.dp))
        }
    }

    @Composable
    private fun Header() {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(
                "Mint Message Archive",
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
                color = MintText
            )
            Text(
                "Your messages. Your archive.",
                style = MaterialTheme.typography.titleMedium,
                color = MintGreen
            )
            Text(
                "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL} • Android ${android.os.Build.VERSION.RELEASE}",
                style = MaterialTheme.typography.bodyMedium,
                color = MintMuted
            )
        }
    }

    @Composable
    private fun StatusCard(status: String) {
        val (container, content) = when {
            status.contains("completed", ignoreCase = true) ->
                Color(0xFFE2F2E9) to MintSuccess
            status.contains("failed", ignoreCase = true) ->
                Color(0xFFFDE9E7) to MintError
            status.contains("scheduled", ignoreCase = true) ||
                status.contains("queued", ignoreCase = true) ->
                Color(0xFFFFF3D6) to MintWarning
            else ->
                Color(0xFFEFF3F0) to MintText
        }

        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(16.dp),
            colors = CardDefaults.cardColors(containerColor = container),
            elevation = CardDefaults.cardElevation(defaultElevation = 0.dp)
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    "STATUS",
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = FontWeight.Bold,
                    color = content
                )
                Spacer(Modifier.weight(1f))
                Text(
                    status,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = content
                )
            }
        }
    }

    @Composable
    private fun SectionTitle(title: String) {
        Text(
            title,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
            color = MintText
        )
    }

    @Composable
    private fun SummaryRow(label: String, value: String) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(label, style = MaterialTheme.typography.bodyMedium, color = MintMuted)
            Text(
                value,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.SemiBold,
                color = MintText
            )
        }
    }
}

object Prefs {
    private const val NAME = "archive_prefs"

    private const val SERVER = "server"
    private const val TOKEN = "token"

    private const val DEVICE_ALIAS = "device_alias"

    fun server(c: android.content.Context) =
        c.getSharedPreferences(NAME, 0)
            .getString(SERVER, "http://192.168.1.96:8765") ?: ""

    fun token(c: android.content.Context) =
        c.getSharedPreferences(NAME, 0)
            .getString(TOKEN, "CHANGE-ME") ?: ""

    fun deviceId(c: android.content.Context): String {
        // ANDROID_ID is stable for this app-signing key, Android user, and device
        // on Android 8.0+ and does not depend on app SharedPreferences. This keeps
        // the archive identity stable across app-data clearing and reinstalling.
        val androidId = android.provider.Settings.Secure.getString(
            c.contentResolver,
            android.provider.Settings.Secure.ANDROID_ID
        )?.trim()

        require(!androidId.isNullOrBlank()) {
            "Unable to determine Android device ID"
        }

        return androidId
    }

    fun deviceAlias(c: android.content.Context) =
        c.getSharedPreferences(NAME, 0)
            .getString(DEVICE_ALIAS, "") ?: ""

    fun save(
        c: android.content.Context,
        server: String,
        token: String
    ) {
        c.getSharedPreferences(NAME, 0).edit()
            .putString(SERVER, server.trim().replace(Regex("\\s+"), "").trimEnd('/'))
            .putString(TOKEN, token)
            .apply()
    }

    fun saveDeviceAlias(
        c: android.content.Context,
        alias: String
    ) {
        c.getSharedPreferences(NAME, 0)
            .edit()
            .putString(DEVICE_ALIAS, alias.trim())
            .apply()
    }
}

object BackupScheduler {
    fun schedule(c: android.content.Context) {
        val request = PeriodicWorkRequestBuilder<BackupWorker>(24, TimeUnit.HOURS)
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.UNMETERED)
                    .build()
            )
            .build()

        WorkManager.getInstance(c).enqueueUniquePeriodicWork(
            "daily_message_archive",
            ExistingPeriodicWorkPolicy.UPDATE,
            request
        )
    }
}

object BackupRunner {
    fun runNow(c: android.content.Context): UUID {
        val req = OneTimeWorkRequestBuilder<BackupWorker>().build()
        WorkManager.getInstance(c).enqueue(req)
        return req.id
    }
}

class BackupWorker(
    appContext: android.content.Context,
    params: WorkerParameters
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): androidx.work.ListenableWorker.Result {
        return try {
            val reader = MessageReader(applicationContext)
            val backup = reader.exportIncremental()

            if (backup == null) {
                android.util.Log.d(
                    "MintMessageArchive",
                    "Backup completed: no archive was created."
                )
            } else {
                android.util.Log.d(
                    "MintMessageArchive",
                    "Archive created: ${backup.absolutePath}"
                )

                ServerClient(applicationContext).upload(backup)
                reader.commitBackupState()

                android.util.Log.d(
                    "MintMessageArchive",
                    "Backup upload completed successfully."
                )
            }

            androidx.work.ListenableWorker.Result.success()
        } catch (e: Exception) {
            val errorMessage = "${e.javaClass.simpleName}: ${e.message}"

            android.util.Log.e(
                "MintMessageArchive",
                "Backup failed: $errorMessage",
                e
            )

            androidx.work.ListenableWorker.Result.failure(
                workDataOf("error" to errorMessage)
            )
        }
    }
}
