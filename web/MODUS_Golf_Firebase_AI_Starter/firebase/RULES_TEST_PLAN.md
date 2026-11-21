# Firebase emulator checks

From `web/`, install the locked dependencies with `npm ci`. With Java 21 or newer on your PATH, run `npm run test:firebase`. The command starts Auth and Firestore for the local demo project, runs both suites and shuts the emulators down.

| Suite | What it checks |
|---|---|
| [Authentication](../../tests/auth.test.mjs) | Email/password registration, sign-out, failed login, signing back in and switching accounts. A separate test signs in with a synthetic Google credential in the Auth emulator. |
| [Firestore access rules](../../tests/firestore.test.mjs) | Signed-out and cross-account access, validated golfer profiles and timestamps, owner reads of backend-written shots, direct-write denial, device registration access and private credential documents. |

The ingestion function uses the Admin SDK. Run its [separate integration suite](README.md) to exercise authenticated uploads, ownership, replay receipts and the 34-column shot contract with the Functions emulator. Native sign-in and capture on the monitor hotspot are physical iPhone checks.
