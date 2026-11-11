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
GATE_GPIO=20       # trigger input the TI radar listens on: GPIO20 = pin 38 (was 17 = pin 11)
OPS_PORT=/dev/ttyAMA0   # speed radar on the Pi's UART (J3 pins 6/7 to Pi pins 8/10); USB would be /dev/ttyACM0
HOLD_SECONDS=5      # ball covered (hand, club, foot) this long -> back to Looking for Ball
MOTION_THRESHOLD=12 # camera trigger: how much the ball's spot must change (0-255) when the ball leaves.
                   # Was 25; lab shots only changed it by 13-16, so half were missed
OPS_TRIGGER=sound  # sound = the OPS waits for a pulse on J3-3 (from the camera or the sound detector);
                   # speed = the OPS triggers itself (picked up noise here, so not used)
TRIGGER_OUT_GPIO=21 # camera trigger: GPIO21 (pin 40) pulses OPS J3-3 and GPIO20 (pin 38) when the
                   # camera sees the ball leave. 0 = off (only if the sound detector is wired again)
OPS_TRIGGER_MPH=60 # speed trigger only fires at this outbound speed or faster (OpenFlight default 20 mph);
                   # lower it for chips, raise it if things that aren't shots still start a measurement
OPS_RESET_GPIO=23  # wired to OPS J3 pin 4 (/Reset); the OPS is reset each time the kiosk starts. Empty = off

# Power. The moment after a shot is the heaviest load (the TI radar's
# processing, plus whatever the camera saves); on a battery pack that spike
# can shut the Pi off. These keep it down:
# The start menu's two modes. Both use the camera + the shot trigger (OPS_TRIGGER).
# Sensor: full = read all 1280x800 pixels and zoom 2x on the hitting zone
# (ball twice as wide, up to 144 fps); binned = 640x400, faster, no zoom.
# Recording: full = slow-motion Shot Preview with Save/Delete;
# flight = only the ball leaving, no preview (least power); off = save nothing.
#   Outside Golf: the settings that ran on the battery pack without cutting out.
OUTSIDE_SENSOR=full
OUTSIDE_FPS=60       # 144 cut out the battery pack; 60 keeps the load down
OUTSIDE_RECORDING=off   # no shot replay or saved frames: lightest load for the battery
#   Inside Golf: wall outlet only. Full sensor so it can zoom 2x on the hitting
#   zone like Outside Golf (the ball is twice as wide, much easier to find), at
#   the full sensor's top speed, 144 fps. INSIDE_SENSOR=binned + INSIDE_FPS=300
#   gives about 250 fps instead, but no zoom.
INSIDE_SENSOR=full
INSIDE_FPS=144
INSIDE_RECORDING=off    # no shot replay (full = slow-motion Shot Preview with Save/Delete)
# Sleep. The moon button (top right) puts the box to sleep: camera and TI
# radar off, screen dark; tap the screen to wake (about 3-5 s, the TI radar is
# set up again). It also sleeps by itself after this many minutes of Looking
# for Ball with no ball, no shot and no taps on the screen; 0 = button only.
# Never in the middle of a shot. The speed radar stays on (its mode can't be
# switched safely at runtime).
OUTSIDE_SLEEP_MINUTES=3   # on the course: sleeps on the walk to the ball
INSIDE_SLEEP_MINUTES=10
SLEEP_SCREEN=off   # off = backlight off while asleep (saves the most);
                   # black = backlight on, screen black (only if a tap doesn't wake it with the backlight off)
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

# Give the TI radar's USB connection (and the OPS port) a moment to appear after boot.
for i in $(seq 1 20); do
    [ -e "$OPS_PORT" ] && [ -e /dev/ttyUSB0 ] && break
    sleep 1
done

# Reset the speed radar through its /Reset pin (replaces unplugging it or
# power-cycling the USB port when it gets stuck with its LED solid).
reset_ops() {
    [ -n "$OPS_RESET_GPIO" ] || return 0
    pinctrl set "$OPS_RESET_GPIO" op dl
    sleep 0.2
    pinctrl set "$OPS_RESET_GPIO" op dh
    sleep 2.5        # the OPS takes about 2 s to start up again
}

# The kiosk turns the screen's backlight off while asleep. If it ever stops
# while asleep, put the backlight back before the menu comes up.
screen_on() {
    [ -f /tmp/modus-backlight ] || return 0
    while read -r path value; do
        echo "$value" > "$path" 2>/dev/null || echo "$value" | sudo -n tee "$path" >/dev/null 2>&1
    done < <(tac /tmp/modus-backlight)
    rm -f /tmp/modus-backlight
}

source ~/vision-env/bin/activate

OPEN="--open-browser"   # open the full-screen browser the first time only
NOTE=""
while true; do
    screen_on
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
        inside) CAM_SENSOR=$INSIDE_SENSOR;  FPS=$INSIDE_FPS;  RECORDING=$INSIDE_RECORDING
                SLEEP_MIN=$INSIDE_SLEEP_MINUTES ;;
        *)      MODE=outside
                CAM_SENSOR=$OUTSIDE_SENSOR; FPS=$OUTSIDE_FPS; RECORDING=$OUTSIDE_RECORDING
                SLEEP_MIN=$OUTSIDE_SLEEP_MINUTES ;;
    esac
    DETECT="'--trigger','motion,sound','--blob'"
    MODELARG=""
    if [ -n "$MODEL" ]; then
        MODELARG="'--model','$MODEL',"
    fi
    DUMPS=""
    if [ "$TI_DUMPS" = "1" ]; then
        DUMPS="'--iwr-save-dumps',"
    fi
    LOG="logs/kiosk_$(date +%Y%m%d_%H%M%S)_${MODE}.log"
    reset_ops
    echo "Starting kiosk: $MODE mode, club $CLUB, recording $RECORDING, camera $CAM_SENSOR at $FPS fps, sleep after $SLEEP_MIN min (log: $LOG)"
    python3 -c "import logging,runpy,sys; logging.basicConfig(level=logging.INFO); sys.path.insert(0,'camera'); sys.argv=['kiosk.py','--iwr','--ops',$DETECT,'--no-browser','--iwr-tee-m','$TEE_M','--iwr-net-m','$NET_M','--iwr-tilt-deg','$TILT_DEG','--iwr-radar-height-m','$RADAR_H','--iwr-ball-height-m','$BALL_H','--iwr-azimuth-offset-deg','$AZIMUTH_DEG',$DUMPS$MODELARG'--recording','$RECORDING','--sensor','$CAM_SENSOR','--fps','$FPS','--gate-gpio','$GATE_GPIO','--radar-port','$OPS_PORT','--ops-trigger','$OPS_TRIGGER','--trigger-out-gpio','$TRIGGER_OUT_GPIO','--motion-threshold','$MOTION_THRESHOLD','--hold-seconds','$HOLD_SECONDS','--ops-trigger-mph','$OPS_TRIGGER_MPH','--sleep-minutes','$SLEEP_MIN','--sleep-screen','$SLEEP_SCREEN','--club','$CLUB']; runpy.run_path('camera/kiosk.py', run_name='__main__')" >> "$LOG" 2>&1
    code=$?
    if [ $code -ne 0 ]; then
        echo "Kiosk stopped unexpectedly (code $code)" >> "$LOG"
        NOTE="The last run stopped unexpectedly. Check the log, or press Start to try again."
        sleep 2
    fi
    # Back to the menu.
done
