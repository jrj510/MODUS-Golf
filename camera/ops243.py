"""MODUS Golf: OPS243-A speed radar driver and shot detector (our own code).

Talks to the OmniPreSense OPS243-A over the Pi's UART (J3 pins 6/7 to Pi pins
8/10, /dev/ttyAMA0) and turns its speed reports into a ball speed, a club
speed and a smash factor.

Radar settings come from OmniPreSense's application note AN-029 ("OPS243 for
Sports Applications", Table 6, Golf Recommended API Settings):

    S=30   sample rate 30 ksps   -> max detectable speed ~209 mph
    S(     sample size 128       -> report rate near 200 Hz (~5 ms)
    X=32   FFT size 4096         -> 0.1 mph speed resolution
    US     units mph
    R>10   speed filter >10 mph  -> drops slow club/body movement
    M>10   magnitude threshold   -> detection distance (10 or 15)
    O2     multi-speed           -> top 2 speeds per report (ball and club)
    K+     peak detect           -> focuses the multi-speed reports

How a shot looks in those reports (AN-029 Figure 5): the club climbs to its
peak just before impact and then falls away, while the ball appears as a
fast, almost flat line that starts at impact. So:

  * ball  = the first run of reports whose top speed holds steady (within a
            few mph) for several reports in a row, clearly faster than
            anything before it. Ball speed is the median of the start of
            that run (the ball slows only slightly over the first 15 ms).
  * club  = the highest speed of the *other* track that a neighbouring report
            agrees with (so one noisy report can't set it), from just
            before the ball appears to just after.
  * smash = ball / club, only kept if it's physically sensible (1.0-1.6).

Run it on the Pi:
    python3 camera/ops243.py                      # configure, then print shots
    python3 camera/ops243.py --raw                # print every report line
    python3 camera/ops243.py --log swings.csv     # also save every report
    python3 camera/ops243.py --replay swings.csv  # rerun detection on a log
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

# --------------------------------------------------------------------------
# Radar settings (AN-029 Table 6). (command, needs Enter)
# --------------------------------------------------------------------------
GOLF_SETTINGS: list[tuple[str, bool]] = [
    ("S=30", True),   # sample rate 30 ksps
    ("S(", False),    # sample size 128
    ("X=32", False),  # FFT size 4096
    ("US", False),    # mph
    ("R>10", True),   # ignore anything under 10 mph
    ("M>10", True),   # magnitude threshold (try 15 if it picks up noise)
    ("O2", False),    # top two speeds per report
    ("K+", False),    # peak detect
]

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class Report:
    """One speed report from the radar."""
    t: float                  # seconds, Pi clock (time.monotonic)
    speeds: list[float]       # mph, fastest first, direction sign removed


def parse_line(line: str, t: float) -> Optional[Report]:
    """Turn one line from the radar into a Report, or None if it isn't one.

    Handles plain output ("132.4" or "132.4,98.1", optionally with "mph"
    units) and JSON output ({"speed": [132.4, 98.1]} or {"speed": "132.4"}).
    Command acknowledgements such as {"SampleRate": 30000} are ignored.
    """
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        try:
            obj = json.loads(line)
        except ValueError:
            return None
        raw = obj.get("speed")
        if raw is None:
            return None
        if not isinstance(raw, list):
            raw = [raw]
        try:
            values = [abs(float(v)) for v in raw]
        except (TypeError, ValueError):
            return None
    else:
        # Plain text: only accept lines made of numbers, separators and units
        # (so settings echoes and help text are skipped).
        if re.search(r"[A-Za-z]", line.replace("mph", "").replace("mps", "")
                     .replace("kmh", "").replace("m/s", "")):
            return None
        values = [abs(float(v)) for v in _NUMBER.findall(line)]
    values = [v for v in values if v > 0]
    if not values:
        return None
    return Report(t=t, speeds=sorted(values, reverse=True))


# --------------------------------------------------------------------------
# Shot detection
# --------------------------------------------------------------------------
@dataclass
class DetectorConfig:
    min_ball_mph: float = 40.0      # slowest ball that counts as a shot
    max_ball_mph: float = 209.0     # radar's limit at 30 ksps
    hold_tol_mph: float = 3.0       # how flat the ball line must be
    hold_reports: int = 4           # reports in a row to call it a ball
    jump_ratio: float = 1.05        # ball must beat the earlier max by 5%
    ball_avg_s: float = 0.015       # average the ball over its first 15 ms
    club_before_s: float = 0.080    # look for the club up to 80 ms before impact
    club_after_s: float = 0.040     # ...and 40 ms after (club falls away)
    club_min_mph: float = 20.0
    club_tol_mph: float = 6.0       # a club reading needs a neighbour this close
    smash_min: float = 1.0
    smash_max: float = 1.6
    settle_s: float = 0.060         # wait this long after impact before reporting
    cooldown_s: float = 1.5         # ignore reports for this long after a shot
    history_s: float = 0.5          # how much radar history to keep


@dataclass
class Shot:
    t_impact: float
    ball_mph: float
    club_mph: Optional[float]
    smash: Optional[float]
    ball_reports: int
    club_track: list[tuple[float, float]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "t_impact": round(self.t_impact, 4),
            "ball_mph": round(self.ball_mph, 1),
            "club_mph": None if self.club_mph is None else round(self.club_mph, 1),
            "smash": None if self.smash is None else round(self.smash, 2),
            "ball_reports": self.ball_reports,
        }


def _supported_peak(values: list[float], tol: float) -> Optional[float]:
    """Highest value that a neighbouring report agrees with (within tol).

    A lone spike has no neighbour near it, so it can't set the club speed,
    but the real peak (where the club is near-flat at impact) keeps its value.
    """
    good = [v for i, v in enumerate(values)
            if any(abs(v - values[j]) <= tol
                   for j in (i - 1, i + 1) if 0 <= j < len(values))]
    return max(good) if good else None


def find_ball(reports: list[Report], cfg: DetectorConfig,
              fastest: bool = False) -> Optional[int]:
    """Index of the report where the ball first appears, or None.

    With fastest=False, returns the first steady run (used to notice that a
    shot is happening). With fastest=True, returns the start of the fastest
    steady run in the window: a slow, steady club near its peak can also look
    like a flat line, but the ball is always the faster one.
    """
    tops = [r.speeds[0] for r in reports]
    n = cfg.hold_reports
    found: list[tuple[int, float]] = []
    for i in range(len(tops) - n + 1):
        run = tops[i:i + n]
        level = statistics.median(run)
        if not (cfg.min_ball_mph <= level <= cfg.max_ball_mph):
            continue
        if max(run) - min(run) > 2 * cfg.hold_tol_mph:
            continue
        if any(abs(v - level) > cfg.hold_tol_mph for v in run):
            continue
        before = [s for r in reports[:i] if r.t >= reports[i].t - cfg.club_before_s
                  for s in r.speeds]
        if before and level < cfg.jump_ratio * max(before):
            continue  # not clearly faster than what came before: still the club
        if not fastest:
            return i
        found.append((i, level))
    if not found:
        return None
    top = max(level for _, level in found)
    return next(i for i, level in found if level >= top - cfg.hold_tol_mph)


def measure_shot(reports: list[Report], i_ball: int, cfg: DetectorConfig) -> Shot:
    """Ball speed, club speed and smash around a ball found at i_ball."""
    t0 = reports[i_ball].t
    level = statistics.median(r.speeds[0] for r in reports[i_ball:i_ball + cfg.hold_reports])

    def is_ball(v: float) -> bool:
        return abs(v - level) <= cfg.hold_tol_mph * 2

    ball = [r.speeds[0] for r in reports[i_ball:]
            if r.t <= t0 + cfg.ball_avg_s and is_ball(r.speeds[0])]
    ball_mph = statistics.median(ball)

    # Club track: per report, the fastest speed that isn't the ball.
    track: list[tuple[float, float]] = []
    for r in reports:
        if not (t0 - cfg.club_before_s <= r.t <= t0 + cfg.club_after_s):
            continue
        others = [s for s in r.speeds
                  if not is_ball(s) and cfg.club_min_mph <= s < ball_mph]
        if others:
            track.append((r.t, others[0]))

    club_mph = smash = None
    peak = _supported_peak([v for _, v in track], cfg.club_tol_mph)
    if peak is not None:
        club_mph = peak
        smash = ball_mph / club_mph
        if not (cfg.smash_min <= smash <= cfg.smash_max):
            club_mph = smash = None  # not a believable club reading
    return Shot(t_impact=t0, ball_mph=ball_mph, club_mph=club_mph, smash=smash,
                ball_reports=len(ball), club_track=track)


class ShotDetector:
    """Feed it reports as they arrive; it calls on_shot once per shot."""

    def __init__(self, on_shot: Callable[[Shot], None],
                 cfg: Optional[DetectorConfig] = None):
        self.cfg = cfg or DetectorConfig()
        self.on_shot = on_shot
        self.history: deque[Report] = deque()
        self.quiet_until = 0.0
        self.pending: Optional[float] = None  # impact time waiting to settle

    def feed(self, rep: Report) -> None:
        cfg = self.cfg
        if rep.t < self.quiet_until:
            return
        self.history.append(rep)
        while self.history and self.history[0].t < rep.t - cfg.history_s:
            self.history.popleft()

        reports = list(self.history)
        if self.pending is None:
            i = find_ball(reports, cfg)
            if i is not None:
                self.pending = reports[i].t
        if self.pending is not None and rep.t >= self.pending + cfg.settle_s:
            self.flush()

    def flush(self) -> Optional[Shot]:
        """Finish a shot that's waiting (also call this when the radar goes quiet)."""
        if self.pending is None:
            return None
        reports = list(self.history)
        i = find_ball(reports, self.cfg, fastest=True)
        shot = None
        if i is not None:
            shot = measure_shot(reports, i, self.cfg)
            self.on_shot(shot)
            self.quiet_until = shot.t_impact + self.cfg.cooldown_s
        self.pending = None
        self.history.clear()
        return shot


# --------------------------------------------------------------------------
# Serial driver
# --------------------------------------------------------------------------
BAUD_RATES = (19200, 57600, 115200, 9600, 230400)   # rates the OPS243 supports, likeliest first


def reset_radar(gpio: Optional[int]) -> None:
    """Pulse the OPS's /Reset pin (J3 pin 4) low, then wait for it to boot."""
    if not gpio:
        return
    import subprocess
    print(f"Resetting the radar (GPIO{gpio} -> J3 pin 4)...")
    try:
        subprocess.run(["pinctrl", "set", str(gpio), "op", "dl"], check=True)
        time.sleep(0.2)
        subprocess.run(["pinctrl", "set", str(gpio), "op", "dh"], check=True)
        time.sleep(2.5)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"  could not reset it ({e}); carrying on")


def find_baud(port: str, rates: Iterable[int] = BAUD_RATES) -> Optional[int]:
    """Ask the radar for its module info ("??") at each baud rate; return the
    first rate that gets a readable answer, or None."""
    import serial
    for baud in rates:
        try:
            with serial.Serial(port, baud, timeout=0.3) as ser:
                ser.reset_input_buffer()
                ser.write(b"??")
                time.sleep(0.6)
                data = ser.read(ser.in_waiting or 1)
        except serial.SerialException as e:
            print(f"  {port}: {e}")
            return None
        text = data.decode("ascii", "replace")
        readable = sum(c.isprintable() or c in "\r\n" for c in text)
        print(f"  {baud:>6} baud: " + (repr(text[:120]) if data else "nothing"))
        if data and readable >= 0.9 * len(text) and any(c.isalnum() for c in text):
            return baud
    return None


class OPS243:
    """The radar on a serial port. Reads in a background thread."""

    def __init__(self, port: str = "/dev/ttyAMA0", baud: int = 19200):
        import serial  # pyserial
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def send(self, cmd: str, enter: bool = False, wait: float = 0.15) -> list[str]:
        """Send one API command; return whatever the radar answered."""
        self.ser.write((cmd + ("\r" if enter else "")).encode("ascii"))
        self.ser.flush()
        time.sleep(wait)
        replies = []
        while self.ser.in_waiting:
            replies.append(self.ser.readline().decode("ascii", "replace").strip())
        return [r for r in replies if r]

    def configure(self, settings: Iterable[tuple[str, bool]] = GOLF_SETTINGS,
                  verbose: bool = True) -> None:
        self.ser.reset_input_buffer()
        for cmd, enter in settings:
            replies = self.send(cmd, enter)
            if verbose:
                print(f"  {cmd:<6} -> {' | '.join(replies) or '(no reply)'}")

    def start(self, on_report: Callable[[Report, str], None],
              on_other: Optional[Callable[[str], None]] = None) -> None:
        """on_report gets every speed report; on_other every other line."""
        def loop() -> None:
            while not self._stop.is_set():
                raw = self.ser.readline()
                if not raw:
                    continue
                t = time.monotonic()
                line = raw.decode("ascii", "replace").strip()
                rep = parse_line(line, t)
                if rep is not None:
                    on_report(rep, line)
                elif on_other is not None and line:
                    on_other(line)
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self.ser.close()


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
def print_shot(shot: Shot) -> None:
    club = "--" if shot.club_mph is None else f"{shot.club_mph:.1f}"
    smash = "--" if shot.smash is None else f"{shot.smash:.2f}"
    print(f"SHOT  ball {shot.ball_mph:.1f} mph   club {club} mph   smash {smash}",
          flush=True)


def replay(path: str, cfg: DetectorConfig) -> list[Shot]:
    shots: list[Shot] = []
    det = ShotDetector(lambda s: (shots.append(s), print_shot(s)), cfg)
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rep = parse_line(row["line"], float(row["t"]))
            if rep:
                det.feed(rep)
    det.flush()
    return shots


def main(argv: Optional[list[str]] = None) -> None:
    p = argparse.ArgumentParser(description="MODUS OPS243-A driver")
    p.add_argument("--port", default="/dev/ttyAMA0")
    p.add_argument("--baud", type=int, default=0,
                   help="serial baud rate; 0 = find it (tries 19200, 57600, 115200, 9600, 230400)")
    p.add_argument("--reset-gpio", type=int, default=23,
                   help="GPIO wired to OPS J3 pin 4 (/Reset); reset before starting. 0 = don't")
    p.add_argument("--raw", action="store_true", help="print every report")
    p.add_argument("--log", help="save every report line to this CSV")
    p.add_argument("--replay", help="run detection on a saved CSV instead of the radar")
    p.add_argument("--no-config", action="store_true",
                   help="don't send the AN-029 golf settings")
    p.add_argument("--min-ball", type=float, default=DetectorConfig.min_ball_mph)
    a = p.parse_args(argv)

    cfg = DetectorConfig(min_ball_mph=a.min_ball)
    if a.replay:
        replay(a.replay, cfg)
        return

    reset_radar(a.reset_gpio)
    baud = a.baud
    if not baud:
        print(f"Looking for the radar on {a.port}:")
        baud = find_baud(a.port)
        if baud is None:
            print("No answer at any baud rate. Check: radar powered (LED on), TX/RX not swapped "
                  "(J3 6/7 to Pi 8/10), radar's USB cable unplugged (USB turns its UART off), "
                  "UART enabled on the Pi (raspi-config > Interface > Serial: login shell NO, "
                  "hardware YES).")
            return
        print(f"Radar answers at {baud} baud")
    radar = OPS243(a.port, baud)
    if not a.no_config:
        print("Sending AN-029 golf settings:")
        radar.configure()

    log_file = open(a.log, "w", newline="") if a.log else None
    writer = csv.writer(log_file) if log_file else None
    if writer:
        writer.writerow(["t", "line"])
    det = ShotDetector(print_shot, cfg)
    lock = threading.Lock()

    def on_report(rep: Report, line: str) -> None:
        with lock:
            if writer:
                writer.writerow([f"{rep.t:.4f}", line])
            if a.raw:
                print(f"{rep.t:.3f}  {rep.speeds}")
            det.feed(rep)

    def on_other(line: str) -> None:
        if a.raw:
            print(f"        (not a speed) {line}")

    radar.start(on_report, on_other)
    print("Listening. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(0.1)
            with lock:  # radar went quiet after a shot: finish it
                last = det.history[-1].t if det.history else None
                if det.pending is not None and last and time.monotonic() - last > 0.1:
                    det.flush()
    except KeyboardInterrupt:
        pass
    finally:
        radar.close()
        if log_file:
            log_file.close()


if __name__ == "__main__":
    main()
