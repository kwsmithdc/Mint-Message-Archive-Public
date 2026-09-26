# Android build notes

Open this folder in Android Studio.

The project uses:
- Android Gradle Plugin 8.13.2
- Gradle 8.13
- Kotlin 2.2.21
- Compose BOM 2026.08.00
- compileSdk 36
- targetSdk 35

Android Studio should use JDK 17.

If you do not have a Gradle wrapper JAR, Android Studio can still import/sync the project using its Gradle tooling. Alternatively, create a wrapper from a machine with Gradle 8.13 installed:

    gradle wrapper --gradle-version 8.13

Then:

    ./gradlew assembleDebug
