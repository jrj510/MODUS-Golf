# Firebase

Always look for and use the appropriate installed Firebase agent skills for Firebase tasks.

Use the existing Firebase project `modus-golf-ea469` and web app `1:759125763752:web:e9b34abb7e38f8b0dc449d`.

The backend uses Firebase Authentication with email/password and Google sign-in, plus Cloud Firestore.

# Installed iPhone app

Reuse Firebase Apple app `1:759125763752:ios:7e7aacf0f2e63d32dc449d`, bundle ID `com.modusgolf.app`, in the same project. Source is in `mobile/` relative to this directory.

Local practice and previously saved shots must open without internet or Firebase sign-in. The Pi keeps its existing capture/computation and current-session CSV service; do not host the mobile UI or add a cloud upload worker on the Pi.

Use a MacBook with the standard Capacitor CLI, Xcode and Swift Package Manager workflow. This supersedes the earlier Windows/xtool requirement. Read `mobile/MAC_BUILD_CHECKLIST.md` and `MODUS_Golf_GitHub_Update_ZIP4_2026-11-02.md`. On the Mac, run `npm ci`, `npm run ios:prepare` and `npm run ios:open` from `mobile/`, then finish resource membership, linker flags and signing in Xcode.

The existing Mac host has built on simulator and device. The owner verified physical Google sign-in and persistence. The phone queues confirmed, account-linked sessions for authenticated ingestion. Preserve the private Firestore rules. Verify capture, display control and upload with a physical monitor before release.
