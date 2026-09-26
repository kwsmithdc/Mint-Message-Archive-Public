# Changelog

All notable changes included in the public Mint Message Archive snapshot are documented here.

## 1.0.0 — Public Snapshot

### Android application

- Added incremental SMS and MMS backup support.
- Added persistent backup state committed only after successful archive upload.
- Added incremental MMS attachment detection.
- Added MMS participant export for searchable sender/recipient filtering.
- Added multiple-phone support using persistent device identities and user-defined aliases.
- Added automatic backups using Android WorkManager.
- Added LAN-only destination validation before archive upload.
- Added authenticated local archive uploads.
- Added runtime device manufacturer/model and Android release metadata instead of development-machine-specific values.
- Added attachment filename sanitization and deterministic attachment naming.
- Added Android unit tests for backup-state merging, attachment naming, and LAN validation.
- Added Android CI builds and unit-test execution.

### Linux server

- Added authenticated archive uploads.
- Added LAN-only client validation.
- Added race-safe preservation of duplicate archive uploads.
- Added safe device identifier validation.
- Added safe archive filename validation.
- Added malformed manifest validation.
- Added protected token-file support.
- Added SQLite indexing for SMS, MMS, MMS parts, participants, and attachments.
- Added local searchable web interface.
- Added message details, thread browsing, participant display, and attachment previews/downloads.
- Added archive inventory and ZIP CRC verification.
- Added non-destructive SQLite database rebuild tooling.
- Added read-only database comparison tooling.
- Added archive health reporting and recovery-readiness checks.
- Added duplicate-maintenance tooling.
- Added Linux regression tests and GitHub Actions verification.
- The Linux server currently requires Python 3.12.

### Public-release documentation

- Added Apache License 2.0 licensing.
- Added project attribution in NOTICE.
- Added plain-language disclaimer information.
- Added an explicit no-ongoing-support policy.
- Added contribution/forking guidance.
- Removed production archive data and installation-specific credentials from the public snapshot.

## Release audit

The public snapshot was audited for installation-specific device identifiers, production archive data, development filesystem paths, and credentials before publication.

## Maintenance policy

This public snapshot is released as a completed reference implementation. No future releases, security patches, compatibility updates, bug fixes, feature development, or support are promised by the original author.
