#!/bin/bash
# Starts MODUS-Golf: the start menu on the screen, then the kiosk with the
# options picked there. The kiosk's Menu button comes back to the menu.
# Run by the desktop at login (see modus-kiosk.desktop), or by hand:
#     ~/MODUS-Golf/start_kiosk.sh
#
# Change the settings below if the setup changes.
# Logs go to ~/MODUS-Golf/logs/, shot logs to ~/MODUS-Golf/logs/sessions/

TEE_M=1.575        # radar to ball, metres (5 ft 2 in)
NET_M=4.6          # radar to the net / box, metres
TILT_DEG=0         # radar tilt, degrees
RADAR_H=0.077      # antenna centre above the floor, metres
BALL_H=0.021       # ball centre above the floor, metres (ball on a mat)
GATE_GPIO=17       # GPIO the sound sensor GATE is wired to (17 = pin 11, 26 = pin 37)

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
    if [ "$MODE" = "sound" ]; then
        DETECT="'--trigger','sound','--no-ball'"
    else
        DETECT="'--trigger','motion,sound','--blob'"
    fi
    LOG="logs/kiosk_$(date +%Y%m%d_%H%M%S)_${MODE}.log"
    echo "Starting kiosk: $MODE detection, club $CLUB (log: $LOG)"
    python3 -c "import logging,runpy,sys; logging.basicConfig(level=logging.INFO); sys.path.insert(0,'camera'); sys.argv=['kiosk.py','--iwr','--ops',$DETECT,'--no-browser','--iwr-tee-m','$TEE_M','--iwr-net-m','$NET_M','--iwr-tilt-deg','$TILT_DEG','--iwr-radar-height-m','$RADAR_H','--iwr-ball-height-m','$BALL_H','--iwr-save-dumps','--gate-gpio','$GATE_GPIO','--club','$CLUB']; runpy.run_path('camera/kiosk.py', run_name='__main__')" >> "$LOG" 2>&1
    code=$?
    if [ $code -ne 0 ]; then
        echo "Kiosk stopped unexpectedly (code $code)" >> "$LOG"
        NOTE="The last run stopped unexpectedly. Check the log, or press Start to try again."
        sleep 2
    fi
    # Back to the menu.
done
