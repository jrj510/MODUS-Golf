#!/bin/bash
# Starts MODUS-Golf: the start menu on the screen, then the kiosk with the
# options picked there. The kiosk's Menu button comes back to the menu.
# Run by the desktop at login (see modus-kiosk.desktop), or by hand:
#     ~/MODUS-Golf/start_kiosk.sh
#
# Change the settings below if the setup changes.
# Logs go to ~/MODUS-Golf/logs/, shot logs to ~/MODUS-Golf/logs/sessions/

# Speed radar (OPS243-A) in rolling-buffer mode: it records raw I/Q nonstop;
# on a trigger we read the recording (~2 s at 230400 baud, set automatically)
# and work out ball and club speed with our own FFT (camera/ops_capture.py).
# The radar triggers itself (OPS_SPEED_TRIGGER) and the camera's pulse on
# J3 pin 3 triggers it too; together they decide what is a shot
# (camera/shot_fusion.py):
#   both fire            -> shot with the radar's speeds
#   radar only           -> shot, unless the camera still sees the ball sitting there
#   camera only          -> shot with no speeds (see RADAR_CONFIRM)
SPEED_RADAR=on     # off = camera only
OPS_PORT=/dev/ttyAMA0   # speed radar on the Pi's UART (J3 pins 6/7 to Pi pins 8/10); USB would be /dev/ttyACM0
OPS_SPLIT=4        # of the recording's 32 blocks (4.3 ms each), how many from before the trigger
                   # (17 ms before, 119 ms after: a fast club trips the trigger well before impact)
OPS_SPEED_TRIGGER=auto  # radar records by itself when something moves away faster than this, mph;
                        # auto = by club (driver 75, irons 50-65, wedges 40); 0 = off
OPS_MIN_BALL=30    # slowest ball the radar counts as a shot, mph (radar view, before any angle
                   # correction; 30 caught a heeled wedge with no false shots, 25 gave false ones)
SPEED_CORRECTION=on  # on = ball speed corrected for the radar's line of sight (raw reading kept in the
                     # session log); 21 Nov 2026 TrackMan: raw read 2.9% low, corrected 0.9%. off = raw
RADAR_FROM_CAMERA=off  # off = camera and radar trigger independently (a false camera trigger
                       # can't keep the radar busy through the real swing); on = the camera
                       # also triggers the radar (soft shots under the radar's trigger speed)
RADAR_CONFIRM=off  # on = a camera trigger with no radar shot is NOT a shot (no speedless chips, but
                   # a shadow or the golfer moving can never count either)
OPS_RESET_GPIO=23  # wired to OPS J3 pin 4 (/Reset); the OPS is reset each time the kiosk starts. Empty = off
GATE_GPIO=20       # sound trigger input: GPIO20 = pin 38 (was 17 = pin 11)
BALL_H=0.021       # ball centre above the ground, metres (0.021 = ball on the ground; on a mat add its thickness)
HOLD_SECONDS=10     # ball covered (club at address, hand, foot) this long -> back to Looking for Ball
MOTION_THRESHOLD=12 # camera trigger: how much the ball's spot must change (0-255) when the ball leaves.
                   # Was 25; lab shots only changed it by 13-16, so half were missed
# Shadow guard: before a sudden change at the ball's spot counts as a shot (and
# pulses the radars), the camera checks the ball isn't simply still there under
# a shadow (the golfer's, late in the day) or a change of light. Also keeps
# Ready while a shadow sits on the ball. Pictures of each decision go to
# shots/shadow_checks/ (newest 40 of each kind). off = exactly as before.
OUTSIDE_SHADOW_GUARD=on
INSIDE_SHADOW_GUARD=on    # same checks in both modes
# Cover guard: setting the club down behind the ball hides it from the camera,
# which looked like the ball leaving (Checking at address, then Looking for
# Ball). on = the camera tells the club at address from the ball leaving (the
# top of the ball is still there, the turf beside it goes dark), keeps Ready
# while the ball is covered (up to HOLD_SECONDS), sends no radar pulse, and
# arms the trigger again the moment the backswing uncovers the ball. Pictures
# of each decision go to shots/shadow_checks/ (..._covered.png). off = as before.
OUTSIDE_COVER_GUARD=on
INSIDE_COVER_GUARD=on
TRIGGER_OUT_GPIO=21 # camera trigger: GPIO21 (pin 40) pulses OPS J3-3 and GPIO20 (pin 38) when the
                   # camera sees the ball leave. 0 = off (only if the sound detector is wired again)
# Pulse timing. With the camera as the trigger (TRIGGER_OUT_GPIO), the camera
# checks the ball is really gone before it pulses: ~4.5 camera frames after the
# ball leaves, ~75 ms at 60 fps but only ~31 ms at 144 fps. RADAR_PULSE_FPS
# makes both modes pulse when a camera at that frame rate would (60 = Outside's
# timing), so the pulse lands at the same moment in both modes.
# 0 = pulse straight away.
RADAR_PULSE_FPS=0  # 0 = pulse at once. The radar keeps only 43 ms from before a pulse
                   # (OPS_SPLIT=10); held back to 60 fps timing (~55 ms) a driver
                   # indoors was already in the net (2026-11-21: no ball in those recordings)

# Power. The moment after a shot is the heaviest load (whatever the camera
# saves); on a battery pack that spike can shut the Pi off. These keep it down:
# The start menu's two modes. Both use the camera as the shot trigger.
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
INSIDE_RECORDING=flight # flight = the frames of the ball leaving are saved per shot (no replay),
                        # for tuning the camera launch angle; set back to off once it's tuned.
                        # (off = nothing saved; full = slow-motion Shot Preview with Save/Delete)
# Camera launch angle: the ball's first frames of flight, through the
# pixel-to-angle grid, with the speed radar's ball speed (camera/launch_camera.py).
# The lens calibrates itself from balls at rest; for that, measure these two once:
INSIDE_CAM_LAUNCH=on
OUTSIDE_CAM_LAUNCH=off
CAM_HEIGHT_M=0.119     # camera lens height above the ground, metres (4 11/16 in, measured)
CAM_BALL_M=1.578       # camera lens to the ball, along the ground, metres (1/8 in farther than the radar)
# Sleep. The moon button (top right) puts the box to sleep: camera off,
# screen dark; tap the screen to wake (about 3-5 s). It also sleeps by itself
# after this many minutes of Looking for Ball with no ball, no shot and no taps
# on the screen; 0 = button only. Never in the middle of a shot.
OUTSIDE_SLEEP_MINUTES=3   # on the course: sleeps on the walk to the ball
INSIDE_SLEEP_MINUTES=5
SLEEP_SCREEN=off   # off = backlight off while asleep (saves the most);
                   # black = backlight on, screen black (only if a tap doesn't wake it with the backlight off)
SCREEN_BRIGHTNESS=max   # set when this script starts (every boot): max = the screen's brightest,
                        # a number = that level (see /sys/class/backlight/*/max_brightness),
                        # empty = leave it as it is
MODEL=~/MODUS-Golf/models/modus_ball_256.onnx
                   # ball model: ours, trained on our camera's pictures (camera/train_ball_model.py).
                   # The only one used: if the file isn't on the Pi, the start menu says so and the
                   # camera looks for the ball with its small-ball finder only.
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

# Give the speed radar's port a moment to appear after boot.
for i in $(seq 1 20); do
    [ -e "$OPS_PORT" ] && break
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

# Screen brightness, once at start (so after every reboot). Waking from sleep
# puts back whatever level the screen had, so this level stays.
set_brightness() {
    [ -n "$SCREEN_BRIGHTNESS" ] || return 0
    for d in /sys/class/backlight/*; do
        [ -e "$d/brightness" ] || continue
        if [ "$SCREEN_BRIGHTNESS" = max ]; then
            level=$(cat "$d/max_brightness" 2>/dev/null) || continue
        else
            level=$SCREEN_BRIGHTNESS
        fi
        echo "$level" > "$d/brightness" 2>/dev/null \
            || echo "$level" | sudo -n tee "$d/brightness" >/dev/null 2>&1 \
            || echo "Screen brightness: couldn't set $d (needs write access or sudo)" >> logs/launcher.log
    done
}

source ~/vision-env/bin/activate
screen_on
set_brightness

OPEN="--open-browser"   # open the full-screen browser the first time only
NOTE=""
while true; do
    screen_on
    if [ -z "$NOTE" ] && [ ! -f "${MODEL/#\~/$HOME}" ]; then
        NOTE="Ball model not found on the Pi ($MODEL): copy it there (camera/train_ball_model.py says how). Until then the camera only uses its small-ball finder."
    fi
    CHOICE=$(python3 camera/launcher.py $OPEN --note "$NOTE" 2>>logs/launcher.log)
    if [ -z "$CHOICE" ]; then
        sleep 2
        continue
    fi
    if [ "$CHOICE" = "shutdown" ]; then
        # Shut Down button on the start menu: the same as typing sudo shutdown now.
        echo "$(date '+%F %T') Shut Down pressed on the start menu" >> logs/launcher.log
        sudo -n shutdown -h now 2>>logs/launcher.log || systemctl poweroff 2>>logs/launcher.log
        sleep 20     # powering off; if it didn't, the menu comes back and says so
        OPEN=""      # the menu's browser window is still open and reloads itself
        NOTE="Couldn't shut down from the menu (see logs/launcher.log). Use sudo shutdown now over SSH."
        continue
    fi
    OPEN=""
    NOTE=""
    MODE=${CHOICE%%,*}
    CLUB=${CHOICE##*,}
    case "$MODE" in
        inside) CAM_SENSOR=$INSIDE_SENSOR;  FPS=$INSIDE_FPS;  RECORDING=$INSIDE_RECORDING
                SLEEP_MIN=$INSIDE_SLEEP_MINUTES
                GUARD=$INSIDE_SHADOW_GUARD; COVER=$INSIDE_COVER_GUARD
                CAMLAUNCH=$INSIDE_CAM_LAUNCH ;;
        *)      MODE=outside
                CAM_SENSOR=$OUTSIDE_SENSOR; FPS=$OUTSIDE_FPS; RECORDING=$OUTSIDE_RECORDING
                SLEEP_MIN=$OUTSIDE_SLEEP_MINUTES
                GUARD=$OUTSIDE_SHADOW_GUARD; COVER=$OUTSIDE_COVER_GUARD
                CAMLAUNCH=$OUTSIDE_CAM_LAUNCH ;;
    esac
    DETECT="'--trigger','motion,sound','--blob'"
    OPSARG=""
    if [ "$SPEED_RADAR" = "on" ]; then
        OPSARG="'--ops','--ops-split','$OPS_SPLIT','--ops-speed-trigger-mph','$OPS_SPEED_TRIGGER','--ops-min-ball','$OPS_MIN_BALL','--ops-reset-gpio','0',"
    fi
    MODELARG="'--model','$MODEL',"
    LOG="logs/kiosk_$(date +%Y%m%d_%H%M%S)_${MODE}.log"
    reset_ops
    echo "Starting kiosk: $MODE mode, club $CLUB, recording $RECORDING, camera $CAM_SENSOR at $FPS fps, sleep after $SLEEP_MIN min, shadow guard $GUARD, cover guard ${COVER:-off}, speed radar ${SPEED_RADAR:-off} (radar check ${RADAR_CONFIRM:-off}), pulse as at ${RADAR_PULSE_FPS:-0} fps, camera launch ${CAMLAUNCH:-off} (log: $LOG)"
    python3 -c "import logging,runpy,sys; logging.basicConfig(level=logging.INFO); sys.path.insert(0,'camera'); sys.argv=['kiosk.py',$OPSARG$DETECT,'--no-browser','--ball-height-m','$BALL_H',$MODELARG'--recording','$RECORDING','--sensor','$CAM_SENSOR','--fps','$FPS','--gate-gpio','$GATE_GPIO','--radar-port','$OPS_PORT','--trigger-out-gpio','$TRIGGER_OUT_GPIO','--radar-pulse-fps','${RADAR_PULSE_FPS:-0}','--motion-threshold','$MOTION_THRESHOLD','--hold-seconds','$HOLD_SECONDS','--shadow-guard','${GUARD:-off}','--radar-confirm','${RADAR_CONFIRM:-off}','--radar-from-camera','${RADAR_FROM_CAMERA:-off}','--speed-correction','${SPEED_CORRECTION:-off}','--cover-guard','${COVER:-off}','--cam-launch','${CAMLAUNCH:-off}','--cam-height-m','$CAM_HEIGHT_M','--cam-ball-m','$CAM_BALL_M','--sleep-minutes','$SLEEP_MIN','--sleep-screen','$SLEEP_SCREEN','--club','$CLUB']; runpy.run_path('camera/kiosk.py', run_name='__main__')" >> "$LOG" 2>&1
    code=$?
    if [ $code -ne 0 ]; then
        echo "Kiosk stopped unexpectedly (code $code)" >> "$LOG"
        NOTE="The last run stopped unexpectedly. Check the log, or press Start to try again."
        sleep 2
    fi
    # Back to the menu.
done
