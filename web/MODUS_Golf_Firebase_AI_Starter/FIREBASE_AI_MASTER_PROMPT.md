# Build the MODUS Golf phone web app

Act as the implementation engineer for MODUS Golf, a Mississippi State ECE capstone launch monitor. Build a working app, with source files and tests, from this specification. Do not stop at a mock screenshot or proposal. Ask only for information that blocks implementation; use clear placeholders for unavailable Firebase configuration.

## Current system and boundaries

A working Raspberry Pi 5 computes shot metrics locally from OPS243 and IWR6843 radar plus an OV9281 camera trigger. It already displays results on an 800 by 480 touchscreen and broadcasts Wi-Fi that a phone can join. The actual current export is the October 22 MODUS-Golf ZIP, archive comment `d9aeafe49d657ffaf403b238ef239f69adc49564`. The export identifier is not an independently verified Git commit. Use PROJECT_CONTEXT.md and the attached source references as authority over older proposal documents or current OpenFlight examples.

The sound detector broke and has been temporarily removed, as confirmed by the team. Its replacement and return are future work. Camera-generated triggering is the current configuration. Show the sound sensor as temporarily unavailable, not connected or healthy, and do not require it for the app or show a system failure merely because it is absent. The code's `sound` trigger option also names the electrical pulse interface; it does not establish that the physical sound detector is present.

Primary sensor processing and ball-flight calculations remain on the Pi permanently. Cloud adds accounts, profiles, history, averages, comparisons, and other analytics. Do not move sensor fusion, spin estimation, or primary carry calculation into the cloud or phone.

Do not modify or execute Pi capture code, GPIO, networking, camera configuration, firmware, or startup scripts. Current startup defaults include OPS UART `/dev/ttyAMA0`, trigger input GPIO20, camera output GPIO21, and OPS reset GPIO23. Outside Golf uses full sensor, requested 60 FPS, recording off; Inside Golf uses binned sensor, requested 300 FPS, recording off. Requested FPS is not a measured delivered cadence. Preserve all of this. Do not switch the camera on or stream it continuously for the app.

The team repository is read-only. Do not commit, push, create pull requests, or change GitHub settings. Deliver source ZIPs or local files. Do not deploy, enable billing, or provision real services as part of the first demo step.

## App target

Build a responsive TypeScript/React web app suitable for iPhone Safari, a Home Screen web app, Windows Chrome, and an optional 800 by 480 display layout. Prefer a client-side app with a static build and Firebase modular Web SDK. If the workspace uses another existing framework, adapt without a wholesale rewrite. Do not add a backend or AI runtime solely to render the UI. Do not require an Apple Developer account, App Store distribution, Bluetooth, Gemini API calls, or simulator software.

Use cream backgrounds, deep green navigation, readable dark text, restrained gold accents, and accessible status text. Use metric cards, large values, clear units, readable touch targets, and a mobile bottom navigation. This is a practice tool, not a promotional landing page. Do not copy another project's branding or screenshots.

Four main sections:

1. **Practice:** latest shot, clear Ready/Processing/Disconnected states from the selected data adapter, ball speed, club speed, smash, VLA, HLA, and modeled carry. Show an optional top/side range plot only when genuine Pi trajectory points are supplied. Otherwise explain that the CSV contains metrics only. Hide or mark unavailable experimental spin and club path. Clearly distinguish Demo, imported history, and live device data. Do not invent a live connection.
2. **Sessions:** golfer, session, date, club filters; shot list and detail; CSV export; import preview; per-record provenance and quality flags. Handle at least 250 stored records without truncating statistics to the first page. Selecting a history filter must never change capture ownership.
3. **My Bag:** each club's mean carry, mean ball/club speed, mean smash, sample standard deviation, and metric-specific sample count. Show session comparisons and gaps between clubs only when samples exist. Label carry and derived landing patterns as modeled. Do not show measured dispersion from assumed direction.
4. **Settings:** account sign-in/out, golfer profiles under that account, units, device/local-page instructions, connection state, latest sync time, and pending-upload status only when actually available. Put profile management here. Never fabricate a battery percentage or sensor-health result.

Distinguish the signed-in account (Firebase UID) from a golfer profile ID and a physical device ID. A single account may hold multiple golfer profiles. These IDs are opaque and separate; never assume Firebase UID is a UUID.

## Exact current Pi interface

The current kiosk is plain HTTP, default port 8000, with:

- `GET /state`: `{state,shot,rev,metrics,video,camera,zone,view,focus,training}`. Metrics use `ball_speed`, `club_speed`, `smash`, `launch_angle`, `launch_dir`, `spin`, `carry`, optional `flight`, and `radar_pending`.
- `GET /history`: `{rev,shots}` with up to 30 in-memory flight objects. These include `shot`, a local `at` time, `ball_speed`, `launch`, `spin`, `direction`, `carry`, `apex`, `path`, `club`, `assumed`, and sometimes `test`.
- `GET /session.csv`: current run's persistent CSV.
- `GET /range`: current mobile-friendly range page.
- There is no Firebase auth, profile API, SSE endpoint, cloud ingestion endpoint, or durable global shot ID in that kiosk. Do not code against invented existing routes.

CSV header, exactly:

```text
shot,time,club,ball_speed_mph,club_speed_mph,smash,launch_deg,launch_measured,spin_rpm_used,carry_yd,apex_yd,ti_radar,ball_speed_raw_mph,launch_dir_deg
```

Important semantics:

- `spin_rpm_used` is the flight model's assumed input, not measured spin.
- `launch_deg` is a measured vertical angle only if `launch_measured` is `yes`; otherwise preserve it as a model input and leave the measured field null.
- `launch_dir_deg` is separately reported radar direction. The existing Pi flight call does not use it; the flight is modeled using assumed direction. Do not present the rendered spread as measured dispersion.
- Empty cells mean null. Numeric zero is valid for angles; never use `value || default` to replace it.
- CSV `time` is local logging time, not the precise impact time. The original filename has the session start date. Require the Pi timezone and resolve DST/midnight correctly before assigning UTC. Do not guess an impact timestamp or a timezone.
- Legacy import has no stable device identity or golfer attribution. Require both explicitly. Use stable IDs derived from device, original session filename, and shot number; an edited row updates/conflicts with that same shot rather than creating a duplicate. Existing ownership is immutable after import.

## Architecture and data contract

Use the supplied `contracts/shot.schema.json`, synthetic fixtures, and `app-core/shot.mjs`. Integrate the tested functions rather than writing a second incompatible normalizer. Preserve them as a framework-independent module. Add TypeScript declarations or adapters around them where helpful.

Separate UI from three adapters: `DemoRepository`, `FirebaseRepository`, and a future `LocalPiRepository`. Demo is selected explicitly and never writes to Firebase. Firebase reads only the authenticated user's records. A hosted HTTPS app cannot assume it can fetch a private Pi HTTP endpoint; CORS alone does not solve mixed content or browser local-network restrictions. For v1, offer the existing local Pi URL as a separate user-opened page and support file import preview. Never build a public server proxy that fetches arbitrary private Pi URLs.

Cloud paths are `users/{uid}/profiles/{profileId}`, `users/{uid}/sessions/{sessionId}`, `users/{uid}/shots/{shotId}`, and `users/{uid}/summaries/{summaryId}`. Device ownership is server-controlled under `devices/{deviceId}`. Device secrets are never client-readable. Final ingestion writes require a backend that authenticates the user or scoped device token and checks actual ownership. A client-provided owner UID is not authorization.

Start with clearly labeled synthetic demo data and editable local demo profiles. Add Google Sign-In and Firestore in a separate implementation step after the demo works. Do not silently use localStorage as fake authentication or fall back to demo after a real authentication failure. The starter Firestore rules are a conservative draft, not a production validation certificate. Do not weaken them to make the demo work.

The browser may compute statistics on downloaded records for preview. Label those as app-computed. Additional cloud computation is a later explicit implementation: Firestore aggregation queries or authenticated server-side analytics. Do not claim that client-side averages already implement cloud analytics. If using triggers, handle duplicate and out-of-order events; recomputation from authoritative shot revisions is preferable for a small capstone dataset.

## Correctness, privacy, and offline behavior

Missing data is null. Real numeric zero is preserved. Exclude synthetic, unknown, and processing attempts from real golfer statistics; demo statistics may deliberately opt into synthetic fixtures and remain visibly labeled. Count samples independently for each metric. Use sample SD (n minus 1); show unavailable for fewer than two samples. Do not average averages. Experimental spin is excluded from ordinary averages.

The same shot may receive late radar enrichment. Use `shot_id` plus monotonically increasing revision, upsert in place, ignore stale revisions, and detect conflicting duplicates. Reconnection does not create a new physical session or change its golfer. An offline queue deletes an item only after the server acknowledges that exact ID and revision.

Local capture must continue without a phone, cloud, or signed-in account. PWA offline history is a separate feature from direct Pi access. Cache app-shell assets only initially; do not indiscriminately cache authenticated API responses. Explain stale cached data and its as-of time. Clear private UI state and detach listeners on sign-out or account change. Add optional persistent record caching only after testing account isolation and logout behavior.

Do not allow browser controls to change the shooting golfer or club until the backend supports an acknowledged, trigger-time-safe change. Keep history filters separate from future capture controls. Never expose reset, shutdown, trigger, calibration, or camera-mutating actions from the reference kiosk.

## Deliver and verify

First deliver a running demo with all four sections and a local CSV preview, not just static visuals. Add a manifest, correctly sized icons, and installation guidance. Test layout at 390 by 844, landscape phone, desktop, and 800 by 480. Verify contrast, keyboard navigation, missing metrics, empty/error states, and long golfer/club names.

Run the supplied Node tests and extend them for imports, units, missing values, revisions, profile isolation, and source labels. Before enabling Firebase writes, run emulator tests for signed-out denial, another user's denial, permitted own-profile changes, denied direct shot/device writes, and verified backend ownership. Do not describe unrun emulator or hardware tests as passed.

List all changed files, exact run/test commands, required project settings, and remaining gaps. Return a downloadable source ZIP. Use separate steps for interface, Firebase connection, and Pi sync. A successful demo does not mean real hardware sync, deployment, power validation, or measurement accuracy has been completed.
