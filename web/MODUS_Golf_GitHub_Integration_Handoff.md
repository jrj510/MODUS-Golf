# MODUS Golf: GitHub implementation handoff

Prepared 2026-10-23. This file is intended to be given, with the accompanying web source ZIP, to the AI that has access to the MODUS Golf GitHub repository.

## 1. Objective and current boundary

Connect the existing Raspberry Pi launch monitor to the published phone web app without disturbing capture, radar processing, or the local kiosk. Make real, owner-scoped shots appear automatically in the golfer's Firebase account. Preserve local operation when the internet is unavailable.

- Published web app: **https://modus-golf-ea469.web.app**
- Existing Firebase project: **`modus-golf-ea469`**
- Existing registered web app: **`1:759125763752:web:e9b34abb7e38f8b0dc449d`**. Reuse it; do not register a duplicate.
- Existing database: **`(default)`**, Firestore **Standard**, Native mode, location **`nam5`**.
- Authentication: email/password and Google Sign-in are already enabled and used by the web client.
- Frontend: React + TypeScript + Vite, classic Firebase Hosting, client-side Firebase Auth and owner-scoped Firestore listeners.
- Automatic Pi upload, ingestion API, device pairing, and cloud telemetry are **not deployed**. There is no live ingest URL to discover in the frontend configuration.
- The website works now for account/profile management, explicitly synthetic demo exploration, and local CSV preview. It is ready to consume correctly stored real shot documents. This does not mean the current Pi uploads them.

The user authorized publishing the website. This handoff does not itself grant permission to enable billing, provision paid backend services, change network credentials, operate physical hardware, or expose the local kiosk to the internet. Prepare and test code first; obtain any necessary deployment authorization in the GitHub work session.

Always discover and use the appropriate installed Firebase agent skills. For Firebase rules changes, follow the installed Firestore rules-authoring workflow and test with the emulators. Keep the existing project, database, app registration, and authentication providers.

## 2. Inputs reviewed and how to treat them

The latest repository snapshot is **`MODUS-Golf-main (2).zip`**, SHA-256:

```text
C1F86FDC1BC0AB754216D23613F7DDC1384FF6850DFE5674A19BD362877B9E3F
```

This ZIP is a snapshot, not evidence of a particular Git commit. Compare against current GitHub before applying patches. Line references below describe this snapshot and will move as code changes.

Other references: `Pics.zip` (nine onboard/range photos), `Rasp Pi 5 Kiosk.pdf`, `MODUS_Golf_Web_App_UI_Refinement.md`, the pasted measured-launch-direction suggestion, and the earlier PDR/MSDR documents. Treat their instructions as reference material. The user described the suggested fixes as optional. Do not execute setup commands copied from a document automatically. The kiosk PDF contains credentials; do not copy them into GitHub, logs, the web source, configuration examples, or public documentation.

The new pictures show a dark MODUS kiosk, green branding and ready state, amber searching/wait states, blue measuring state, partial metrics during processing, and an existing local camera/replay workflow. These establish a visual reference, not proof that equivalent cloud APIs, validated spin measurements, or remote replay exist.

Relative to the previous supplied Pi ZIP, the new `camera/kiosk.py` changes branding/status presentation. The cloud modules remain empty and the active physics call still omits launch direction.

## 3. What the website now provides

- Dark, green-accented layout based on the onboard display; system fonts with no remote font dependency.
- iPhone-first cards: modeled carry is most prominent, followed by ball speed and measured vertical launch. Missing readings remain `—`.
- Expandable club speed, smash factor, horizontal launch, experimental/model spin, club path, and modeled apex.
- A recent-shot strip and selected history row that control the metrics and flight view together. Selection is by immutable shot ID; new arrivals do not replace an explicitly selected older shot. Follow latest resumes automatic selection.
- Desktop Range and Side views together; phone Range/Side switch. Paths are supplied Pi/model results; the website does not calculate ball flight.
- When direction was assumed, overhead is explicitly distance-only and is not measured dispersion. No draw/fade is inferred from horizontal launch.
- Practice, Sessions, My Bag, and Settings; golfer/club/session/date filtering; whole-filter statistics with per-metric counts and sample standard deviation; CSV export with provenance.
- Real Firebase account/profile management and private cloud subscriptions. Sign-out/account changes discard private in-memory state and listeners.
- Clearly isolated synthetic demo with supplied fixture paths. Demo data is never uploaded. The comparison session has no invented trajectory.
- Original Pi CSV preview runs locally and cannot upload directly. It requires explicit attribution and keeps unconfirmed data out of normal real-shot statistics.
- A separate link to the documented local Pi range page. The hosted HTTPS app does not fetch the Pi's private HTTP endpoints.
- Home Screen manifest and icons. Offline cold-start caching and real iPhone Home Screen Google sign-in have not been certified on physical hardware.

Cloud snapshot status is separate from capture readiness. The current website does not subscribe to a live device heartbeat, expose pairing controls, report upload queue depth, or fetch camera/replay content. Do not claim those features are connected merely because Firestore is connected.

## 4. Active Pi code: where to integrate

| File / location in supplied ZIP | Current behavior | Required integration work |
|---|---|---|
| `start_kiosk.sh`, around line 110 | Launches `camera/kiosk.py` | Preserve the working camera startup. Add uploader supervision separately. |
| `main.py` | Placeholder print | Do not assume this starts the production monitor. |
| `camera/kiosk.py`, `/state` around line 446 | Returns mutable current kiosk state/shot/revision/metrics | Keep local; not durable shot history or a cloud API. |
| `camera/kiosk.py`, `/session.csv` around line 479 | Exports current run's CSV | Preserve compatibility and original filename. |
| `camera/kiosk.py`, `/history` around line 490 | Keeps only 30 modeled flights | Do not poll this as the durable upload source. |
| `_session_path`, around line 672 | Lazily creates `logs/sessions/session_*.csv` | Retain local logs; introduce durable session identity before capture. |
| `_log_session`, around line 681 | Writes local-time CSV with no account/profile/UTC IDs | Keep legacy export; use a separate canonical outbox for cloud records. |
| `_publish`, around line 700 | Updates current UI from partial/final radar results | Build per-shot immutable snapshots independent of current UI state. |
| `_publish`, around line 704 | Returns early if `K.shot != shot` | Prevent this UI guard from discarding an older shot's durable final result. |
| `_publish`, around lines 720–721 | Stores TI horizontal launch as `m["launch_dir"]` | Preserve the actual measurement separately from model direction. |
| `_publish`, around line 755 | Calls `shot_flight` without direction | Optional physics fix in section 13. Not required to transport truthful data. |
| `_publish`, around lines 759–761 | Adds history and CSV once, only with ball speed | Queue a finalized canonical record independently; late enrichment increments its revision. |
| `add_radar_results`, around line 769 | Partial speed result, then later TI result | Preserve same-shot identity across both stages and asynchronous completion. |
| Capture completion / worker launch, around lines 1146–1178 | Increments local shot number and starts radar job | Freeze device/session/profile/club/capture-time context before asynchronous work. |
| `camera/ballflight.py`, `shot_flight` around line 99 | Already accepts `direction=None` | Copy its output and assumptions; no new browser physics. |
| `camera/range_page.py` | Polls local `/state` and `/history` | Keep as local UI. Clear currently clears the displayed overlay, not cloud history. |
| `cloud/database.py`, `cloud/api_client.py`, `cloud/upload_results.py` | Zero-byte placeholders | Implement durable queue, authenticated transport, and background worker. |
| `deployment/` | Supplied service/install helpers are placeholders | Add reviewed installation/supervision instructions; no automatic Pi reboot. |

Preserve current UART/GPIO assignments and capture presets. The configured OPS electrical trigger is not evidence that the removed physical sound detector is working. Inside/Outside modes are local capture/power choices. The supplied startup defaults disable recording for both, so do not promise replay solely because a mode label mentions it. Never publish the existing unauthenticated local control server or port 8000 to the internet.

## 5. Required architecture

```text
Camera / radar workers on Pi
  -> per-shot canonical snapshot
  -> durable local SQLite outbox
  -> background HTTPS uploader with scoped device credential
  -> authenticated ingestion service (not yet implemented)
  -> validated transactional write to Firestore
  -> users/{owner_uid}/shots/{shot_id}
  -> existing web listener -> selected shot / history / statistics
```

Do not upload from a frame loop or hold the camera/UI lock while making a network request. A slow or unavailable network must not block capture, radar processing, or kiosk rendering.

The Pi's hotspot only provides local connectivity. Cloud uploads additionally need a working upstream internet route. Verify that route on the actual installation; do not assume a phone connected to the hotspot automatically provides an internet bridge. Queue safely while offline.

### Authentication, pairing, and attribution

Implement an explicit device claim/pairing flow before accepting real uploads. A minimal deliverable includes a phone pairing page/section, backend pairing endpoints, and Pi enrollment/configuration tooling. The current web app has no pairing controls, so this requires coordinated frontend work as well as Pi/backend changes.

1. A signed-in human requests/claims a short-lived, single-use device pairing challenge over HTTPS. The backend verifies the Firebase **ID token**, derives its UID, and verifies the selected golfer profile exists under that UID. Do not trust a body-supplied UID. See [Firebase token verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens).
2. Require proof of physical/device possession, bind the challenge to the enrolling device, rate-limit attempts, expire the challenge, and consume it transactionally. Do not make knowing a predictable device ID sufficient to claim it.
3. Issue a revocable, device-scoped credential through the authenticated enrollment channel. Store only a secure verification hash server-side; keep the secret in a Pi-local permissions-restricted configuration file outside Git. Never put an Admin SDK/service-account key or a golfer's password on the Pi.
4. Persist authoritative owner UID, device ID, enrollment generation, and active capture profile on the server. Device authentication resolves this binding. Recheck revocation, owner, enrollment generation, and profile in each ingestion transaction.
5. Snapshot profile/club/session context before the shot triggers. Switching a history filter in the web app does not reassign capture ownership. A future explicit capture-profile change must be authenticated, acknowledged, and take effect at a defined next-shot boundary.
6. Device reassignment must not relabel queued shots. Old enrollment credentials and old queue context must be rejected or explicitly resolved under the previous owner. Never retry old shots into a newly claimed owner's namespace.

The account UID, golfer profile ID, device ID, session ID, and shot ID are separate identities. Names are presentation fields and may change without changing record identity.

## 6. Exact data contract the website reads

### Paths and ownership

```text
users/{firebase_auth_uid}/profiles/{profile_id}
users/{firebase_auth_uid}/shots/{shot_id}
users/{firebase_auth_uid}/sessions/{session_id}       # optional server summary
users/{firebase_auth_uid}/summaries/{summary_id}     # optional future analytics
devices/{device_id}                                 # non-secret registration
device_credentials/{credential_id}                 # server-only verifier
```

The shot document ID **must equal** its `shot_id`. The server chooses the owner namespace from verified credentials. The current website listens to the owner's complete `shots` collection and filters locally for the small capstone dataset. No new query/index is needed for the first integration. Plan pagination/aggregation before scaling substantially; do not silently compute statistics from a truncated page.

Profiles are created by the authenticated website with `display_name`, `created_at`, `updated_at`. The timestamps are Firestore server timestamps; renaming preserves `created_at`. The backend verifies profile existence and ownership before shot creation.

### Canonical Pi/API shape

The complete normative schema is included in Appendix A and in the source package at `MODUS_Golf_Firebase_AI_Starter/contracts/shot.schema.json`. Every required nullable field must be present with `null` when unavailable. Do not use empty strings, zero as a missing sentinel, `NaN`, Infinity, or missing required fields. Reject unknown core fields at the backend. Browser validation is a display boundary, not a substitute for backend validation.

This example is illustrative, not a real measurement or an upload instruction. Its shortened path illustrates axis order only; export the complete model path for real shots.

```json
{
  "schema_version": 1,
  "shot_id": "shot_deviceA_sessionA_000001",
  "session_id": "session_deviceA_opaqueUUID",
  "device_id": "device_opaqueUUID",
  "profile_id": "existingProfileDocumentID",
  "sequence_number": 1,
  "revision": 1,
  "timestamp": "2026-10-23T15:00:00.000Z",
  "club": "52",
  "record_kind": "real",
  "processing_state": "final",
  "ball_speed_mph": 84.3,
  "club_speed_mph": 66.1,
  "smash_factor": 1.28,
  "vertical_launch_angle_deg": 24.6,
  "horizontal_launch_angle_deg": -1.8,
  "carry_yards": 112,
  "carry_kind": "model",
  "spin_rpm": null,
  "club_path_deg": null,
  "trajectory": [[0,0,0],[56,19,0],[112,0,0]],
  "model_inputs": {
    "vertical_launch_angle_deg": 24.6,
    "spin_rpm": 7690,
    "horizontal_launch_angle_deg": 0
  },
  "quality_flags": ["spin_assumed", "flight_direction_assumed", "sensor_values_unverified"],
  "source": {
    "kind": "pi_live",
    "filename": "session_20261023_100000.csv",
    "local_log_time": "10:00:00",
    "timezone": null,
    "ti_radar": "Example status only",
    "ball_speed_raw_mph": null,
    "apex_yards": 19
  }
}
```

The example deliberately distinguishes measured HLA `-1.8` from model HLA `0`: that is valid for the current kiosk call that does not pass direction. Only claim direction was applied after it actually was.

### REQUIRED: Firestore storage differs for trajectory points

**Standard Firestore rejects directly nested arrays.** Do not write `[[x,y,z], ...]` to a document. See [supported Firestore data types](https://firebase.google.com/docs/firestore/manage-data/data-types).

Validate the canonical API object first, then encode just its `trajectory` field for Firestore:

```python
def shot_to_firestore(canonical_shot):
    stored = dict(canonical_shot)
    path = canonical_shot["trajectory"]
    stored["trajectory"] = None if path is None else [
        {"forward_yards": x, "height_yards": y, "right_yards": z}
        for x, y, z in path
    ]
    return stored
```

Stored example field:

```json
"trajectory": [
  {"forward_yards": 0, "height_yards": 0, "right_yards": 0},
  {"forward_yards": 56, "height_yards": 19, "right_yards": 0},
  {"forward_yards": 112, "height_yards": 0, "right_yards": 0}
]
```

The supplied website's `src/domain.ts::validateCloudShot` already decodes these exact three-key point maps back into canonical tuples and validates their finite values. It also supports canonical tuples in local fixtures. Do not rename point keys, change units, serialize the field as a string, or write arbitrary point objects. Null paths remain null. Keep delivery metadata outside the strict core schema, for example in a server-only separate record keyed by shot ID.

The core `timestamp` field is a known UTC **ISO 8601 string or null**, not a Firestore Timestamp object. Server receipt time is a different fact; keep it in backend metadata. Do not use server receipt time as impact time. For new captures, record a trustworthy UTC event timestamp only if the Pi clock is synchronized and its event meaning is documented. Otherwise send null and add `no_impact_timestamp`; retain local log time/timezone separately.

### Metric mapping and provenance

| Canonical field | Pi origin / rule |
|---|---|
| `ball_speed_mph` | `m.ball_speed`, corrected value if correction actually ran |
| `source.ball_speed_raw_mph` | `m.ball_speed_raw`, otherwise null; do not invent a raw reading |
| `club_speed_mph` | Accepted `m.club_speed`; leave rejected/unavailable reading null |
| `smash_factor` | Accepted same-shot `m.smash`; not a ratio across different shots |
| `vertical_launch_angle_deg` | Measured `m.launch_angle` only. Club default belongs in model inputs, not this field. |
| `horizontal_launch_angle_deg` | Measured `m.launch_dir`, including valid zero, otherwise null |
| `carry_yards` | Existing `f.carry` from the actual flight result; canonical value shared across all web views |
| `source.apex_yards` | Existing `f.apex` from that same flight result |
| `trajectory` | Existing `f.path`, `[forward, height, right]`, all in **yards**, then map-encoded for Firestore |
| `model_inputs.vertical_launch_angle_deg` | Actual `f.launch` used by this model invocation |
| `model_inputs.spin_rpm` | Actual `f.spin` used by the model; typical spin remains estimated |
| `model_inputs.horizontal_launch_angle_deg` | Actual `f.direction`, not automatically the measured HLA |
| `spin_rpm` | Null by default. Populate only a separately identified experimental reported value with an experimental flag; never copy `spin_rpm_used` into it. |
| `club_path_deg` | Null unless a separate validated/reportable source exists. HLA is not club path. |

Set `launch_assumed`, `spin_assumed`, and `flight_direction_assumed` from `f.assumed`. Use `source.kind="pi_live"` for newly exported physical captures, `record_kind="real"` only for physical shots, and `processing_state="final"` only after that record's processing completes. Mark sensor validity honestly. Missing measurements must not inherit the last shot's values. Do not mark `/testshot`, SWINGTEST, simulator/demo records, or fixture records as real.

`carry_kind` stays `model`, even when launch inputs were measured. The original Pi rounds kiosk `m.carry` more coarsely than `f.carry`; choose the canonical `f.carry` and apply only display rounding in clients. Do not alter the flight solver to make screenshots agree. A side readout, metric card, CSV export, and selected row must all use the same canonical shot carry. Unit conversion belongs at display boundaries; stored speeds are mph, angles degrees, distance/path yards.

Keep absent trajectory null for legacy CSV. The website deliberately refuses to render a trajectory attributed to `legacy_csv`; the old CSV does not contain path points.

### Identity and revisions

- Generate a persistent opaque device ID once at enrollment, not on each boot.
- Create a persistent session UUID before its first shot. Local shot counters and wall-clock filenames alone are insufficient across reboots/devices.
- Allocate immutable shot ID, sequence, profile, device, session, club, and timestamp context once. Persist before asynchronous work. IDs must match `[A-Za-z0-9_-]{1,120}`; club length is 1–24.
- `revision` is a monotonically increasing **per-shot** integer, starting at 1. It is not global `K.rev`.
- A `processing` revision may have nullable metrics; a later `final` revision enriches the same document. Never create a second shot to represent late TI results.
- If a processing revision is exposed, it must contain only that shot's partial data, not previous finalized metrics. It remains out of normal statistics.
- Lower revisions cannot overwrite higher ones. Identical same-revision retries succeed idempotently. Different content at the same revision is a conflict. Compare a canonical normalized payload hash, not map key order or client-only document ID metadata.
- Session, device, profile, owner binding, sequence, and event identity are immutable after creation. Reject attempted reassignment. Keep all queued revisions bound to the enrollment/profile snapshot that produced them.

## 7. Implement the Pi outbox and worker

### `cloud/database.py`

Use SQLite (standard library is sufficient) for local sessions, per-shot context, revision allocation, payload/hash, enrollment generation, pending/acknowledged revisions, retry schedule, and last classified error. Transactionally persist a snapshot before scheduling upload. Acknowledgement of revision N must never delete a queued revision N+1. Avoid unlimited WAL/log growth; handle storage-full errors visibly while preserving capture responsiveness and already saved records.

Queue state must survive kiosk restart, network loss, worker restart, and Pi power loss to the extent local durable storage permits. Use bounded disk retention with explicit operator handling; never silently discard unsent shots. Keep credentials separately from normal shot data and logs.

### Capture integration in `camera/kiosk.py`

Introduce a small export boundary, e.g. `record_partial(context, result)` / `record_final(context, result)`, behind a local queue module. It receives an immutable snapshot, not mutable `K.metrics` or pointers to current args. Do not perform HTTPS under `K.lock`.

Decouple durable result construction from the early-return UI guard in `_publish`. A result for shot A that completes after shot B starts still finalizes/queues A, but must not overwrite B's screen. Refactor carefully: per-shot radar results and frozen context must be sufficient to build A without reading B's metrics/club/profile. Test this with fake radar workers before touching hardware.

Do not use `/state` polling, the 30-item history ring, or periodically rereading only the last CSV row as the primary upload mechanism. Finalization without a valid ball speed should yield a failed or incomplete record with nulls and meaningful quality flags, not a fabricated carry.

Keep legacy CSV output compatible. As a separate optional cleanup, replace manual comma joining with `csv.writer` so radar error strings containing commas/quotes cannot corrupt exports. Preserve exact column order, original filename and newline-terminated snapshots.

### `cloud/api_client.py`

HTTPS only, normal certificate verification, explicit connection/read timeouts, bounded request bytes, a configured ingest base URL, and scoped device credential. No token/password in query parameters or logs. Classify retryable timeouts/5xx/429 separately from invalid payloads, revoked credentials, and ownership conflicts. Respect retry hints, back off exponentially with jitter and a maximum delay, and quarantine invalid records for operator review rather than retrying forever.

### `cloud/upload_results.py`

A separately supervised background worker drains the outbox. Commit success means the backend has acknowledged the durable Firestore write for that shot ID/revision/hash. HTTP connection success alone is not acknowledgement. Keep queue mutations transactional. Do not upload images/video as part of shot metrics. Provide a small local status interface for enrollment state, pending count, and classified last error without exposing secrets.

Add a reviewed service unit/install guide in `deployment/`; use an unprivileged service user and persistent writable data directory. Avoid launching a second camera/kiosk instance. Do not add destructive migration, credential changes, `git pull`/reboot, or desktop/network changes to automatic installation steps without the operator's explicit approval.

## 8. Implement ingestion backend and pairing UI

Suggested API names below are a proposed interface, **not existing hosted routes**:

| Proposed operation | Caller / authorization | Purpose |
|---|---|---|
| `POST /v1/pairing/challenges` | Authenticated human + device possession flow | Begin a short-lived enrollment |
| `POST /v1/pairing/claims` | Verified Firebase ID token | Bind device to owner/profile and consume challenge |
| `POST /v1/devices/enroll` | One-time device enrollment proof | Exchange proof for revocable scoped credential |
| `POST /v1/shots:upsert` | Scoped device credential | Validate and commit one shot revision |
| Authenticated profile/session control | Owner authorization + device acknowledgement | Explicit future capture profile selection |

Finalize the protocol coherently; the exact endpoint names may change as long as Pi client, backend, pairing page, and tests use the same versioned contract. Never route an unimplemented API name through the SPA fallback and treat its returned HTML as an ingest response.

Example single-shot request envelope:

```json
{"protocol_version":1,"enrollment_generation":1,"shot":{"schema_version":1,"...":"full canonical shot object from section 6"}}
```

This abbreviated envelope is explanatory, not a valid schema fixture. Add transport metadata outside the core shot. The device credential is in an authorization header. The backend independently resolves UID/device identity, validates enrollment and profile, enforces that the payload device matches the authenticated device, validates the full schema and model/provenance semantics, and transactionally compares identity/revision/hash before writing the map-encoded shot.

Successful acknowledgement example:

```json
{"shot_id":"shot_deviceA_sessionA_000001","revision":1,"payload_sha256":"CANONICAL_PAYLOAD_HASH","status":"committed"}
```

Return success for an identical retry, an explicit conflict for different content at the same revision, and an unambiguous stale-revision outcome including the stored revision. The worker must never overwrite a newer revision or clear unsent newer content from its queue. Define invalid/unauthorized/revoked outcomes precisely and test them. Limit payload and batch sizes; a single-shot API is enough initially. Do not echo credentials, frames, or private account details in errors.

Use the Admin SDK only in a trusted backend environment with managed application credentials. Admin writes bypass Firestore rules, so the backend's authentication, ownership checks, schema validation, and transactional idempotency are mandatory. Keep existing browser shot/session/device write denial. Do not change rules to `allow write: if request.auth != null` to make uploading easier.

Implement and test locally before choosing a deployed Cloud Run/Functions service. Deployment needs a real HTTPS base URL, runtime identity/least-privilege access, necessary API/billing review, and configuration of the Pi and pairing UI. Do not add a fake endpoint to `src/firebase.ts`.

## 9. Bring the website source into GitHub

Use **`MODUS_Golf_Web_App_Refined_2026-10-23.zip`**, supplied with this handoff. The built public website does not include source, tests, or backend code. The photos/PDFs/review workspace and their credentials are excluded from the source ZIP.

Recommended repository arrangement:

```text
camera/                    # existing Pi code
radar/                     # existing radar code
cloud/                     # Pi queue/client/worker
backend/                   # new trusted ingestion/pairing service
deployment/                # reviewed device service/deploy guidance
web/                       # extracted web source, package.json, src/, public/, tests/
  MODUS_Golf_Firebase_AI_Starter/  # retain contracts, app-core, fixtures, rules
  firebase.json
  firebase.emulator-test.json
docs/MODUS_Golf_GitHub_Integration_Handoff.md
```

The starter folder contains older prompts and historical `reference/` Pi code; do not replace current GitHub hardware files with those references. This handoff describes the current integration boundary. Keep the original starter folder alongside `web/src` because existing TypeScript imports reference `../MODUS_Golf_Firebase_AI_Starter/...`. Do not copy only `src/` or overwrite the Pi's Python requirements with frontend dependencies. Retain package-lock and run `npm ci` from `web/`.

The provided `web/firebase.json` uses `hosting.public="dist"` and its Firestore rules path is relative to that folder. Run deployment from **`web/`**. If moving Firebase config to repository root instead, change public to `web/dist` and fix the rules path deliberately. Do not run build/deploy in an empty Cloud Shell home directory; it needs the checked-out web package and Firebase config.

```bash
cd web
npm ci
npm test
npm run build
npx -y firebase-tools@latest deploy --only hosting --project modus-golf-ea469
```

Use an active Node LTS release; this source was validated on the local bundled Node runtime. Do not force a major SDK upgrade or regenerate the lockfile as part of copying source. The sign-in entry loads separately from the practice workspace/Firestore SDK to reduce initial phone download work. Preserve these lazy-loading boundaries and test sign-in and workspace transitions.

Existing rules are in `web/MODUS_Golf_Firebase_AI_Starter/firebase/firestore.rules`. They allow owner profile creation/rename and owner history reads; shot writes and credential reads are denied to browsers. No rules change is required just to support backend-authored shot documents. Deploying only Hosting does not deploy rules or backend code. If rules change later, use skill-guided authoring and emulator tests before an explicit rules deployment.

For optional GitHub Actions CI/CD, add tests/build first; use properly scoped managed deployment credentials and repository secrets/identity federation. Never commit a downloaded service-account JSON or expose server credentials as `VITE_*` values. The Firebase web SDK configuration is public configuration, not a device enrollment credential.

## 10. Device telemetry and media: separate follow-up scope

The first working milestone needs pairing, upload and history, not remote camera control. For future telemetry, define a nonsensitive owner-readable device status document and a frontend subscription keyed by a verified device ID. Existing device rules permit owner `get`, not collection listing; the current app does not watch device documents. Adding backend heartbeat writes alone will not create UI status.

Define timestamps and expiration for heartbeat, queue count, capture state, mode, capabilities, and sensor availability. Display stale/unknown explicitly. Kiosk Ready is different from network connected, backend received, or Firestore snapshot confirmed. Missing sound hardware remains unavailable; do not report it as a sensor fault just because it is intentionally absent.

Local camera/training/replay pages stay local. Hosted media would require a separately authorized private media transport, access control, storage/lifecycle policy, capability flags and real URLs. Do not fabricate stream URLs or expose unauthenticated `/quit`, `/testshot`, delete, or camera controls. Do not claim Outside/Inside guarantees a recording.

## 11. Legacy CSV backfill is optional and explicit

The existing website preview is not an upload path. If adding server-side backfill later, preserve original `session_YYYYMMDD_HHMMSS.csv` filename, explicit device ID and golfer profile, verified Pi timezone when known, and explicit real-shot confirmation. Legacy log time is not a known UTC impact timestamp. Unknown records remain `record_kind="unknown"` and out of real statistics.

Reuse the exact normalizer and stable ID algorithm in `MODUS_Golf_Firebase_AI_Starter/app-core/shot.mjs`, or demonstrate cross-language equivalence with its fixtures/tests:

```text
session_id = stableId("session", [deviceId, originalFilename])
shot_id    = stableId("shot", [deviceId, originalFilename, originalShotNumberString])
row_sha256 = stableId("row", CSV_COLUMNS.map(column => originalRow[column]))
stableId(prefix, parts):
  prefix + "_" + lowercase_hex(SHA256(UTF8(JSON.stringify([prefix, ...parts]))))
```

Retain JSON array element types, compact encoding, exact CSV column order, quoting semantics, and whole-file validation. Renamed files, guessed timezone, or new hashes must not silently create duplicate physical shots. Decide reconciliation between live UUID IDs and legacy hash IDs before backfill; do not import the same live-captured session again as unrelated legacy shots. Browser history CSV export has additional provenance columns and is not the original Pi CSV import format.

## 12. Acceptance tests and staged rollout

Before hardware installation, use fake camera/radar sources and Firebase Auth/Firestore emulators under a `demo-*` project. Never seed synthetic test records into the user's real shot collection.

1. Validate the entire canonical payload, enums, ID patterns, bounds, nullability, unique quality flags, maximum path length, finite point coordinates, and forbidden unknown fields. Verify Firestore map encoding and client decoding end-to-end.
2. Verify valid zero HLA/VLA survives. Missing measurement remains null; default launch/spin/direction remains in model inputs with assumption flags.
3. Enroll device A under user A/profile A. A real final upload appears once in A's account and nowhere in user B's account. Body-supplied owner/device/profile substitutions, expired challenge, replayed claim, revoked credential, and old enrollment generation must fail.
4. Retry the same revision repeatedly: one document and one statistics sample. Lower revision cannot replace higher revision. Conflicting same-revision payload fails. Acknowledging an earlier revision cannot erase a later queued revision.
5. Complete shot A after B starts: both records finalize correctly, each with frozen club/profile/context; B's current kiosk UI is not overwritten by A. No previous-shot metric leaks into a processing record.
6. Cut internet during capture and restart worker/Pi: local capture continues and queued records survive; restoring upstream drains the queue exactly once logically. Test disk-full and poisoned-record isolation.
7. Write at least 250 emulator records across profiles/sessions with missing metrics. Recall ten randomly chosen IDs and verify metrics/counts/means/sample SD against the entire eligible dataset, not the visible table page.
8. Select an earlier shot on the phone, then upload a newer shot and enrich the selected shot. Selection stays on its ID and refreshes its own revision. Follow latest moves to the newest; Range/Side toggling retains selection; carry agrees everywhere.
9. Sign out and switch accounts: prior account records/listeners disappear. Demo never uploads, invalid cloud data never silently switches to demo, browser direct shot writes remain denied.
10. Check physical iPhone Safari in portrait and landscape, keyboard-open sign-in/profile forms, Google popup/redirect, Home Screen launch, safe-area bottom navigation, pinch zoom, and CSV import/export. Test narrow 320 CSS-pixel layouts and actual touch targets. Desktop browser resizing is useful but does not certify physical iOS behavior.
11. Verify local kiosk capture modes, trigger/radar timing, UART/GPIO, CSV export, and local training/replay still work after install. Measure physical impact-to-phone latency only with real hardware and known clocks; do not equate emulator time or server receipt time with impact latency.

Suggested rollout: reviewable code + emulator tests -> staging/backend deployment with explicit authorization -> one enrolled device/profile and a few real shots -> offline/restart check -> phone field test -> broader use. Preserve a reviewed rollback to the prior kiosk and disable the uploader independently if needed.

The supplied website build passes **33 domain/view-model tests plus 11 Auth/Firestore emulator tests** (44 total). Production build passes; release notes record the final chunk sizes. These checks do not test real radar accuracy, hardware latency, newly proposed ingest endpoints, or physical iPhone sign-in.

## 13. Optional fixes: do not mix with minimum connectivity

### Pass measured launch direction to existing flight model

Verified in this ZIP: TI direction is already saved in `m["launch_dir"]`; `shot_flight` accepts `direction`; the current kiosk caller omits it. Optional change near `camera/kiosk.py:755`:

```python
f = shot_flight(
    m["ball_speed"],
    club,
    launch_angle=m.get("launch_angle"),
    direction=m.get("launch_dir"),
)
```

Pass `None` through when unavailable. Do not replace it with zero before the call: the function uses `None` to record that direction was assumed, while a measured zero is a valid applied direction. Do not pass experimental measured spin into the solver as part of this change; preserve its current typical-spin behavior.

Add pure model tests at +5°, -5°, zero and None. Verify right-axis signs against the actual TI installation before changing a sign. Check lateral position, unchanged missing-value behavior and assumption flags. Horizontal launch alone does not establish spin-axis curvature, hook/slice, draw/fade, or actual measured dispersion. The website does not implement this physics change; it faithfully displays the path/provenance it receives.

### Investigate kiosk/range carry disagreement before changing math

One supplied kiosk photo shows 112 yd and a range photo shows 102 yd alongside similar launch numbers. The pictures do not establish identical event identity, solver revision, selected club, assumptions, calibration or input time. First attach stable shot ID and model context to both local views and log canonical `f.carry`. Reproduce using the same shot/inputs. Do not alter physics or create a second frontend carry calculation to force screenshot agreement.

### Other optional improvements

- Standards-compliant CSV quoting (`csv.writer`) with compatibility tests.
- Review truthiness checks separately where valid zero values must be preserved; avoid a broad untested sensor/model refactor.
- GitHub preview deploys/CI, frontend lazy loading, scalable aggregate queries, and private media only after minimum secure upload works.
- Keep local Clear as a visual-overlay action. Cloud deletion requires an explicit separately authorized backend feature; do not map it to deleting stored shots.

## 14. Completion checklist for the GitHub AI

### Required for real automatic shots in the current website

- [ ] Import accompanying frontend source into GitHub with working build paths and existing Firebase configuration.
- [ ] Implement paired owner/profile/device binding and coordinated authenticated phone pairing UI.
- [ ] Implement per-shot immutable context and durable local queue; decouple history export from current UI guard.
- [ ] Implement independently supervised HTTPS uploader, revision-aware acknowledgement and offline recovery.
- [ ] Implement and test trusted ingestion with schema validation, owner checks, revocation and transactional idempotency.
- [ ] Encode trajectory as point maps in Firestore; retain tuples only for canonical API/local files.
- [ ] Preserve nullable measurements, actual model assumptions, source classification and exact canonical carry.
- [ ] Keep browser shot writes denied and credentials out of source/frontend/Pi Admin SDK.
- [ ] Deploy a real approved ingest service, configure endpoint/enrollment, verify upstream network and one real physical shot on iPhone.
- [ ] Report tests, changed paths, deployment URL/configuration, and remaining hardware/iOS limitations in a reviewable PR.

### Optional, separately reviewable

- [ ] Measured direction passed to existing flight model with tests and verified sign.
- [ ] Carry disagreement reproduction/diagnostics.
- [ ] Legacy CSV backfill/reconciliation, telemetry subscription, private replay/media, scalable analytics, CI/CD.

## Appendix A: complete canonical shot JSON Schema

The following is the canonical Pi/API contract. Apply the explicit point-map storage transform in section 6 before a Standard Firestore write. Do not validate the map-encoded storage object as if it were this tuple-based API object.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.invalid/modus/shot-v1.schema.json",
  "title": "MODUS app shot v1 proposed contract",
  "description": "Proposed app contract, not an API already served by the current Pi. Missing measurements are null. All fixture records are synthetic.",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "shot_id", "session_id", "device_id", "profile_id", "sequence_number", "revision", "timestamp", "club", "record_kind", "processing_state", "ball_speed_mph", "club_speed_mph", "smash_factor", "vertical_launch_angle_deg", "horizontal_launch_angle_deg", "carry_yards", "carry_kind", "spin_rpm", "club_path_deg", "trajectory", "model_inputs", "quality_flags", "source"],
  "properties": {
    "schema_version": {"const": 1},
    "shot_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,120}$"},
    "session_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,120}$"},
    "device_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,120}$"},
    "profile_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,120}$"},
    "sequence_number": {"type": "integer", "minimum": 1},
    "revision": {"type": "integer", "minimum": 1},
    "timestamp": {"type": ["string", "null"], "format": "date-time", "description": "Known UTC shot timestamp only. Legacy log time is preserved separately and does not become an invented impact time."},
    "club": {"type": "string", "minLength": 1, "maxLength": 24},
    "record_kind": {"enum": ["real", "synthetic", "unknown"]},
    "processing_state": {"enum": ["final", "processing", "failed"]},
    "ball_speed_mph": {"type": ["number", "null"], "minimum": 0, "maximum": 250},
    "club_speed_mph": {"type": ["number", "null"], "minimum": 0, "maximum": 200},
    "smash_factor": {"type": ["number", "null"], "minimum": 0, "maximum": 2},
    "vertical_launch_angle_deg": {"type": ["number", "null"], "minimum": -30, "maximum": 90},
    "horizontal_launch_angle_deg": {"type": ["number", "null"], "minimum": -90, "maximum": 90},
    "carry_yards": {"type": ["number", "null"], "minimum": 0, "maximum": 500},
    "carry_kind": {"const": "model"},
    "spin_rpm": {"type": ["number", "null"], "minimum": 0, "maximum": 30000, "description": "Never populate from CSV spin_rpm_used. Any future experimental value needs corresponding flags and remains outside normal averages."},
    "club_path_deg": {"type": ["number", "null"], "minimum": -90, "maximum": 90},
    "trajectory": {"type": ["array", "null"], "maxItems": 1000, "description": "Optional Pi-computed [forward, height, right] points in yards. CSV exports do not contain these points.", "items": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}}},
    "model_inputs": {"type": "object", "additionalProperties": false, "required": ["vertical_launch_angle_deg", "spin_rpm", "horizontal_launch_angle_deg"], "properties": {
      "vertical_launch_angle_deg": {"type": ["number", "null"], "minimum": -30, "maximum": 90},
      "spin_rpm": {"type": ["number", "null"], "minimum": 0, "maximum": 30000},
      "horizontal_launch_angle_deg": {"type": ["number", "null"], "minimum": -90, "maximum": 90}
    }},
    "quality_flags": {"type": "array", "maxItems": 32, "uniqueItems": true, "items": {"type": "string", "maxLength": 100}},
    "source": {"type": "object", "additionalProperties": false, "required": ["kind"], "properties": {
      "kind": {"enum": ["legacy_csv", "pi_live", "synthetic_demo"]},
      "filename": {"type": "string", "pattern": "^session_[0-9]{8}_[0-9]{6}\\.csv$"},
      "local_log_time": {"type": "string", "pattern": "^[0-2][0-9]:[0-5][0-9]:[0-5][0-9]$"},
      "timezone": {"type": ["string", "null"], "maxLength": 100},
      "row_sha256": {"type": "string", "pattern": "^row_[a-f0-9]{64}$"},
      "ti_radar": {"type": "string", "maxLength": 1000},
      "ball_speed_raw_mph": {"type": ["number", "null"], "minimum": 0, "maximum": 250},
      "apex_yards": {"type": ["number", "null"], "minimum": 0, "maximum": 300}
    }}
  }
}
```
