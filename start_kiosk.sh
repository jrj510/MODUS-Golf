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
RADAR_H=0.06985    # antenna centre above the ground, metres (2.75 in, measured with the box tipped back 10 deg)
BALL_H=0.021       # ball centre above the ground, metres (0.021 = ball on the ground; on a mat add its thickness)
AZIMUTH_DEG=0      # radars point this far right of the target line (left = negative), degrees
GATE_GPIO=20       # trigger input the TI radar listens on: GPIO20 = pin 38 (was 17 = pin 11)
OPS_PORT=/dev/ttyAMA0   # speed radar on the Pi's UART (J3 pins 6/7 to Pi pins 8/10); USB would be /dev/ttyACM0
HOLD_SECONDS=5      # ball covered (hand, club, foot) this long -> back to Looking for Ball
MOTION_THRESHOLD=12 # camera trigger: how much the ball's spot must change (0-255) when the ball leaves.
                   # Was 25; lab shots only changed it by 13-16, so half were missed
# Shadow guard: before a sudden change at the ball's spot counts as a shot (and
# pulses the radars), the camera checks the ball isn't simply still there under
# a shadow (the golfer's, late in the day) or a change of light. Also keeps
# Ready while a shadow sits on the ball. Pictures of each decision go to
# shots/shadow_checks/ (newest 40 of each kind). off = exactly as before.
OUTSIDE_SHADOW_GUARD=on
INSIDE_SHADOW_GUARD=off
# Radar check: the camera's trigger pulses the speed radar, and OpenFlight says
# whether anything flew away. on = a camera trigger only counts as a shot if
# the speed radar saw a ball leave; a shadow or the golfer moving (nothing
# flying away) is no shot, and Ready comes back only once the radar has
# finished reading out (so Ready means camera AND radar are ready). A shot the
# radar can't see (a chip under 15 mph) is then not counted either: it had no
# numbers anyway. off = the camera decides on its own, as before.
OUTSIDE_RADAR_CONFIRM=on
INSIDE_RADAR_CONFIRM=off
OPS_TRIGGER=sound  # sound = the OPS waits for a pulse on J3-3 (from the camera or the sound detector);
                   # speed = the OPS triggers itself (picked up noise here, so not used)
TRIGGER_OUT_GPIO=21 # camera trigger: GPIO21 (pin 40) pulses OPS J3-3 and GPIO20 (pin 38) when the
                   # camera sees the ball leave. 0 = off (only if the sound detector is wired again)
# Speed radar history. With the camera as the trigger (TRIGGER_OUT_GPIO), the
# pulse reaches the OPS ~4 camera frames after the ball leaves, because the
# camera checks the ball is really gone first. That is ~90 ms after impact at
# 60 fps, ~40 ms at 144 fps. OpenFlight's default buffer (made for a sound
# trigger at impact) then no longer holds the club coming in: no club speed.
# These say how many of the OPS buffer's 32 blocks (~4.3 ms each, 136 ms in all)
# come from before the trigger. Only used with the camera trigger.
OUTSIDE_OPS_PRE_TRIGGER=30   # 128 ms before the trigger: club + ~90 ms of ball at 60 fps
INSIDE_OPS_PRE_TRIGGER=20    # 85 ms before + 51 ms after: club + ~90 ms of ball at 144 fps
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
MODEL=             # ball model; empty = OpenFlight's (until ours is trained). Ours, after
                   # camera/train_ball_model.py:  MODEL=~/MODUS-Golf/models/modus_ball_256.onnx
BACKUP_MODEL=~/openflight/models/golf_ball_yolo11n_new_256.onnx
                   # used only once MODEL is ours: looks when ours finds nothing (at most once a
                   # second) and the log says when it found a ball ours missed. Empty = no backup.
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
                SLEEP_MIN=$INSIDE_SLEEP_MINUTES; OPS_PRE=$INSIDE_OPS_PRE_TRIGGER
                GUARD=$INSIDE_SHADOW_GUARD; CONFIRM=$INSIDE_RADAR_CONFIRM ;;
        *)      MODE=outside
                CAM_SENSOR=$OUTSIDE_SENSOR; FPS=$OUTSIDE_FPS; RECORDING=$OUTSIDE_RECORDING
                SLEEP_MIN=$OUTSIDE_SLEEP_MINUTES; OPS_PRE=$OUTSIDE_OPS_PRE_TRIGGER
                GUARD=$OUTSIDE_SHADOW_GUARD; CONFIRM=$OUTSIDE_RADAR_CONFIRM ;;
    esac
    DETECT="'--trigger','motion,sound','--blob'"
    MODELARG=""
    if [ -n "$MODEL" ]; then
        MODELARG="'--model','$MODEL',"
        if [ -n "$BACKUP_MODEL" ]; then
            MODELARG="$MODELARG'--backup-model','$BACKUP_MODEL',"
        fi
    fi
    DUMPS=""
    if [ "$TI_DUMPS" = "1" ]; then
        DUMPS="'--iwr-save-dumps',"
    fi
    OPSPREARG=""
    if [ "$TRIGGER_OUT_GPIO" != "0" ] && [ -n "$OPS_PRE" ]; then
        OPSPREARG="'--ops-pre-trigger','$OPS_PRE',"
    fi
    LOG="logs/kiosk_$(date +%Y%m%d_%H%M%S)_${MODE}.log"
    reset_ops
    echo "Starting kiosk: $MODE mode, club $CLUB, recording $RECORDING, camera $CAM_SENSOR at $FPS fps, sleep after $SLEEP_MIN min, shadow guard $GUARD, radar check ${CONFIRM:-off} (log: $LOG)"
    python3 -c "import logging,runpy,sys; logging.basicConfig(level=logging.INFO); sys.path.insert(0,'camera'); sys.argv=['kiosk.py','--iwr','--ops',$DETECT,'--no-browser','--iwr-tee-m','$TEE_M','--iwr-net-m','$NET_M','--iwr-tilt-deg','$TILT_DEG','--iwr-radar-height-m','$RADAR_H','--iwr-ball-height-m','$BALL_H','--iwr-azimuth-offset-deg','$AZIMUTH_DEG',$DUMPS$MODELARG$OPSPREARG'--recording','$RECORDING','--sensor','$CAM_SENSOR','--fps','$FPS','--gate-gpio','$GATE_GPIO','--radar-port','$OPS_PORT','--ops-trigger','$OPS_TRIGGER','--trigger-out-gpio','$TRIGGER_OUT_GPIO','--motion-threshold','$MOTION_THRESHOLD','--hold-seconds','$HOLD_SECONDS','--shadow-guard','${GUARD:-off}','--radar-confirm','${CONFIRM:-off}','--ops-trigger-mph','$OPS_TRIGGER_MPH','--sleep-minutes','$SLEEP_MIN','--sleep-screen','$SLEEP_SCREEN','--club','$CLUB']; runpy.run_path('camera/kiosk.py', run_name='__main__')" >> "$LOG" 2>&1
    code=$?
    if [ $code -ne 0 ]; then
        echo "Kiosk stopped unexpectedly (code $code)" >> "$LOG"
        NOTE="The last run stopped unexpectedly. Check the log, or press Start to try again."
        sleep 2
    fi
    # Back to the menu.
done
