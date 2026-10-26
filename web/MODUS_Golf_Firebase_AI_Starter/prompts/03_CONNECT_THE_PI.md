# Later prompt for real Pi-to-cloud integration

Implement this only after the app, authenticated backend, schema, and ownership tests work. First inspect the actual current source; this package describes the October 22 export, not every future version.

Preserve the existing camera-trigger path, outside/inside presets, recording-off settings, radar GPIO and UART wiring, Pi calculations, and local touchscreen. No firmware, hardware, power-mode, network, or geometry changes belong in this task.

Build a separate optional process with read-only access to finalized local shot records. The original kiosk has no durable globally unique shot IDs, golfer ownership, or revision log. Establish those explicitly; do not fabricate identity from `/state.rev` or treat `/history` as a permanent source. Legacy CSV contains final records but lacks some real-time fields and exact impact timing. Document what can and cannot be synchronized until a narrowly reviewed exporter exists.

Use a local durable SQLite outbox. Persist a normalized processed shot before attempting network upload. Use a stable device UUID provisioned separately from Firebase UID, a stable session ID, shot ID, and revision. Bind account/profile/session before capture and freeze ownership at trigger time. Browsing a golfer on the phone must not change that binding.

The server authenticates an individually revocable device credential, resolves its registered owner, verifies profile/session ownership, validates an allowlisted schema and size limits, and commits idempotently. Store only a credential hash/verification material server-side. Use HTTPS. Never install an Admin SDK service-account key on the Pi. Return an acknowledgment with the exact shot ID and revision; remove only that queued revision. Back off on outages and preserve queued data across restart. Exclude test and unconfirmed legacy records by default.

Cloud upload failure never blocks local capture or display. Raw camera/radar files remain local. With current recording-off presets, do not imply raw artifacts or replay clips exist. Reconnect must catch up without duplicates and must not start a new physical session.

The Pi's existing hotspot serves the local app. It needs an independently tested upstream route for cloud sync. Do not assume the phone shares cellular back to it. Do not change Wi-Fi mode while a shot is being captured. Start with after-session sync over a known network, then consider field connectivity only if required by tests.

Do not expose the unauthenticated kiosk to the public internet. Do not add a cloud service that proxies requests to arbitrary private IPs. A hosted HTTPS PWA's access to local HTTP requires a separately designed, authenticated browser-compatible transport; relaxing CORS alone is insufficient.

Deliver a local review ZIP/patch and tests before installation. Verify queue persistence, duplicate retries, revision ordering, ownership denial, exact acknowledgments, network loss, and shutdown/restart using recorded or synthetic artifacts. Report real-Pi tests as pending until actually run. Never flash firmware or restart production capture automatically.
