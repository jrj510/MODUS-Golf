# Current source to proposed app model

This normalized shot contract is for the app and ingestion service; the Pi exports CSV rather than this JSON shape. The adapter supports the original 14-column CSV and the current 34-column export, verified on November 19 against `jrj510/MODUS-Golf` commit `8846a3958b22e8be898e2930b691f96ba7dd697c`. The exact current header and producer blob SHA are recorded in `pi-csv-34.json`.

Headers are matched by unique column names against either complete known format, so ordering can change without shifting values. Missing, duplicate, unknown or truncated columns are rejected. The original 14 fields keep their meanings below; the extra 20 fields are preserved under `source.csv_extra` with `source.csv_format = 'modus_csv_34'`. They are bounded raw strings, not new validated measurements. For example, `club_speed_hidden_mph`/`club_speed_check_mph` do not replace an unavailable accepted club speed, `cam_launch_deg` does not override the selected launch result, and `spin_model_rpm` does not become measured spin. New modeled total/roll and diagnostic fields remain available for a later explicitly typed UI mapping.

| Existing source field | Canonical destination | Interpretation |
|---|---|---|
| CSV `shot` | `sequence_number` | Per-run counter; not a global ID. |
| Original filename plus explicit device ID and shot number | `shot_id`, `session_id` | Deterministic hash IDs; freeze profile ownership separately. |
| Explicit import profile | `profile_id` | A golfer label identity, separate from Firebase account UID. |
| CSV `time` | `source.local_log_time` | Log time, not impact time. |
| Confirmed Pi timezone | `source.timezone` | Preserve; do not guess. Converter does not assign UTC. |
| CSV `ball_speed_mph` | `ball_speed_mph` | Reported speed; can include correction/fallback, not guaranteed raw OPS. |
| CSV `ball_speed_raw_mph` | `source.ball_speed_raw_mph` | Raw radar value when supplied. |
| CSV `club_speed_mph`, `smash` | `club_speed_mph`, `smash_factor` | Null when missing; validation is still required against real shots. |
| CSV `launch_deg`, measured=yes | `vertical_launch_angle_deg` | Reported measured VLA; does not prove accuracy. |
| CSV `launch_deg`, measured=no | measured VLA null; `model_inputs.vertical_launch_angle_deg` | Assumed input. |
| CSV `launch_dir_deg` | `horizontal_launch_angle_deg` | Selected reported HLA (radar, or camera in the newer producer). The reviewed flight call does not use this direction. |
| CSV `spin_rpm_used` | `model_inputs.spin_rpm` | Estimated/model input, never measured spin. The older exporter used club defaults; the newer exporter includes its own estimate/check diagnostics. |
| CSV `carry_yd`, `apex_yd` | `carry_yards`, `source.apex_yards` | Modeled distance and height. |
| CSV `ti_radar` | `source.ti_radar` | Preserve quality/error text, not a fabricated numeric confidence. |
| Current `_publish()` flight direction | `model_inputs.horizontal_launch_angle_deg = 0` | Current flight call omits direction; this is an assumed zero, separate from reported HLA. |
| `/history` flight `path` | optional `trajectory` | Pi-computed [forward, height, right] in yards. CSV has no path. |
| `/history` `assumed`, `test` | quality flags and `record_kind` | Preserve source semantics; do not turn test flights into real records. |
| `/state.rev` | none as a durable revision | UI counter only. Future exporter must supply durable per-shot revisions. |
| Missing raw capture file | no link | Recording-off presets intentionally do not create replay clips. |

## Stable ID algorithm

The supplied core uses UTF-8 JSON arrays and SHA-256:

- session: `session_` + hex SHA256 of JSON `["session", deviceId, originalFilename]`.
- shot: `shot_` + hex SHA256 of JSON `["shot", deviceId, originalFilename, shotNumberAsString]`.
- legacy row hash: `row_` + hex SHA256 of JSON `["row", ...all14ColumnValuesInCanonicalOrder]`.
- current row hash: `row_` + hex SHA256 of JSON `["row", ...all34ColumnValuesInCanonicalOrder]`.

Reordering a header does not change its row hash. Diagnostic-only changes in a 34-column row do change its hash, so local revision merging retains the enrichment. Session/shot IDs do not depend on the format or mutable diagnostics. Moving from a 14-field to a 34-field record keeps those IDs and legitimately changes the row content hash. Existing legacy normalized records and fixture hashes are unchanged.

A backend must use the identical encoding, prohibit duplicate row numbers and conflicting repeated imports, and bind the source session to its first owner/profile. A source hash identifies a changed row; it does not authorize overwriting it or changing its owner. Firebase UID is not part of the shot hash and must be independently authenticated.

The core uses Web Crypto by default and accepts the existing portable hash callback for the installed phone app. It does not make an HTTP Pi page a secure PWA or implement cloud ingestion. A later local exporter can implement the same hashing on the Pi.
