# MODUS Golf web app

## iPhone app — Mac build added 2026-11-02

The installed iPhone source is in **`mobile/`**. It shares this website's components and contracts while storing local captures independently of Firebase sign-in/internet. New Pi readings use the existing local `/session.csv`; no new app is hosted on the Pi.

On the MacBook with a compatible Xcode 26+ and Node 24 LTS, run from this `web/` directory:

```bash
cd mobile
npm ci
npm run ios:prepare
npm run ios:open
```

Finish the two resource memberships, `-ObjC` linker setting and Apple signing in **`mobile/MAC_BUILD_CHECKLIST.md`**. Native build/install and phone tests have not been performed yet. This app's automatic local-to-cloud upload remains unfinished.

Read **`MODUS_Golf_GitHub_Update_ZIP4_2026-11-02.md`** for this exact repository update and **`MODUS_Golf_Mac_Deployment_2026-11-02.md`** for the first install. These are the current mobile instructions. The older integration handoff's Pi upload worker proposal is superseded by a phone-side queue and trusted backend ingestion.


Published at **https://modus-golf-ea469.web.app**.

The app now has Practice, Sessions, My Bag and Settings screens, real Firebase accounts/profiles, automatic cloud-record subscriptions, an explicitly synthetic demo, and local Pi CSV preview. See `WEB_APP_REFINEMENT_2026-10-23.md` for the latest iPhone-focused release and `MODUS_Golf_GitHub_Integration_Handoff.md` for the full Pi/backend integration plan. The previous release notes retain earlier design-document traceability.

## Run and test locally

Use PowerShell on this Windows computer in this folder. Cloud Shell is a different computer and does not automatically contain these source files.

```powershell
Set-Location -LiteralPath 'C:\Users\logan\Documents\ChatGPT\modus golf'
npm ci
npm run dev
# http://localhost:5173
```

```powershell
npm test
npm run build
```

`npm test` runs the 22 unchanged original domain tests plus eleven view-model tests. To run the eleven Firebase security/auth tests, use Java 21+ and the emulator command in the release notes. `firebase.emulator-test.json` uses isolated ports 8087/9097; normal development config uses Auth 9099 and Firestore 8080.

## Use the app

- Sign in with email/password or Google to use your own Firebase account. Create a golfer profile in Settings.
- To explore populated screens without hardware, choose **Explore the demo** on the sign-in screen or select **Synthetic demo** in the data-source selector. Every demo record is synthetic and stays out of Firebase.
- Use Practice for carry-first feedback, expandable metrics and supplied flight paths, Sessions for filters/details/export, and My Bag for club means, sample SD, metric-specific counts, modeled gaps and session comparisons.
- Choose **Preview CSV** for an original `session_YYYYMMDD_HHMMSS.csv` exported from the Pi. Supply a golfer, device ID and verified Pi timezone. The entire file is validated locally. Unconfirmed records are excluded from real statistics. Normalized JSON is downloadable. The CSV upload does not contact a server or write to Firestore.
- Browser CSV history export includes stable IDs, provenance and quality flags. Its extra columns distinguish it from original Pi import files.
- A manifest and 192/512 icons are included for Home Screen use. Offline cold-start caching is not implemented; private records are held in memory only. Real Google sign-in on iPhone/Home Screen still requires interactive verification.

## Firebase resources

- Project `modus-golf-ea469`
- Existing registered app `1:759125763752:web:e9b34abb7e38f8b0dc449d`
- Firestore `(default)`, Standard/Native, `nam5`
- Email/password and Google sign-in enabled.
- Public Firebase SDK/Auth configuration in `src/firebase.ts`; lazily loaded Firestore setup in `src/firestore.ts`.
- Owner-scoped rules in `MODUS_Golf_Firebase_AI_Starter/firebase/firestore.rules`, previously deployed and freshly emulator-tested. Browser shot/session/device writes remain denied.

The app subscribes to the complete authenticated owner's shot collection for the expected small capstone dataset, rather than calculating statistics from a truncated page. Future backend-authored canonical records will appear automatically. Cloud data errors never switch to demo. Profile/account/device identity remains separate; filters do not change capture ownership. Private state and listeners are discarded on sign-out/account change.

## Publish frontend updates

Publishing the frontend is authorized. These commands publish only the contents of `dist`, not the PDFs, Pi source, tests or credentials:

```powershell
npm run build
npx -y firebase-tools@latest deploy --only hosting --project modus-golf-ea469
```

For future custom domains, configure Firebase Auth authorized domains and test the actual phone browser. No billing upgrade or ingestion backend has been provisioned. Sign-in and workspace load separately to reduce initial phone download work; the workspace chunk still triggers a build size warning.

## Real launch monitor boundary

The Pi continues to capture and compute locally. Use its separate local `/range` page and `/session.csv` export. The hosted HTTPS app does not fetch unauthenticated private HTTP endpoints. The current camera-trigger configuration, UART/GPIO assignments and capture presets are unchanged. The removed sound detector is described as temporarily unavailable, not as a failing device.

Live Pi uploads, secure device pairing, server-side import, durable uploader retries and cloud-computed analytics remain separate implementation work. See the release notes for the exact canonical Firestore contract the future backend must write. No Admin SDK/service-account key belongs in frontend code or on the Pi. No GitHub changes or Pi operations were performed.

## Handoff for the GitHub AI

Send `MODUS_Golf_GitHub_Integration_Handoff.md` and `MODUS_Golf_Web_App_Refined_2026-10-23.zip`. See `handoff/README.md` for a ready-to-send prompt and the JSON examples/storage schema. Standard Firestore trajectory points must be named maps; the website already converts those into canonical tuples. Do not write nested coordinate arrays directly to Firestore. Required secure upload work and optional physics fixes are separated in the full handoff.
