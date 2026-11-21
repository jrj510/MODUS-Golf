# Test mobile shot ingestion

The function entry point is `ingest.mjs`. It verifies a Firebase ID token and enforces golfer ownership before writing accepted shots. Firestore rules in this directory govern client access. The installed app uses the original Firebase project and registrations.

From the repository’s `web/` directory, with Java 21 or newer installed, run:

```sh
npm ci --prefix MODUS_Golf_Firebase_AI_Starter
npx firebase-tools emulators:exec --project demo-modus-golf --only auth,firestore,functions "npm test --prefix MODUS_Golf_Firebase_AI_Starter"
```

Use the [iPhone build guide](../../README.md) to build and install the client.
