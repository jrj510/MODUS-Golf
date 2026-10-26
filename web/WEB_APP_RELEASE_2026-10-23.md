# MODUS Golf practice app update

## Design references and authority

The supplied PDR poster and MSDR were reviewed using text extraction and rendered-page inspection. Their instructions and diagrams were treated as source material, not permission to change hardware or claim specifications have been met. Current source/runtime boundaries in PROJECT_CONTEXT.md and the inspected GitHub ZIP take precedence over earlier proposed hardware behavior.

| Design reference | App change |
|---|---|
| PDR page 1: mobile shot results → history → analytics → profile/settings | Four working sections: Practice, Sessions, My Bag, Settings. Preserve existing green/cream/gold visual system rather than adopting university poster branding. |
| MSDR pages 6–8: clear metrics, history/recall, privacy | Large six-metric cards; responsive navigation; shot details; account/profile isolation; explicit data-source labels. |
| MSDR pages 8 and 10, R10: 250 stored shots and recall target | All relevant records included in statistics; 25-row display pagination; 250-record domain and browser checks. The ≤3 s end-to-end recall target is not claimed as certified. |
| MSDR page 19: latest shot and fast history recall | Latest saved shot screen and direct detail selection. Cloud changes update via an owner-scoped Firestore subscription. No impact-to-phone latency claim is made. |
| MSDR page 20: profiles, comparisons, progression | Per-club means/sample SD/metric counts, modeled carry gaps, like-for-like session comparison and modeled carry history chart. Statistics run in the app, not a cloud analytics service. |
| MSDR pages 5–6 and 11: proposed sound trigger/pairing | Keep current camera-trigger information. Sound detector is temporarily unavailable; Bluetooth, calibration controls and hardware health are not fabricated or activated. |

## Implemented

- Preserved email/password sign-up/sign-in, Google popup sign-in, password reset and real Firestore golfer-profile management. These are in Settings for an authenticated cloud account.
- Explicit synthetic demo entry, 24 local synthetic records across two synthetic sessions, editable demo profiles, an empty-profile example and manual playback. No fixture writes to Firebase.
- Practice cards for ball/club speed, smash, measured VLA/HLA and modeled carry. Missing values stay unavailable and zero angles remain zero. Flight view renders only trajectory points supplied by a Pi record; CSV metrics never become invented trajectories or measured dispersion.
- Sessions filtered by golfer, club, session and UTC/source date, with provenance, quality flags, revisions and CSV export retaining stable IDs/source labels. Export is app history format, not a substitute for an original Pi import CSV.
- My Bag statistics use final eligible records, per-metric sample counts and sample SD. Sample SD is unavailable for n<2. Synthetic/unknown/processing attempts are excluded from real statistics. Synthetic inclusion is explicit in demo.
- CSV preview validates the whole original file using the unchanged supplied normalizer. Device/profile/timezone attribution is required; real-shot confirmation is explicit. All normalized timestamps remain null for legacy data. Preview records are held in memory, and JSON download is available. The upload button remains disabled because there is no authenticated ingestion server yet.
- Complete owner-scoped Firestore shot subscription for the expected small capstone dataset. New backend-authored canonical records automatically appear. Dataset validation fails visibly for incompatible cloud documents; authentication/read failures never fall back to demo. No statistic is limited to the displayed page.
- Units preference persists independently; private records are not persisted. Listener cleanup and keyed remounts discard private UI state on account change/sign-out.
- Home-screen manifest with correctly sized 192/512 icons. There is no service worker or offline cold-start guarantee. A loaded tab can browse its in-memory demo/preview; Firestore networking and Pi-local access remain separate concerns.

## Verification

- TypeScript and production build passed.
- 29 domain/view-model tests passed, including the 22 original starter tests and seven new tests for whole-filter 250-record statistics/lookup, filters/ownership, units, sample counts/SD, revisions, malformed cloud records and provenance-preserving export.
- Ten Auth/Firestore emulator tests passed on isolated ports 8087/9097 after an initial emulator startup failure. Tests cover signed-out/cross-account denial, own profiles/timestamp immutability, denied direct shot/device writes, credential denial, email/password account switching and synthetic Google credentials. No real users or shots were created in Firebase during testing.
- Browser checks: explicit demo entry; populated/empty golfer selection; My Bag metric-specific counts and two-session comparison; club filtering; shot details; units switching; 12-record preview; 250-record local preview showing all 250 records and 25-row pagination with zero statistics-eligible unconfirmed records.
- Browser layout inspected at desktop, phone-sized viewport and an 800×480 viewport; the document does not horizontally overflow. Wide tables intentionally scroll within their containers. A compact landscape layout keeps shot metrics prominent.
- Google popup sign-in on real iPhone Safari, hardware shot accuracy, actual Pi/network sync, offline cold start and the PDR/MSDR latency targets remain unverified.

Commands:

```powershell
npm ci
npm test
npm run build
$env:JAVA_HOME = (Get-ChildItem '.tools/java21' -Directory | Select-Object -First 1).FullName
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
npx -y firebase-tools@latest emulators:exec --config firebase.emulator-test.json --only auth,firestore --project demo-modus-golf 'node --test tests/auth.test.mjs tests/firestore.test.mjs'
```

The portable Java runtime is intentionally excluded from the source ZIP; use an installed Java 21+ runtime when reproducing emulator tests elsewhere. The production build still reports a large JavaScript bundle warning; code splitting is a future performance improvement.

## Future Pi integration contract

The future authenticated backend must resolve UID server-side and write canonical shot documents under `users/{uid}/shots/{shot_id}`. Use the existing shot.schema.json/normalizer contract: immutable shot/session/device/profile identity, monotonic per-shot revision, processing state, explicit nulls, quality flags and source.kind `pi_live` for live records. Firestore profile IDs come from the authenticated owner's profile collection. Client history filters never change capture assignment.

The browser subscribes to these documents now. Device pairing, credential verification, stable durable capture records and a retrying uploader still need implementation in the separate Pi/backend workstream. Do not put Admin SDK keys on the Pi. Do not weaken browser rules to allow shot ingestion. No hardware, network, firmware, camera, GPIO, startup or GitHub changes were made for this release. Publishing authorizes frontend Hosting only; no billing upgrade or backend service was provisioned.

## Changed source files

`src/main.tsx`, `src/auth-ui.tsx`, `src/workspace.tsx`, `src/components.tsx`, `src/import-preview.tsx`, `src/bag.tsx`, `src/domain.ts`, `src/demo.ts`, `src/repository.ts`, `src/style.css`, `tsconfig.json`, `index.html`, `package.json`, `package-lock.json`, `public/manifest.webmanifest`, `public/icons/*`, `scripts/make-icons.py`, `tests/view-model.test.mjs`, `tests/fixtures/session_20261022_192000.csv`, `firebase.emulator-test.json`, and release/setup documentation.

The original framework-independent normalizer, original fixtures, Firestore rules and inspected Pi sources remain unchanged. The added 250-row CSV is a synthetic local test fixture, not recorded hardware evidence. Source archives exclude the reference PDFs, extracted reviews, debug logs, node_modules, build outputs, CLI credentials and local runtime tools.
