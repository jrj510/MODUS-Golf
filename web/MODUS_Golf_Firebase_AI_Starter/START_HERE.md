# MODUS Golf Firebase app handoff

This package starts the phone web app around the actual October 22 uploaded Pi code. It contains a complete AI build brief, current API evidence, sample data, tested JavaScript import/statistics helpers, and a conservative Firestore rules draft. It is not a deployed app or a replacement for the working Pi software.

## Use it now

1. Unzip this package on Windows.
2. Open Google AI Studio at https://aistudio.google.com/ and select Build and the web-app target. Sign in with the Google account that will own the project. For an existing Firebase Studio workspace, its coding assistant can also use these files.
3. Paste **FIREBASE_AI_MASTER_PROMPT.md** into the builder. This prompt is self-contained, so a ZIP importer is not required.
4. Supply `PROJECT_CONTEXT.md`, `contracts/`, and `app-core/` through the builder's supported file/context controls or code editor. If it cannot attach code, paste the needed files as named code blocks. Do not assume that uploading this ZIP automatically imports a project.
5. Ask for the demo app first, using the included synthetic fixtures. Download its generated source ZIP when the demo works. Return that ZIP to this chat for review.
6. Use `prompts/02_CONNECT_FIREBASE.md` after the interface and tests work. Review and select the Firebase project/location before enabling its integration. Production deployment and billing are separate steps.
7. Use `prompts/03_CONNECT_THE_PI.md` only after the cloud API and ownership rules have been implemented and tested. This is a later integration brief, not a script to run on the Pi now.

For a short initial message, paste: "Build the MODUS Golf app described in FIREBASE_AI_MASTER_PROMPT.md. Use PROJECT_CONTEXT.md and contracts as authoritative. First create a working, clearly labeled demo, preserve the Pi's current calculations and outside/inside settings, and run the supplied tests. Do not deploy or modify Pi code."

## Which tool to use

Google's current documentation says Firebase Studio stopped new workspace creation on June 22, 2026 and sunsets March 22, 2027. **For a new project use Google AI Studio Build with Firebase**, or a local coding assistant such as Google Antigravity. Firebase Authentication, Firestore, and Hosting continue independently. An existing Firebase Studio workspace can still be used during the transition.

The browser builder may publish using Cloud Run rather than static Firebase Hosting. Start with the preview. For this client-only web app, request a static production build for Firebase Hosting when deployment is actually needed; do not add an unnecessary server-rendering or paid hosting dependency.

## Accounts and setup

- Use your Google account to own the Firebase project and enable Google Sign-In when ready. Invite teammates through their own Google accounts when collaboration is needed.
- No Apple developer enrollment or App Store submission is required for the web app.
- No Gemini runtime API key is required: AI helps write this app; golfer-facing AI generation is outside this build.
- No live Firebase project, deployment, authentication, or billing changes were made for this handoff.
- Keep project/location selection intentional. The AI Studio integration binds later services to the selected project/location.

The Firebase web configuration is client configuration, not an Admin SDK private key. Never place service-account JSON, device tokens, refresh tokens, or administrator credentials in frontend code or files sent as build context.

## What is included

| Folder or file | Purpose |
|---|---|
| `FIREBASE_AI_MASTER_PROMPT.md` | Paste this first; it specifies the app and implementation boundaries. |
| `PROJECT_CONTEXT.md` | Exact current Pi interfaces and new ZIP changes. |
| `contracts/` | Canonical shot model, API fixtures, source-to-app mapping, and future ownership design. |
| `app-core/` | Dependency-free JavaScript CSV import, normalization, revision handling, and statistics, with tests. These are real starter modules for a React/TypeScript app. |
| `firebase/` | Rules draft and backend contract. Rules deliberately prevent browser writes to shot/session/device data until an authenticated ingestion service exists. |
| `prompts/` | Separate Firebase and Pi integration prompts so demo success is not confused with completed cloud sync. |
| `reference/` | Unmodified current kiosk, range renderer, ball-flight model, and startup script for study. Do not execute these files in the web workspace. |
| `VALIDATION.md` | Checks performed here and checks still required. |
| `ENGINEERING_RECORD.md` | Status, risks, and next three actions. |

## Verify the supplied core

Install a current supported Node.js release on Windows if it is not installed. In the unzipped folder run:

```powershell
node --test app-core/shot.test.mjs
```

These tests do not need Firebase, radar, camera, npm dependencies, or the Pi. They do not establish physical measurement accuracy.

## Connection behavior

The Pi already broadcasts a Wi-Fi network. For immediate local results, join that network and open the existing Pi page. The uploaded code defaults to port 8000 and has `/range` and `/session.csv`; verify the real Pi address and running port.

For an initial cloud-data trial, download a session CSV from the Pi, then reconnect to internet and upload through a deliberately authenticated import feature after that backend has been built. Initially the generated UI can preview and normalize the file without uploading it. Automatic Pi-to-cloud upload comes later through an authenticated, durable outbox.

A hosted HTTPS page must not assume it can silently fetch the Pi's HTTP API. Opening the existing local page in Safari is a separate path. Joining the Pi hotspot does not automatically share the phone's cellular internet with the Pi.

Original project ZIP and all sensor/startup files remain unchanged. Deliver changes as downloadable files for review; no GitHub access is required.
