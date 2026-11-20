# Existing Pi interface: read-only integration reference

November 19 compatibility update: the current GitHub producer exports **34 columns**, while older supplied ZIPs exported 14. The shared app parser now supports both complete known headers by name; the exact new header is pinned in `pi-csv-34.json`. The installed phone reader still uses this shared normalizer for `/session.csv`. Extra diagnostic fields are retained, not discarded. This source update is not a physical-device or cloud-upload test. Historical October interface notes follow.

Verified against the supplied October 22 source, not against a running Pi. Default bind is `0.0.0.0:8000`; determine the actual device address and startup port. Authentication, cloud ingestion, stable cloud identities, and remote profile controls are absent from this API.

| Method and path | Existing behavior | App use |
|---|---|---|
| `GET /` | Embedded current kiosk page | Existing local display, unchanged. |
| `GET /range` | Current responsive range page | Open directly in Safari while joined to the Pi hotspot. |
| `GET /ping` | Local availability route | Later local adapter only; response does not establish sensor health. |
| `GET /state` | Mutable latest shot and UI state | Use `pi_state.json` as a synthetic shape example. |
| `GET /history` | Up to 30 in-memory flights | Use `pi_history.json` as a synthetic shape example; not a permanent archive. |
| `GET /session.csv` | Current run's session CSV download | Explicit local export, then app preview/import when internet is available. |

`shot` and `rev` are counters from this process, not global shot identities or durable per-shot revisions. Neither endpoint proves camera cadence, sensor health, battery level, or successful cloud upload.

The app must not call kiosk routes that mutate camera, calibration, zone, test shots, save/delete files, or quit the process. This reference intentionally does not offer those controls. Keep the existing unauthenticated server local.

`known_hardware.json` is a demo context fixture, not an endpoint the Pi currently serves. It records the team-confirmed removal of the broken sound sensor and the camera-trigger configuration. Show that as configured hardware context, separately from live telemetry.

A hosted HTTPS app and an HTTP page on the Pi are separate origins and transports. The installed mobile source uses native local transport, while the hosted browser's transport limitations remain separate. CORS configuration alone does not establish a supported, authenticated browser connection.
