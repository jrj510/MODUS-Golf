# Manual GitHub update — MODUS-Golf-main (4).zip

Prepared 2026-11-02. This update targets the fourth supplied ZIP, not ZIP 3.

Reviewed ZIP SHA-256: `9a685acd09de30a78ad877f2aaf0bc6df4ce966a80cdfd61ea70cc8cc70608e6`.

## What to upload

1. Extract **`MODUS_Golf_GitHub_Update_ZIP4_2026-11-02.zip`**.
2. In GitHub open the repository root, where `camera/`, `web/` and `start_kiosk.sh` exist.
3. Use **Add file → Upload files** and upload the extracted **`web/` folder into that root**, preserving subfolders. Do not upload the ZIP itself as a repository file, and do not put the folder under another `web/`.
4. Review the change list below and commit. Merge folder contents; do not delete/recreate your existing `web/` directory. Ensure the included `web/mobile/.gitignore` is uploaded.

The final app manifest must be at **`web/mobile/package.json`**.

This overlay adds **24 files** and replaces **four existing files**, all under `web/`. It includes no Pi code, `node_modules`, generated build output, native iOS project or signing credentials. The four newer Pi files from ZIP 4 remain intact.

## Existing files to replace

| Repository file | Change |
|---|---|
| `web/MODUS_Golf_Firebase_AI_Starter/app-core/shot.mjs` | Adds an optional portable SHA-256 implementation hook for the phone while preserving default web hashing behavior and IDs. |
| `web/MODUS_Golf_Firebase_AI_Starter/app-core/shot.d.mts` | Matching TypeScript declaration for the hash hook. |
| `web/README.md` | Keeps the old website instructions and adds the current iPhone/Mac commands and limitations. |
| `web/AGENTS.md` | Keeps the existing Firebase instructions and adds the registered Apple app, offline practice and selected Mac workflow. |

The existing shared UI, contracts and required fixtures match the prepared app source and do not need replacing. The existing website package/lockfile, Firebase Hosting/Auth configuration and Firestore rules stay as provided in ZIP 4.

## New app files

Upload the entire supplied `web/mobile/` folder:

```text
web/mobile/
  .gitignore
  capacitor.config.ts
  index.html
  package.json
  package-lock.json
  tsconfig.json
  vite.config.ts
  README.md
  MAC_BUILD_CHECKLIST.md
  src/
    journal.ts
    main.tsx
    native-firebase.ts
    pi.ts
    storage.ts
    style.css
  tests/
    journal.test.mjs
  scripts/
    prepare-mac.mjs
    configure-ios.swift
  firebase/
    GoogleService-Info.plist
    apple-app.json
    Info.plist.required-entries.json
    PrivacyInfo.xcprivacy
```

Also upload the two new documents:

- `web/MODUS_Golf_Mac_Deployment_2026-11-02.md`
- `web/MODUS_Golf_GitHub_Update_ZIP4_2026-11-02.md` — this guide.

## First Mac build after committing

Clone/download the updated repository on the MacBook. Keep the whole repository arrangement. From its root:

```bash
cd web/mobile
npm ci
npm run ios:prepare
npm run ios:open
```

Use Xcode 26+ and Node 24 LTS. Sequoia 15.6.1 can use Xcode 26.3; select a compatible version using Apple's current requirements if using a different macOS. Finish the App resource memberships, `-ObjC` linker flag and owner's signing team in the Mac checklist, then Run on the iPhone. The setup script never text-edits `.pbxproj`; no native project or signed IPA is included in this upload.

Reuse the existing Firebase project `modus-golf-ea469` and Apple registration `1:759125763752:ios:7e7aacf0f2e63d32dc449d`, bundle ID `com.modusgolf.app`. The client plist is included; it is not an Admin SDK credential. No Firebase re-registration or Pi app hosting is needed for the first local test.

## What changed in ZIP 4 and is preserved

Compared with ZIP 3, the only changed files are `camera/iwr_bridge.py`, `camera/kiosk.py`, `camera/launcher.py` and `start_kiosk.sh`. The changes add an in-kiosk club selector, remember the selection, forward club changes to the radar bridges, simplify the launcher and use full-sensor/144 FPS for Inside Golf. This upload contains none of those files and preserves their exact bytes.

The current CSV header/order and original filename response remain compatible with the prepared phone reader. Missing measurements remain null; no trajectories or UTC impact times are invented from CSV. The phone does not poll camera streams or run a new flight model.

## Remaining work — not finished by this upload

This update puts the mobile source and Mac preparation workflow in GitHub. It is not a claim of a native device build or complete automatic cloud sync.

- **Cloud sync:** implement explicit account/profile/device pairing, a persistent phone upload queue, authenticated ingestion and idempotent commit acknowledgements. The three Pi `cloud/*.py` files are still empty, but a Pi uploader is not required by the selected phone-first design. Keep current client shot-write denial; account sign-in and cloud history reads do not prove new captures uploaded.
- **Pi archive recovery:** `/session.csv` exposes the current run, while `/history` is a 30-shot in-memory view. A read-only archive listing/download route or manual file transfer is needed to recover an uncopied older session after restart.
- **CSV correctness:** use proper CSV quoting and complete-row download snapshots. Before the first saved shot the current endpoint uses the generic filename `session.csv`, which is intentionally not accepted as a durable session identity by the phone reader. Define an empty-session response or initialize a legitimate session/header.
- **Overlapping results:** `_publish()` still returns early if a newer shot replaced the displayed one, before the old final result can be logged. Persist each shot's final data independently of the current UI selection.
- **New club selector:** `_publish()` reads the current global club rather than a frozen capture-time club. Changing club while a previous radar job is still processing can apply the new club to the older shot. Freeze per-shot context in a future Pi fix; for the first test, wait until the previous shot finishes before switching clubs.
- **Optional flight correction:** the active call still omits measured launch direction. Keep this separate from connectivity; CSV supplies no trajectory points, so the phone leaves them unavailable.

The older Pi worker/outbox handoff is background context and is superseded as the primary plan. Do not change startup, GPIO/UART, FPS or capture/calibration settings just to add this mobile package.

## Verification

The ZIP 4 files were compared byte-for-byte with ZIP 3 and the required web shared dependencies with the prepared mobile source. The upload manifest records add/replace actions and before/after hashes. The four Pi files are excluded from the overlay. See the accompanying validation record for source/integration checks; native compile/sign/install, actual iPhone layout/network/Firebase testing and hardware capture tests remain pending. Source from the supplied ZIP was treated as reference and no Pi hardware code was executed.
