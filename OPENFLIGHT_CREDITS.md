# OpenFlight credit

MODUS-Golf learned to read its radars from [OpenFlight](https://github.com/open-flight/openflight), an open-source DIY golf launch monitor licensed under the GNU AGPL-3.0. Turning one golf swing into a ball speed and a club speed with an OmniPreSense OPS243-A, inside a radar recording of only 136 ms, was the steepest part of our learning curve, and OpenFlight's code is how we learned it. After that we built the rest of MODUS our own way. This file lists what still comes from OpenFlight, what we learned from it, and what is ours.

OpenFlight is installed on the Pi as its own checkout (default `~/openflight`, set with `--openflight` in `camera/kiosk.py`). No OpenFlight source files are copied into this repository; our code imports them from that checkout.

## Radar: still OpenFlight's code

| What | OpenFlight module | Where MODUS uses it |
|---|---|---|
| OPS243-A speed radar driver and rolling-buffer signal processing: raw I/Q recording, FFT readings, then ball speed | `openflight.rolling_buffer` | `camera/iwr_bridge.py` (`OPSBridge`) |
| Its club speed, kept only as a logged backup check (`club_speed_check_mph` in the session CSV) | `openflight.rolling_buffer` | `camera/iwr_bridge.py` |
| Ball-speed correction, run beside ours on every shot as a logged backup check only (`ball_speed_check_mph` in the session CSV) | `openflight.speed_correction` | `camera/iwr_bridge.py` |

## What we developed after learning OpenFlight's speed-radar processing:

- Trigger: our camera, not OpenFlight's sound sensor, pulses the OPS243's trigger pin when it sees the ball leave. MODUS has no microphone.
- Recording window: the camera triggers 40-90 ms after impact, so we keep 20-30 of the radar's 32 blocks from before the trigger (OpenFlight's sound trigger keeps 12), or the club is gone from the recording (`OUTSIDE_OPS_PRE_TRIGGER` / `INSIDE_OPS_PRE_TRIGGER` in `start_kiosk.sh`).
- Club speed: ours. We developed it from OpenFlight's FFT readings with our own method (`club_speed_from_readings` in `camera/radar_calibration.py`): the peak of the club head's climb just before the ball's jump, or where the climb levels off when club and ball merge. It doesn't need OpenFlight's club types, so the speed radar is no longer told the club. 
- Ball speed: its reading goes through our own line-of-sight model and per-unit trim (`camera/radar_calibration.py`).
- Readiness: its "nothing flew away" answer is our radar check.
- Speed-radar calibration (`camera/radar_calibration.py`): OpenFlight's line-of-sight idea, rebuilt on our own flight model (drag by speed and spin, gravity and lift, 3-D aim), our camera-triggered window, the indoor net and the radar's beam, plus a per-unit trim fitted against a reference launch monitor. 
- TI calibration (`camera/radar_calibration.py`, `camera/calibrate_radars.py`): our angle trim against the camera and our own array solver with a floor-echo model (** still a work in process since we can no longer run tests with the sensor being broken)
- Ball model: version 1 (`modus_ball_256.onnx`) was originally fine-tuned from OpenFlight's ball model however it gave us numerous issue in the early stages. Therefore we took on 250 pictures from our own camera and created and now use version 2. Version 2 trains from Ultralytics' generic YOLO11n (`camera/train_ball_model.py --base yolo11n.pt`)
- Camera exposure: the shutter/gain steps started from OpenFlight's, however it was unrevised and had issues when introduced to environmental variables; therefore we added and developed The metering area, the extra sun and dark-room steps and Low light mode.

No OpenFlight code: club speed, the camera trigger and readiness (Ready, shadow guard, cover guard, radar check), ball detection on the device (our model only), camera launch angle and direction (`camera/launch_camera.py`), spin, carry, roll/total and smash (`camera/ballflight.py`), the kiosk screens and start menu (`camera/kiosk.py`, `camera/launcher.py`), and the enclosure designs.

## License

OpenFlight is the work of its authors and is licensed under the GNU Affero General Public License v3.0; its code stays under that license. Source and full license text: https://github.com/open-flight/openflight
