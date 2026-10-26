# Validation record

Prepared October 23, 2026 UTC against the supplied October 22 source snapshot. This is a prompt and starter-code handoff, not a deployed or visually tested application.

## Passed here

- 22 Node tests passed, zero failures: strict CSV parsing and bounds; null versus zero; modeled versus reported metrics; no invented impact timestamps; stable import IDs; whole-file rejection; stale/conflicting revisions; immutable ownership; metric-specific counts and sample SD; profile isolation; synthetic exclusion; and packaged demo consistency.
- All 12 normalized fixture shots match the supplied CSV importer and are explicitly synthetic. The demo API fixtures contain finite model trajectory points and identify the sound detector as temporarily removed.
- Source references are checked byte-for-byte against the uploaded source. JSON files and the original ZIP hash are checked during packaging. These checks do not constitute full JSON Schema validator conformance.
- The final ZIP is extracted into a separate verification directory and the same 22 tests are run from the extracted copy before delivery.

Exact repeatable core check, from the package root:

```powershell
node --test app-core/shot.test.mjs
```

Node 20 or later is required. No npm install, Firebase connection, credentials, Pi, or sensors are required for these tests.

## Not run or implemented here

- No live Pi, camera, radar, battery, trigger, accuracy, or timing test. The working battery/setup status is team-reported.
- No generated app UI, browser layout, PWA installation, iPhone interaction, or Safari local-network test.
- No Firebase emulator, Authentication, Firestore authorization, server ingestion, production deployment, billing, or cost validation. `firebase/firestore.rules` is an unexecuted starter draft. Run `firebase/RULES_TEST_PLAN.md` before deployment.
- No automatic Pi upload, durable outbox, production device pairing, cloud analytics execution, or native iPhone app.
- No full JSON Schema validation engine or TypeScript build was run. The app builder must add these checks to its actual project.

The app builder must provide its own run/test evidence and list remaining gaps. Passing these starter-core tests says nothing about physical measurement accuracy or app/cloud completion.
