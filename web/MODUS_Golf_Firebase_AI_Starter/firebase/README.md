# Firebase integration boundary

This folder is a reviewed starting design, not an initialized Firebase project. It contains no project ID, credential, deployment target, or enabled service. The rules have not been deployed or emulator-tested here.

The rules allow authenticated owners to read their records and create/rename a small validated golfer profile. They deny direct browser writes to shot, session, import, summary, and device data. Profile deletion is also denied until server-side reference handling exists. This intentionally prevents the AI builder from creating a publicly writable database or silently bypassing the future ingestion boundary.

Use server timestamps for profile `created_at` and `updated_at`. Account UID comes from Firebase Authentication, not a client-supplied body. Documents in `users/{uid}/shots` use the canonical shot fields plus backend-owned ingestion metadata; their IDs equal `shot_id`. The user's namespace does not authorize a device to upload on their behalf: backend device ownership must still be verified.

Required future API behavior:

- Human CSV import: verify Firebase ID token, resolve UID, validate whole file and explicit golfer/device/timezone attribution, fix first-import ownership, then idempotently store canonical records. Reject modifications that conflict with already imported immutable rows. A preview-only frontend does not need this endpoint.
- Pi ingestion: verify a scoped revocable device credential against registered ownership, resolve account server-side, validate profile/session binding and shot revision, return exact acknowledgment. Never trust an arbitrary `owner_uid` from the Pi.
- Analytics: compute only from allowed real/final records with metric-specific sample counts, preserve model labels, and version/recompute materialized summaries after revisions. Do not add demo fixtures to actual user collections.

Before production, implement emulator tests for signed-out denial, own/other owner isolation, field validation, immutable creation timestamps, denied direct shot writes, denied credential access, and device-read policy. Separately test backend authorization because Admin SDK writes bypass rules. Add query-specific indexes only after the actual frontend queries are known.
