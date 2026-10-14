#!/bin/bash
# Starts MODUS-Golf: the start menu on the screen, then the kiosk with the
# options picked there. The kiosk's Menu button comes back to the menu.
# Run by the desktop at login (see modus-kiosk.desktop), or by hand:
#     ~/MODUS-Golf/start_kiosk.sh
#
# Change the settings below if the setup changes.
# Logs go to ~/MODUS-Golf/logs/, shot logs to ~/MODUS-Golf/logs/sessions/

# TI radar geometry. Measure these on site; a wrong value shifts every launch
# angle without any error message. "Antenna centre" = the point halfway
# between the middle of the TX patches (top group) and the middle of the RX
# patches (bottom group). Heights are from the ground the ball sits on.
TEE_M=1.575        # antenna centre to ball centre, slant, metres (5 ft 2 in)
NET_M=4.6          # antenna centre to the net / box, metres
TILT_DEG=10        # antenna face leans back this far from vertical (points up), degrees
RADAR_H=0.076      # antenna centre above the ground, metres (3 in, measured with the box tipped back 10 deg)
BALL_H=0.021       # ball centre above the ground, metres (0.021 = ball on the ground; on a mat add its thickness)
AZIMUTH_DEG=0      # radars point this far right of the target line (left = negative), degrees
GATE_GPIO=17       # GPIO the sound sensor GATE is wired to (17 = pin 11, 26 = pin 37)

# Power. The moment after a shot is the heaviest load (the TI radar's
# processing, plus whatever the camera saves); on a battery pack that spike
# can shut the Pi off. These keep it down:
# The start menu's mode picks the recording:
#   Power saver -> flight: only the ball leaving, no preview video (least power)
#   Wall power  -> full:   slow-motion Shot Preview with Save/Delete
#   Sound only  -> flight
SENSOR=full       # full = read all 1280x800 pixels and zoom 2x on the hitting zone
                  # (ball twice as wide, up to 144 fps); binned = old 640x400 mode, 200 fps
MODEL=             # ball model; empty = OpenFlight's. After retraining (camera/train_ball_model.py):
                   # MODEL=~/openflight/models/modus_ball_256.onnx
TI_DUMPS=0         # 1 = also save the TI radar's raw captures (for debugging angles only)
export OPENBLAS_NUM_THREADS=1   # math on one core at a time instead of all four at once
export PYTHONUNBUFFERED=1       # the kiosk's messages reach its log straight away

cd ~/MODUS-Golf || exit 1
mkdir -p logs

# Only one copy at a time.
exec 9>/tmp/modus-kiosk.lock
if ! flock -n 9; then
    echo "MODUS-Golf is already running."
    exit 0
fi

# Give the radars' USB connections a moment to appear after boot.
for i in $(seq 1 20); do
    [ -e /dev/ttyACM0 ] && [ -e /dev/ttyUSB0 ] && break
    sleep 1
done

source ~/vision-env/bin/activate

OPEN="--open-browser"   # open the full-screen browser the first time only
NOTE=""
while true; do
    CHOICE=$(python3 camera/launcher.py $OPEN --note "$NOTE" 2>>logs/launcher.log)
    if [ -z "$CHOICE" ]; then
        sleep 2
        continue
    fi
    OPEN=""
    NOTE=""
    MODE=${CHOICE%%,*}
    CLUB=${CHOICE##*,}
    case "$MODE" in
        sound) DETECT="'--trigger','sound','--no-ball'";       RECORDING=flight ;;
        wall)  DETECT="'--trigger','motion,sound','--blob'";   RECORDING=full ;;
        *)     MODE=saver
               DETECT="'--trigger','motion,sound','--blob'";   RECORDING=flight ;;
    esac
    MODELARG=""
    if [ -n "$MODEL" ]; then
        MODELARG="'--model','$MODEL',"
    fi
    DUMPS=""
    if [ "$TI_DUMPS" = "1" ]; then
        DUMPS="'--iwr-save-dumps',"
    fi
    LOG="logs/kiosk_$(date +%Y%m%d_%H%M%S)_${MODE}.log"
    echo "Starting kiosk: $MODE mode, club $CLUB, recording $RECORDING (log: $LOG)"
    python3 -c "import logging,runpy,sys; logging.basicConfig(level=logging.INFO); sys.path.insert(0,'camera'); sys.argv=['kiosk.py','--iwr','--ops',$DETECT,'--no-browser','--iwr-tee-m','$TEE_M','--iwr-net-m','$NET_M','--iwr-tilt-deg','$TILT_DEG','--iwr-radar-height-m','$RADAR_H','--iwr-ball-height-m','$BALL_H','--iwr-azimuth-offset-deg','$AZIMUTH_DEG',$DUMPS$MODELARG'--recording','$RECORDING','--sensor','$SENSOR','--gate-gpio','$GATE_GPIO','--club','$CLUB']; runpy.run_path('camera/kiosk.py', run_name='__main__')" >> "$LOG" 2>&1
    code=$?
    if [ $code -ne 0 ]; then
        echo "Kiosk stopped unexpectedly (code $code)" >> "$LOG"
        NOTE="The last run stopped unexpectedly. Check the log, or press Start to try again."
        sleep 2
    fi
    # Back to the menu.
done
