@echo off
setlocal

set "GRADLE_VERSION=8.13"
set "GRADLE_ROOT=%USERPROFILE%\.gradle\mint-message-archive\gradle-%GRADLE_VERSION%"
set "GRADLE_BIN=%GRADLE_ROOT%\bin\gradle.bat"
set "DIST_URL=https://services.gradle.org/distributions/gradle-%GRADLE_VERSION%-bin.zip"
set "TMP_DIR=%GRADLE_ROOT%.download"

if not exist "%GRADLE_BIN%" (
    if not exist "%TMP_DIR%" mkdir "%TMP_DIR%"
    echo Downloading Gradle %GRADLE_VERSION%...

    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$ErrorActionPreference='Stop'; Invoke-WebRequest -Uri '%DIST_URL%' -OutFile '%TMP_DIR%\gradle.zip'"

    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$ErrorActionPreference='Stop'; Expand-Archive -Force '%TMP_DIR%\gradle.zip' '%TMP_DIR%'"

    if not exist "%TMP_DIR%\gradle-%GRADLE_VERSION%\bin\gradle.bat" (
        echo Error: Gradle archive did not contain the expected distribution.
        exit /b 1
    )

    if exist "%GRADLE_ROOT%" rmdir /s /q "%GRADLE_ROOT%"
    move "%TMP_DIR%\gradle-%GRADLE_VERSION%" "%GRADLE_ROOT%" >nul
    rmdir /s /q "%TMP_DIR%"
)

call "%GRADLE_BIN%" %*
