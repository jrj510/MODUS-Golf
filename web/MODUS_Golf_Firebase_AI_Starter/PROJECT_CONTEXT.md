# Current MODUS Golf source context

Authoritative supplied artifact: `MODUS-Golf-main (1).zip`, received October 22, 2026.

- SHA256: `d5f72b90f815f48ca962459a264ce80b8a1274e0abd1ada74f74f172e66c430e`
- ZIP comment: `d9aeafe49d657ffaf403b238ef239f69adc49564` (export metadata, not independently verified remote HEAD).
- 42 files. Compared with the earlier supplied ZIP, 37 files are byte-identical. Five changed: `camera/iwr_bridge.py`, `camera/kiosk.py`, `camera/launcher.py`, `camera/shot_capture.py`, and `start_kiosk.sh`.
- The files under `cloud/` in this export are empty placeholders. There is no implemented cloud service in this source snapshot.

## Installed prototype and software configuration

Raspberry Pi 5, 8 GB; OPS243-A-CW-RP; IWR6843LEVM; OV9281; 800 by 480 DSI touchscreen; TalentCell portable power. The user confirms that the SparkFun sound detector broke and has been temporarily removed; it will be restored after replacement. The camera-generated trigger is the current path. The user reports that the current outside setup works on the battery and the Pi already hosts joinable Wi-Fi. No live Pi measurements or network configuration were supplied with the ZIP.

Current `start_kiosk.sh` configures OPS on `/dev/ttyAMA0`, TI on the default USB path, trigger input GPIO20, camera-generated trigger output GPIO21, and OPS reset GPIO23. The trigger label `sound` is also used for the hardware pulse path, although no sound detector is currently installed. Display `Trigger: Camera` and `Sound sensor: Temporarily removed; replacement planned` when describing this known configuration. Do not report the sound detector as healthy or treat its planned absence as a failed system. Its later return requires verified wiring/configuration and must not happen automatically from the app.

Outside Golf: full sensor, requested 60 FPS, recording off. Inside Golf: binned sensor, requested 300 FPS, recording off. The file comments describe battery trouble at 144 FPS and approximately 250 FPS delivered in the inside configuration; those comments are not independent measurements from this review. Both presets intentionally disable saved replay. Do not promise camera replay in those modes.

Earlier advice about `/dev/ttyACM0`, GPIO17, or default saved flight clips does not describe the new startup configuration. GPIO17 remains in some help/comments; runtime arguments from the startup script take precedence. IWR geometry numbers in the script are configured values, not measurements verified here.

The Pi imports radar processing from an external OpenFlight checkout. The uploaded ZIP does not identify the installed OpenFlight commit. Current upstream code cannot be assumed to be identical to that installed dependency.

## Current local UI and contract

`camera/kiosk.py` embeds the touchscreen HTML and serves it with Python's ThreadingHTTPServer, bound to `0.0.0.0`, default port 8000. `camera/launcher.py` serves the start menu before capture begins. The existing kiosk has eight tiles, status, a camera/alignment view, an optional preview, and Range navigation. It polls `/state` every 250 ms. The existing range page in `camera/range_page.py` polls every 600 ms, renders Pi-provided paths on canvases, and links to CSV export.

`GET /state` is a mutable latest-state snapshot. `rev` is a UI update counter, not a durable per-shot revision. `shot` restarts per process. Neither is a global database identity.

`GET /history` contains up to 30 flight objects in RAM. `/session.csv` exports the per-run CSV in `logs/sessions/session_YYYYMMDD_HHMMSS.csv`. Do not use the 30-shot live buffer as the permanent golfer archive.

Read-only routes useful to a later local adapter: `/ping`, `/state`, `/history`, `/session.csv`, `/range`. The source also has camera, test, alignment, quit, save, and delete controls. The Firebase app must not call those controls. The API is shared-local access, not an authenticated public API.

## Provenance and modeling

`_publish()` first shows OPS results and may later enrich them with TI angles. Current `_publish()` calls `shot_flight(ball_speed, club, launch_angle=...)` without a measured spin or horizontal direction. The rendered flight therefore uses club-default spin and assumed direction, even if separate radar HLA or an experimental spin number exists in the metrics dictionary. Carry is modeled in all cases; `carry_estimated` only identifies one missing-launch case and must not be used as a universal measured-distance indicator.

CSV `spin_rpm_used` always comes from this model result. It must map to a model-input field, never to measured spin. CSV `launch_deg` can be an assumed club default; `launch_measured` distinguishes it. CSV `launch_dir_deg` is separate radar output and did not drive the historical modeled trajectory.

CSV lacks a precise impact timestamp, stable hardware ID, cloud account, golfer identity, raw capture paths, and an explicit real/test classification. Preserve those limitations. Record an explicit human import confirmation rather than silently classifying old rows as real. The original `test_shot()` marks in-memory flights as synthetic but does not itself call the CSV logger.

## App and cloud decisions

The user wants a Windows-developed iPhone web app. Native installation and App Store publishing are unnecessary. Primary calculations remain onboard in the final product. Firebase is the intended initial backend for accounts, profiles, history, and additional analytics; nothing has been provisioned in this session.

Keep the working local Pi pages available through its current hotspot. A hosted cloud app uses internet. Do not assume the iPhone automatically bridges cellular internet to the Pi, or that one Pi radio can reliably host the AP and join another network simultaneously. An initial upload can happen after practice when the Pi has internet, or through a deliberately implemented manual import backend.

## Ownership and reuse

The team repository is read-only unless the user explicitly authorizes remote writes. Source changes are local/downloadable only. The reference files are unmodified team source and may contain upstream-derived code. Preserve attribution and verify the applicable project/file license before redistributing derived implementation; do not relicense the reference folder as MIT. No external app source was newly copied into the starter core.
