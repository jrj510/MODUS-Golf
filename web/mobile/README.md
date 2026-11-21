# MODUS Golf iPhone app source

This is a separate Capacitor/React iPhone app package. It reuses the website's metric, flight, history, bag and domain components. Screens and local storage start independently of Firebase Authentication or internet availability. The published website remains a separate build.

## Current status

- Firebase Apple app registered: **MODUS Golf iPhone**.
- Project: **`modus-golf-ea469`**.
- Bundle identifier: **`com.modusgolf.app`**.
- Apple Firebase app ID: **`1:759125763752:ios:7e7aacf0f2e63d32dc449d`**.
- Downloaded and validated native configuration: `firebase/GoogleService-Info.plist`.
- Email/password and Google Authentication enabled in the existing project.
- Native Auth plugin methods: create account, email/password sign-in, Google sign-in, password reset, sign-out and cached account restoration.
- Native Firestore plugin: persistent cache, owner-scoped shot/profile subscriptions, validated point-map decoding and golfer profile creation.
- Local app storage: two checksummed generations, serialized writes, read-back verification and recovery from an incomplete newer generation. Native storage uses the app's private data directory; browser preview uses IndexedDB.
- Local Pi transport: bounded foreground reads of the existing `/session.csv` endpoint through Capacitor's native HTTP transport; no website or new processing service runs on the Pi.
- Explicitly synthetic records stay separate and cannot be uploaded or reclassified as physical shots.
- TypeScript/Vite build and automated storage tests pass. **No IPA has been compiled, signed or installed yet.** Native SDK callbacks, local-network permissions, cold launch and actual iPhone behavior require the first device build.
- **Cloud upload of locally captured shots is not implemented/deployed.** Existing private Firebase history can be read. Physical local records await explicit account/profile pairing and the authenticated ingestion service described in the handoff. Existing Firestore rules deny direct client shot writes; this app preserves that boundary.

## Offline behavior

| Connection | Available behavior |
|---|---|
| No Wi-Fi and no cellular service | Open the installed app, view previously saved local shots, inspect statistics and test synthetic fixtures. |
| MODUS Wi-Fi, no internet | Copy new final Pi CSV rows to phone storage; use the local app and history. |
| Internet available | Sign in/create account with Firebase, use Google sign-in, and read the account's cloud history. Automatic upload of local captures still needs pairing/ingestion integration. |

The app cannot receive new measurements from a physically separate Pi when there is no communication link. Receiving live Pi shots requires its local Wi-Fi or another future transport. Internet access is not required for that local link.

The app does not require a sign-in screen to finish loading before local practice opens. New sign-ins, account creation, Google OAuth and password reset require internet. A restored cached account is not proof of current server authorization; backend access is still enforced by Firebase.

This prototype copies only finalized legacy CSV data. CSV has no trajectory points, capture readiness or reliable UTC impact timestamp. Those fields are not invented. The supplied flight view is populated for explicit synthetic fixtures and future properly sourced canonical cloud records.

## Develop and preview on Windows

Keep this folder beside the parent `src/` and `MODUS_Golf_Firebase_AI_Starter/` folders; they contain the reused code and contracts.

```powershell
Set-Location -LiteralPath 'C:\Users\logan\Documents\ChatGPT\modus golf\mobile'
npm ci
npm test
npm run build
npm run dev
```

Preview at **http://127.0.0.1:5174**. The browser preview deliberately does not execute native Firebase or direct-Pi functions. It tests the UI and IndexedDB storage. Add a synthetic test shot, reload, then choose Synthetic test shots to confirm persistence. Previewing in a browser is not an installed iPhone build.

The package lock pins compatible dependencies separately from the existing website. Compatible overrides patch the grpc-js and UUID audit findings. The package audit reported zero vulnerabilities after those overrides. Do not run a forced major-version audit upgrade as part of copying the source.

## Build and install on a MacBook with Xcode — selected route

As of 2026-10-29, the owner selected a MacBook using the easiest suitable tool. Follow **`MAC_BUILD_CHECKLIST.md`**: build the shared UI, generate/reuse the standard Capacitor iOS project using SPM, then configure, sign and install through Xcode. Use the owner's Apple signing identity. Keep signing credentials outside this source tree.

Updated 2026-11-02: after extracting the complete Mac package and installing Xcode 26+ and Node 24 LTS, open Terminal in `mobile/` and run:

```bash
npm ci
npm run ios:prepare
npm run ios:open
```

`ios:prepare` checks the Mac toolchain, runs tests/build, generates or reuses the standard SPM project, syncs plugins/assets and runs the Swift resource configurator. It never edits `.pbxproj` directly. Finish the two resource target memberships, `-ObjC` linker setting and signing in Xcode as described in the checklist. `ios:check` can validate source/configuration on Windows without generating native files.

## Native build work still required

This folder contains the React/Capacitor UI and TypeScript native-plugin calls. The native iOS project still needs generation/configuration on the MacBook, including the Firebase plist, Google callback, native plugin linkage, signing and actual iPhone tests. `npm run build` creates UI assets, not a signed IPA. Use the documented Capacitor generator rather than building a custom xtool host for this route.

`WINDOWS_XTOOL_BUILD_PLAN.md` and `XTOOL_NATIVE_HOST_TODO.md` remain optional alternative references. They are not prerequisites for the selected MacBook/Xcode workflow. No native build/sign/install or Apple login has been performed by this task.

## Files that must reach the native app bundle

- The whole `dist/` output, bundled as the native host's web assets with a working Capacitor bridge; **no remote `server.url`** for a release.
- `firebase/GoogleService-Info.plist`, included in the actual App target's resources.
- `firebase/PrivacyInfo.xcprivacy`, merged into the native app's privacy manifest for the Filesystem file-timestamp API usage.
- URL scheme and local-network settings from `firebase/Info.plist.required-entries.json`, merged into the actual application Info.plist.
- Linked and registered native plugin packages, including Firebase Authentication with the Google SPM trait, Firebase Firestore, Filesystem and App. Use Capacitor sync and verify the actual native dependencies in Xcode.

Do not copy `GoogleService-Info.plist` only into a web asset folder. Native Firebase must find it at the application resource level. The native plugins configure Firebase if needed before using Auth/Firestore. Avoid double-configuring the default Firebase app or using web `signInWithPopup` inside the iPhone WebView.

## Capture and storage limits to verify

The current Pi exposes only its current run at `/session.csv`; it writes historical files locally but has no session archive download API. If the phone misses a session and the Pi restarts before copying it, the app cannot recover that older file automatically with the current API. The first offline field test must cover this case. A minimal future read-only archive listing/download endpoint or explicit session-file transfer can solve it without hosting the website or adding new flight computation on the Pi.

This app polls only while foregrounded and connected. iOS background execution is not a guaranteed continuous collector. The existing Pi CSV log remains the source for recovering missed measurements. Stop/restart the app, lose local Wi-Fi, restart the Pi and check recovery deliberately.

The local profile/device IDs are provisional single-monitor test context, not verified Firebase ownership. Do not automatically assign all stored shots to whichever account signs in next. Pairing must explicitly resolve capture ownership before the ingest backend accepts them.

Local journal backup export is available in Connection. Deleting the app can delete its local files. The two-generation journal is a capstone-scale implementation; field-test large trajectory datasets and consider transactional SQLite for a larger release.

## Monitor remote

Join MODUS Wi-Fi, start a local connection in the app, and select **Enable phone controls**. The remote starts off each time you enter the Connection screen, reconnect, or return from the background. The physical touchscreen stays active. Club, low light, camera zoom on supported hardware, sleep, and wake use the existing kiosk commands.

The **Show on monitor screen** buttons require a running kiosk with the display-control change in `camera/kiosk.py`. Updating the GitHub checkout alone does not update a running monitor. The Dashboard, Camera, and Range buttons send one-time page requests. The phone confirms each change when the monitor browser acknowledges it. Normal touchscreen navigation can continue immediately.
