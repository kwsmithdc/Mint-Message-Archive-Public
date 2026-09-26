#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/kwsmithdc/Mint-Message-Archive-Public.git"
INSTALL_DIR="${MINT_MESSAGE_ARCHIVE_DIR:-$HOME/mint-message-archive}"
APK="$INSTALL_DIR/android/app/build/outputs/apk/debug/app-debug.apk"

log() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

command -v adb >/dev/null 2>&1 || fail "adb is required. On Linux Mint/Ubuntu, install it with: sudo apt install adb"
command -v java >/dev/null 2>&1 || fail "Java is required. Install OpenJDK 17 with: sudo apt install openjdk-17-jdk"

JAVA_VERSION="$(java -version 2>&1 | awk -F '[".]' '/version/ {print $2; exit}')"
[[ "$JAVA_VERSION" == "17" ]] || fail "Java 17 is required. Found Java $JAVA_VERSION."

if [[ -e "$INSTALL_DIR/.git" ]]; then
    log "Updating existing source checkout"
    git -C "$INSTALL_DIR" pull --ff-only
elif [[ -e "$INSTALL_DIR" ]]; then
    fail "$INSTALL_DIR exists but is not a Git checkout."
else
    command -v git >/dev/null 2>&1 || fail "Git is required. Install it with: sudo apt install git"
    log "Downloading Mint Message Archive"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

if [[ -z "${ANDROID_HOME:-}" && -z "${ANDROID_SDK_ROOT:-}" ]]; then
    cat >&2 <<'EOF'

Android SDK was not detected.

Install Android Studio or the Android SDK command-line tools, then set
ANDROID_HOME or ANDROID_SDK_ROOT and make sure the required SDK platform
and build tools are installed.

After that, run this installer again.
EOF
    exit 1
fi

log "Checking for an authorized Android device"
adb start-server >/dev/null
DEVICE_COUNT="$(adb devices | awk 'NR > 1 && $2 == "device" {count++} END {print count+0}')"
[[ "$DEVICE_COUNT" -eq 1 ]] || fail "Exactly one authorized Android device must be connected; found $DEVICE_COUNT."

log "Building the Android application"
cd "$INSTALL_DIR/android"
./gradlew :app:testDebugUnitTest :app:assembleDebug

[[ -f "$APK" ]] || fail "The APK was not produced at $APK."

log "Installing the APK"
adb install -r "$APK"

cat <<EOF

Android application installed successfully.

APK:
  $APK

Connected device:
EOF
adb devices

printf '\nNext steps:\n'
printf '  1. Open Mint Message Archive on the phone.\n'
printf '  2. Enter the Linux server URL and token.\n'
printf '  3. Run a manual backup.\n'
printf '  4. Confirm the archive appears in the Linux web interface.\n'
