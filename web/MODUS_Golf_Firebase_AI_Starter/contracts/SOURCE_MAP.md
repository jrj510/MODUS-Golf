# Current source to proposed app model

This contract is proposed for the app and ingestion service. The current Pi does not serve it. Reference fields are from the actual October 22 uploaded source.

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
| CSV `launch_dir_deg` | `horizontal_launch_angle_deg` | Separate reported radar HLA. The existing flight does not use this direction. |
| CSV `spin_rpm_used` | `model_inputs.spin_rpm` | Club-default model input, never measured spin. |
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
- row hash: `row_` + hex SHA256 of JSON `["row", ...all14ColumnValuesInOrder]`.

A backend must use the identical encoding, prohibit duplicate row numbers and conflicting repeated imports, and bind the source session to its first owner/profile. A source hash identifies a changed row; it does not authorize overwriting it or changing its owner. Firebase UID is not part of the shot hash and must be independently authenticated.

The core requires Web Crypto, available in secure browser contexts or Node 20+. It does not make an HTTP Pi page a secure PWA or implement cloud ingestion. A later local exporter can implement the same hashing on the Pi.
