# Mint Message Archive

**A self-hosted Android SMS/MMS archival system for Linux, designed to keep message archives under the user's control.**

Mint Message Archive creates portable ZIP archives from Android SMS/MMS data and attachments, transfers them over a trusted local network to a Linux server, preserves the original ZIP files, and builds a SQLite search index for convenient local browsing.

## Installation

### Linux server — automated installation

On a supported Linux Mint/Ubuntu-style system with Python 3.12, the simplest installation is:

```bash
curl -fsSL https://raw.githubusercontent.com/kwsmithdc/Mint-Message-Archive-Public/main/install.sh | bash
```

The installer downloads the public source, creates the archive and protected token directories, generates a token if one does not already exist, installs the user-level systemd services, enables the health timer, and verifies the local health endpoint.

It does not expose the server to the Internet. If UFW is already active, the installer attempts to allow the detected local IPv4 subnet to reach port 8765.

For manual installation, see [linux-server/README.md](linux-server/README.md).

### Android application — automated ADB installation

If Android SDK tooling is already installed on the Linux computer and one Android phone is connected with USB debugging authorized:

```bash
curl -fsSL https://raw.githubusercontent.com/kwsmithdc/Mint-Message-Archive-Public/main/install-android.sh | bash
```

The script runs the Android unit tests, builds the debug APK, verifies that exactly one authorized phone is connected, and installs the APK with ADB.

Detailed Android installation instructions are in [ANDROID-INSTALL.md](ANDROID-INSTALL.md).

### Prebuilt Android APK

Tagged public releases include a downloadable debug APK built by GitHub Actions. This is the easiest option for users who do not want to set up Android Studio or build the Android project themselves.

Open the repository's **Releases** page and download the APK from the release assets. Android may require enabling installation from the application used to open the APK.

The ADB installer remains available when you want the source tree built and installed automatically.

### Manual Android build

```bash
cd android
./gradlew :app:testDebugUnitTest
./gradlew :app:assembleDebug
```

The APK is produced at `android/app/build/outputs/apk/debug/app-debug.apk`.

## What it does

- Archives SMS messages.
- Archives MMS messages and MMS participants.
- Preserves MMS attachments inside the original ZIP archive.
- Supports multiple Android phones with separate device identities and aliases.
- Performs incremental backups so previously archived records are not repeatedly exported.
- Keeps preserved ZIP archives authoritative; SQLite is a searchable index.
- Provides a local web interface with text, sender/recipient, device, type, date, and attachment filters.
- Provides message details, conversation/thread views, and attachment previews/downloads.
- Includes read-only archive integrity, inventory, health, rebuild, and database-comparison tools.
- Includes automated Android and Linux regression testing.

## LAN-only design

The archive data path is intentionally **local-network only**.

The Android application validates the configured server address before uploading and rejects public Internet destinations. The Linux receiver also rejects requests from non-local/private client addresses.

Mint Message Archive does **not** use cloud storage, third-party archive services, Internet synchronization, telemetry, analytics, or an Internet-facing archive service.

The Linux computer may still have ordinary Internet access for unrelated operating-system maintenance. That does not make the archive data path an Internet service.

Do not expose the archive server through port forwarding, public DNS, or another Internet-facing path.

## Architecture

```text
Android phone(s)
      |
      | SMS / MMS / attachments
      | Local network
      v
Mint Message Archive Android app
      |
      v
Linux archive server
      |
      +--> Preserved original ZIP archives
      |
      +--> SQLite searchable index
      |
      +--> Local web archive interface
```

Each phone receives its own persistent device identity. Device archives are stored separately so multiple phones can use the same Linux archive server.

## Archive preservation

The original ZIP archive is the authoritative preserved source data.

The Linux server stores uploaded archives under a device-specific directory and does not delete an existing preserved archive when the same archive filename is uploaded again.

SQLite contains an index of the preserved data. The project includes tools that can rebuild the searchable database from the preserved ZIP archives without rewriting the source archives.

## Android application

The Android application is written in Kotlin.

Major components include:

- `MainActivity.kt` — application UI and backup controls.
- `MessageReader.kt` — SMS/MMS export, participants, attachments, manifest creation, and incremental backup state.
- `ServerClient.kt` — authenticated archive upload.
- `LocalNetworkValidator.kt` — LAN-only destination validation.
- Android WorkManager components — automatic backup scheduling.

The application records the device manufacturer/model and Android release at runtime rather than assuming a particular phone model.

### RCS

The application can report RCS capability/status, but it does not claim to export RCS message history through unsupported Android APIs.

The current public Android application exports SMS and MMS data available through the supported message providers. RCS message history is not currently exported.

## Linux archive server

The Linux server is implemented with the Python standard library and currently requires **Python 3.12**.

The Linux component includes:

- archive receiver
- SQLite database/index
- local web interface
- archive inventory tool
- archive integrity verifier
- database rebuild tool
- read-only database comparison tool
- archive health report
- duplicate-maintenance tooling
- systemd service/timer examples
- automated regression tests

Python 3.12 is required because the current receiver uses the standard-library multipart parser provided by the `cgi` module, which is unavailable in Python 3.13.

## Web interface

The local web interface provides:

- keyword/message-text search
- device filtering
- SMS/MMS filtering
- sender/recipient/contact filtering
- date-range filtering
- attachment filtering
- pagination
- individual message details
- MMS participant information
- conversation/thread browsing
- inline image, video, and audio previews
- attachment downloads

Browser access uses HTTP Basic authentication with the same token used by the Android uploader.

## Security model

The project is designed for a trusted local network.

Security measures include:

- LAN-only destination validation on Android
- LAN-only source validation on the Linux server
- bearer-token authentication for uploads
- Basic authentication for the local web interface
- protected external token-file support
- safe device identifier validation
- safe archive filename validation
- ZIP archive validation
- safe ZIP-member path validation
- non-destructive archive preservation
- read-only recovery and integrity tooling
- automated regression tests for network and archive boundary conditions

HTTP is used for the local archive connection. Do not expose the service beyond the trusted network.

## Building the Android app

A Java 17 development environment and the included Gradle wrapper are used by the project.

From the `android/` directory:

```bash
./gradlew :app:testDebugUnitTest
./gradlew :app:assembleDebug
```

The resulting debug APK is produced under:

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

## Linux regression suite

From the repository root:

```bash
./run-tests.sh
```

The regression suite checks:

- Python 3.12 runtime compatibility
- Python syntax
- Linux server unit/regression tests
- SQLite initialization and integrity
- repository checks for obvious installation-specific paths, identifiers, and bearer credentials

The test suite uses temporary test data and does not require a production archive.

## Project status

This repository is a **completed public snapshot/reference implementation**.

The original author does not promise ongoing maintenance, future releases, security patches, compatibility updates, bug fixes, feature development, or user support.

Anyone may fork, modify, improve, maintain, or redistribute the project under the terms of the Apache License 2.0.

## Privacy

Do not place personal messages, attachments, production SQLite databases, server tokens, device identifiers, private network details, or other personal information into a public repository.

The public source tree is intended to contain source code, generic examples, tests, and documentation—not personal archive data.

## License

Copyright © 2026 Kevin Smith.

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Additional project-specific information is provided in [DISCLAIMER.md](DISCLAIMER.md), [SUPPORT.md](SUPPORT.md), and [CONTRIBUTING.md](CONTRIBUTING.md).
