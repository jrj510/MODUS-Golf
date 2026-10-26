# MODUS Golf app handoff engineering record

Date: October 23, 2026 UTC. Source baseline: supplied October 22 ZIP. Evidence levels below separate source inspection, user reports, and proposed work.

## CURRENT STATE

The team reports a working integrated prototype and a usable battery setup in its current mode. This session prepares a phone web-app build handoff while preserving primary shot processing on the Pi. The sound detector broke and has been temporarily removed; replacement and restoration are planned. Current startup source uses the camera-generated trigger path.

## WHAT WAS VERIFIED

The new ZIP contains 42 files; five differ from the previous supplied snapshot. The current startup script, kiosk, model, range UI, API routes, CSV header, and placeholder cloud modules were inspected. Import/statistics/revision helpers and synthetic fixtures passed the 22 supplied tests. These are software checks, not hardware measurements.

## REPOSITORIES INSPECTED

Local uploaded `jrj510/MODUS-Golf` snapshots were compared. No successful current remote MODUS repository audit is claimed. The installed external OpenFlight revision is unknown. No external launch-monitor app code was ported into this handoff; current MODUS kiosk and range files are included unmodified as the closest implementation reference.

Official Google/Firebase documentation was checked for the builder lifecycle and Firebase integration. Firebase Studio no longer accepts new workspaces; a new build should use Google AI Studio Build with Firebase, or an existing local coding environment.

## WHAT CHANGED LOCALLY

Created this separate handoff directory: master prompt; staged cloud/Pi prompts; exact source context; proposed shot schema and mapping; synthetic CSV, API, and normalized app fixtures; dependency-free JavaScript helpers and TypeScript declarations; Firestore rules draft; source references; and validation notes. No uploaded source file was edited.

## REMOTE GITHUB CHANGES

NONE.

## TEST RESULTS

22 Node tests passed, zero failed. Packaging checks and a test rerun on the extracted delivery verify the handoff boundary. No Firebase emulator, UI, deployment, or live-hardware test was run. See VALIDATION.md for limits.

## CURRENT HARDWARE STATUS

- Raspberry Pi 5: installed and working per team; no live shell accessed here.
- Display: existing local UI works per team; 800 by 480 remains the target.
- OPS243-A: source configures UART `/dev/ttyAMA0`; no new communication measurement.
- IWR6843: source integration present; installed firmware, dependency revision, geometry, and accuracy not verified here.
- Sound Trigger: broken and temporarily removed per team; replacement planned. Its absence must not block the app.
- OV9281: camera-trigger path in current source. Outside full sensor/60 requested FPS; inside binned/300 requested FPS; both recording off. Delivered cadence not measured here.
- Power: current setup works on the battery per team. No runtime or electrical margin measured here; upgrade remains future work.

## OPEN PROBLEMS

Build and review the actual phone UI; select Firebase project/location; implement and emulator-test ownership and ingestion; then add optional durable Pi sync. Record current radar geometry and measurement validation separately. Replace and verify the sound detector before restoring its physical trigger path.

## NEW FINDINGS

Camera-trigger GPIO21 feeds the pulse interface; the code option named `sound` does not imply that a sound detector is physically present. GPIO20 is the configured trigger input, superseding older GPIO17 comments. Primary carry is modeled from assumed spin; separate reported HLA is not used by the current flight call. The app must preserve these distinctions and must not present modeled dispersion as a measured landing pattern.

## RISKS / UNKNOWNS

The uploaded ZIP does not identify the installed external OpenFlight commit. Existing local endpoints have no cloud account ownership or durable global shot IDs. CSV lacks impact timestamps and explicit golfer identity. The Pi hotspot is not evidence of a Pi internet route. Starter rules are deliberately restrictive but have not been emulator-tested. Cloud costs depend on the eventual services and workload; no free-tier guarantee is made.

## NEXT 3 ACTIONS

1. Paste FIREBASE_AI_MASTER_PROMPT.md into Google AI Studio Build and supply the context/core/fixtures. Build the explicitly labeled demo and CSV preview first.
2. Return the generated app source ZIP for review of its interfaces, source labels, mobile layout, and test results before connecting real golfer data.
3. Use prompts/02_CONNECT_FIREBASE.md to implement Google Sign-In, profiles, and ownership-tested backend ingestion; only then use prompts/03_CONNECT_THE_PI.md for optional after-session sync.

## EXACT COMMANDS TO KEEP

From the extracted handoff root on Windows:

```powershell
node --test app-core/shot.test.mjs
```

No command in this handoff needs to run on the working Pi now.

## LOCAL FILES CREATED / UPDATED

All delivered files live inside the separate MODUS Golf Firebase AI starter package. `reference/` contains four byte-identical source copies; all other files are app handoff material created locally. The original source ZIP and team GitHub remain unchanged. The standalone master-prompt download duplicates the prompt inside the package for convenient copying.
