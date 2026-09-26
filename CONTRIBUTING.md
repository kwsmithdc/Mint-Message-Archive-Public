# Contributing

Contributions and derivative projects are welcome under the Apache License 2.0.

You may:

- fork the project;
- modify the source;
- fix bugs;
- add features;
- adapt the project to other Android devices or Linux environments;
- maintain your own version;
- redistribute modified versions in accordance with the license.

The original author does not promise to review, merge, release, maintain, or support contributions.

## Development checks

Run the Linux regression suite:

    ./run-tests.sh

Run Android unit tests and build the debug APK:

    cd android
    ./gradlew :app:testDebugUnitTest
    ./gradlew :app:assembleDebug

Please do not include personal message data, attachments, production databases, authentication tokens, private device identifiers, private network information, or other sensitive information in contributions.
