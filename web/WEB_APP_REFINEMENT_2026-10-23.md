# MODUS Golf web refinement release

Published site: https://modus-golf-ea469.web.app

This release applies selected ideas from the optional UI brief and the new onboard screenshots. The Pi ZIP and physical monitor were inspected as references; neither GitHub nor the Pi was modified. Setup instructions and credentials in the kiosk PDF were not executed or published.

## Website changes

- Dark kiosk-inspired design with green accents, system fonts, and matching Home Screen icons.
- Carry-first Practice feedback, secondary ball speed and measured launch, expandable additional metrics with model/experimental provenance.
- Recent-shot selection updates cards and supplied flight together. Stable IDs retain selection across new arrivals and revision updates; Follow latest resumes automatic selection.
- Quiet range/side views using supplied paths, no browser flight solver. Explicit distance-only overhead when direction was assumed; no inferred draw/fade or measured dispersion.
- Phone Range/Side switch, touch controls, 16px inputs/selects to avoid Safari focus zoom, viewport safe areas and bottom navigation clearance. No page horizontal overflow observed at 320, 360, 390, 430, 768, 1024 and 1280 viewport widths.
- Sign-in loads separately from the workspace/Firestore SDK. Initial JavaScript falls from about 880 KB to about 334 KB uncompressed (about 62% less); workspace loads on demand with loading/error states. Final output: entry 333.85 KB (103.07 KB gzip), workspace 548.22 KB (164.63 KB gzip), CSS 30.95 KB (6.88 KB gzip). The workspace chunk still exceeds Vite's 500 KB warning threshold. This is not a physical-device performance benchmark.
- Firestore trajectory point-map adapter fixes a storage compatibility issue: Firestore Standard cannot persist arrays directly inside arrays. Canonical API/local paths stay tuples; stored paths use `{forward_yards,height_yards,right_yards}` maps. No Firestore rules change was needed.
- Hosting HTML/default routes now revalidate on use; fingerprinted assets retain immutable caching. Existing open tabs may need one refresh to leave the previous cached release.
- Documented local Pi range link in Settings. Cloud history, capture status, pending uploads, and sensor health are kept distinct.

## Validation

- `npm test`: **33 passed** (22 original domain tests, 11 view-model tests).
- Auth/Firestore emulator checks: **11 passed**, including owner isolation, direct browser write denial, profile validation, auth account changes, and real Firestore persistence/decoding of point maps.
- `npm run build`: TypeScript and production Vite build passed.
- Browser checks: sign-in/demo transition after lazy loading; selected metric/flight carry agreement; phone Range/Side toggle; responsive widths and 16px form controls; Sessions, My Bag and Settings checked before publication.
- Emulator Google credential testing does not certify a real Google OAuth popup on an iPhone. Physical Safari/Home Screen login, keyboard behavior, Pi network connectivity, capture accuracy and impact-to-phone latency still require field verification.

## Handoff and remaining integration

Send `MODUS_Golf_GitHub_Integration_Handoff.md` plus `MODUS_Golf_Web_App_Refined_2026-10-23.zip` to the AI with GitHub access. See `handoff/README.md` for a suggested prompt and canonical/storage examples. The full Markdown includes the latest Pi snapshot SHA-256, active code paths, full canonical schema, Firestore encoding, secure pairing/ownership protocol, durable upload design, tests, deployment boundaries, and optional fixes.

Automatic physical-shot uploads remain dependent on the required Pi/backend work. No ingest endpoint, pairing service, telemetry service or hosted replay has been provisioned. No service-account key or reference-document credentials are included in the source package or public Hosting files.

The earlier `WEB_APP_RELEASE_2026-10-23.md` records the preceding build. This document and the new handoff supersede its UI, test-count, and Firestore trajectory-storage details.
