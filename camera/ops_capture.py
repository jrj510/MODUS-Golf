"""MODUS Golf: OPS243-A in rolling-buffer mode, with our own signal processing.

The radar records raw I/Q samples nonstop into a 4096-sample buffer. On a
trigger it freezes the buffer and sends it over; we turn it into speeds
ourselves:

  1. split the 4096 samples into 32 blocks of 128 (4.3 ms each at 30 ksps)
  2. per block: remove the DC offset, Hann window, complex FFT of I + jQ
     zero-padded to 4096 points
  3. find the strongest peaks above the block's noise floor
  4. Doppler -> speed:  v = f_d * c / (2 * f0),  f0 = 24.125 GHz
     (0.006213 m/s per Hz; at 30 ksps one FFT bin is 0.102 mph, the same
     resolution the radar itself reports)

Each block becomes a Report (time, top speeds), so the same ball/club
detector as before (ops243.ShotDetector) reads the swing.

Triggers (any of them freezes the buffer):
  * the radar's own speed trigger (ST): anything moving away faster than
    --speed-trigger-mph. Club and ball both qualify, so it fires as the club
    comes through, with no camera or sound needed
  * a 3.3 V rising edge on J3 pin 3 (the camera's pulse on GPIO21)
  * S! sent over the serial line (software trigger)

Pre-trigger split (S#n): n of the 32 blocks come from before the trigger.
Default here 4 (17 ms before, 119 ms after): the speed trigger fires as the
club comes through, before impact (2026-11-20, wedge at 40 mph: ~15-20 ms
before; 2026-11-21, 3-iron: early enough that with 94 ms after the trigger the
recording ended before impact), so nearly all of it goes after the trigger.

Serial: the radar starts at 19200 baud (its saved setting); a dump is ~41 KB,
which takes ~21 s at 19200, so we switch it to 230400 (I5) for ~1.8 s.

Commands are from OmniPreSense AN-027 (Rolling Buffer) and AN-010 (API).

Run on the Pi:
    python3 camera/ops_capture.py                 # arm, print each shot
    python3 camera/ops_capture.py --blocks        # also print every block's speeds
    python3 camera/ops_capture.py --save caps/    # keep every capture as JSON
    python3 camera/ops_capture.py --replay caps/x.json
    (press Enter to trigger by hand)
"""

from __future__ import annotations

import argparse
import json
import os
import select
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from ops243 import DetectorConfig, Report, ShotDetector, Shot, find_baud, reset_radar

C = 299_792_458.0
F0 = 24.125e9                      # OPS243 carrier, Hz
MPS_PER_HZ = C / (2 * F0)          # 0.006213 m/s of speed per Hz of Doppler
MPH_PER_MPS = 2.236936
N_SAMPLES = 4096
BLOCK = 128
N_BLOCKS = N_SAMPLES // BLOCK
FAST_BAUD = 230400
FAST_BAUD_CMD = b"I5"              # tested on our OPS243-A rev D6, fw 1.3.2


# --------------------------------------------------------------------------
# Signal processing (ours)
# --------------------------------------------------------------------------
@dataclass
class Capture:
    sample_time: float             # radar clock, s: first sample
    trigger_time: float            # radar clock, s: the trigger
    i: np.ndarray
    q: np.ndarray
    received: float                # Pi clock (monotonic) when the dump started arriving
    rate: float                    # samples per second

    @property
    def duration(self) -> float:
        return len(self.i) / self.rate

    def pi_time(self, radar_t: float) -> float:
        """Radar clock -> Pi clock. The dump starts right after the last
        sample, so that moment is ~self.received."""
        return self.received - (self.sample_time + self.duration - radar_t)

    def as_json(self) -> dict:
        return {"sample_time": self.sample_time, "trigger_time": self.trigger_time,
                "received": self.received, "rate": self.rate,
                "I": self.i.astype(int).tolist(), "Q": self.q.astype(int).tolist()}

    @staticmethod
    def from_json(d: dict) -> "Capture":
        return Capture(float(d["sample_time"]), float(d["trigger_time"]),
                       np.asarray(d["I"], float), np.asarray(d["Q"], float),
                       float(d.get("received", 0.0)), float(d.get("rate", 30000)))


@dataclass
class ProcessConfig:
    nfft: int = 4096
    min_mph: float = 10.0          # ignore slower (body, clutter, DC)
    max_peaks: int = 4             # speeds kept per block (ball, club, and room for the
                                   # golfer's body etc. without crowding the ball out)
    snr: float = 8.0               # peak must be this many times the block's noise floor
    rel_min: float = 0.03          # ...and at least this share of the block's strongest peak
                                   # (keeps a strong target's window sidelobes out)
    separation_mph: float = 8.0    # two peaks closer than this are one target
    outbound_sign: int = 0         # +1/-1: keep only that Doppler sign; 0 = work it out per
                                   # capture (the side with the most energy: club and ball
                                   # move away; the other side is clutter and mirror images)


def block_spectra(cap: Capture, nfft: int = 4096) -> np.ndarray:
    """|FFT| of each 128-sample block: shape (n_blocks, nfft), fftshifted."""
    n = len(cap.i) // BLOCK
    i = cap.i[: n * BLOCK].reshape(n, BLOCK)
    q = cap.q[: n * BLOCK].reshape(n, BLOCK)
    z = (i - i.mean(axis=1, keepdims=True)) + 1j * (q - q.mean(axis=1, keepdims=True))
    z = z * np.hanning(BLOCK)
    return np.abs(np.fft.fftshift(np.fft.fft(z, nfft, axis=1), axes=1))


def speed_axis(rate: float, nfft: int = 4096) -> np.ndarray:
    """Signed speed (mph) of each fftshifted bin."""
    f = np.fft.fftshift(np.fft.fftfreq(nfft, d=1.0 / rate))
    return f * MPS_PER_HZ * MPH_PER_MPS


def outbound_sign(spec: np.ndarray, v: np.ndarray, ok: np.ndarray) -> int:
    """Which Doppler sign is "moving away": the side with more energy above
    each block's noise floor (club and ball both move away from the radar)."""
    floor = np.median(spec[:, ok], axis=1, keepdims=True)
    excess = np.clip(spec - 8 * floor, 0, None)
    pos = excess[:, ok & (v > 0)].sum()
    neg = excess[:, ok & (v < 0)].sum()
    return 1 if pos >= neg else -1


def capture_reports(cap: Capture, cfg: Optional[ProcessConfig] = None) -> list[Report]:
    """One Report per block: its time on the Pi clock and its strongest speeds."""
    cfg = cfg or ProcessConfig()
    spec = block_spectra(cap, cfg.nfft)
    v = speed_axis(cap.rate, cfg.nfft)
    ok = np.abs(v) >= cfg.min_mph
    sign = cfg.outbound_sign or outbound_sign(spec, v, ok)
    floors = np.median(spec[:, ok], axis=1)
    ok &= np.sign(v) == sign
    sep_bins = max(1, int(cfg.separation_mph / abs(v[1] - v[0])))
    reports = []
    for b in range(spec.shape[0]):
        s = spec[b]
        floor = floors[b]
        # Real peaks only: a local maximum (higher than both neighbours), so
        # slow motion just under min_mph can't leak in as a reading at the
        # cut-off, and strong enough above this block's noise floor.
        peak = np.zeros_like(ok)
        peak[1:-1] = (s[1:-1] > s[:-2]) & (s[1:-1] >= s[2:])
        top = s[ok].max() if ok.any() else 0.0
        cand = np.flatnonzero(peak & ok & (s >= cfg.snr * floor) & (s >= cfg.rel_min * top))
        cand = cand[np.argsort(s[cand])[::-1]]
        kept: list[int] = []
        for k in cand:
            if len(kept) >= cfg.max_peaks:
                break
            # Not the same target again, and not its mirror image (a weaker
            # copy at the opposite Doppler sign from the radar's I/Q imbalance).
            if any(abs(k - j) <= sep_bins or abs(abs(v[k]) - abs(v[j])) * (1.0 / abs(v[1] - v[0])) <= sep_bins
                   for j in kept):
                continue
            kept.append(int(k))
        speeds = [abs(float(v[k])) for k in kept]
        t_radar = cap.sample_time + (b + 0.5) * BLOCK / cap.rate
        if speeds:
            reports.append(Report(t=cap.pi_time(t_radar), speeds=sorted(speeds, reverse=True)))
    return reports


def find_shot(cap: Capture, pcfg: Optional[ProcessConfig] = None,
              dcfg: Optional[DetectorConfig] = None) -> tuple[Optional[Shot], list[Report]]:
    """Ball, club and smash from one capture (None if no ball in it)."""
    dcfg = dcfg or DetectorConfig()
    dcfg.cooldown_s = 0.0
    reports = capture_reports(cap, pcfg)
    shots: list[Shot] = []
    det = ShotDetector(shots.append, dcfg)
    for r in reports:
        det.feed(r)
    det.flush()
    return (shots[0] if shots else None), reports


def parse_dump(lines: list[str], received: float, rate: float) -> Optional[Capture]:
    """sample_time / trigger_time / I / Q JSON lines -> Capture."""
    got: dict = {}
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            got.update(json.loads(line))
        except ValueError:
            continue
    if not all(k in got for k in ("sample_time", "trigger_time", "I", "Q")):
        return None
    return Capture(float(got["sample_time"]), float(got["trigger_time"]),
                   np.asarray(got["I"], float), np.asarray(got["Q"], float), received, rate)


# --------------------------------------------------------------------------
# The radar
# --------------------------------------------------------------------------
@dataclass
class CaptureConfig:
    rate_ksps: int = 30
    split: int = 4                        # blocks from before the trigger (S#n): 17 ms before,
                                          # 119 ms after. A fast club passes the speed trigger
                                          # well before impact (2026-11-21, 3-iron: recordings
                                          # with split 10 ended before the ball was struck)
    speed_trigger_mph: Optional[float] = 40.0   # radar's own trigger, moving away; None = off
    trigger_magnitude: int = 20           # SMnnn


class RollingBufferRadar:
    """Arms the rolling buffer, reads each dump in a background thread and
    calls on_capture(Capture). Re-arms itself after every dump."""

    def __init__(self, port: str = "/dev/ttyAMA0", cfg: Optional[CaptureConfig] = None,
                 reset_gpio: Optional[int] = 23, verbose: bool = True):
        import serial
        self.cfg = cfg or CaptureConfig()
        self.port = port
        self.verbose = verbose
        self.serial_mod = serial
        reset_radar(reset_gpio)
        baud = find_baud(port, (19200, FAST_BAUD, 115200, 57600, 9600))
        if baud is None:
            raise RuntimeError(f"no answer from the OPS243 on {port}")
        if baud != FAST_BAUD:
            with serial.Serial(port, baud, timeout=0.3) as s:
                s.write(FAST_BAUD_CMD)
                time.sleep(0.3)
        self.ser = serial.Serial(port, FAST_BAUD, timeout=0.05)
        self.ser.reset_input_buffer()
        if not self._ask(b"I?"):
            raise RuntimeError(f"OPS243 didn't answer at {FAST_BAUD} baud after {FAST_BAUD_CMD!r}")
        self.lock = threading.Lock()
        self.busy = False                   # a dump is coming in: radar isn't recording
        self._new_trigger: Optional[float] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _ask(self, cmd: bytes, wait: float = 0.3) -> list[str]:
        self.ser.write(cmd)
        time.sleep(wait)
        out = self.ser.read(self.ser.in_waiting or 1).decode("ascii", "replace")
        return [l.strip() for l in out.splitlines() if l.strip()]

    def setup(self) -> None:
        c = self.cfg
        # Commands with a number end in Enter (\r): the radar waits for it,
        # as S=30 and X=32 showed. An extra \r after the others is harmless.
        cmds = [b"PI", f"S={c.rate_ksps}\r".encode(), f"S#{c.split}\r".encode()]
        if c.speed_trigger_mph:
            mps = int(round(c.speed_trigger_mph / MPH_PER_MPS))
            cmds += [f"ST-{mps}\r".encode(), f"SM{c.trigger_magnitude}\r".encode()]
        cmds += [b"GC"]
        for cmd in cmds:
            replies = self._ask(cmd)
            if self.verbose:
                print(f"  {cmd.decode().strip():<7} -> {' | '.join(replies) or '(no reply)'}")

    def arm(self) -> None:
        with self.lock:
            mph, self._new_trigger = self._new_trigger, None
        if mph is not None:
            self._send_speed_trigger(mph)
        self.ser.write(b"GC")

    def _send_speed_trigger(self, mph: float) -> None:
        if mph and mph > 0:
            mps = max(1, int(round(mph / MPH_PER_MPS)))
            self.ser.write(f"ST-{mps}\r".encode())
        else:
            self.ser.write(b"ST-0\r")
        time.sleep(0.05)
        self.cfg.speed_trigger_mph = mph or None

    def set_speed_trigger(self, mph: Optional[float]) -> None:
        """Change the radar's own trigger speed (moving away, mph) while running.
        Applied at once if the radar is recording, else after the recording
        that is coming over."""
        with self.lock:
            if self.busy:
                self._new_trigger = mph or 0.0
                return
        self._send_speed_trigger(mph or 0.0)
        self.ser.write(b"GC")

    def trigger(self) -> None:
        """Software trigger (S!)."""
        with self.lock:
            if not self.busy:
                self.ser.write(b"S!")

    def start(self, on_capture: Callable[[Capture], None],
              on_notice: Optional[Callable[[float], None]] = None) -> None:
        """on_capture(Capture) for every recording; on_notice(Pi time) the
        moment the radar says its speed trigger fired, ~2 s before that
        recording has come over (so the camera can still keep its frames)."""
        rate = self.cfg.rate_ksps * 1000.0

        def loop() -> None:
            lines: list[str] = []
            first = None
            while not self._stop.is_set():
                raw = self.ser.readline()
                if not raw:
                    if lines and first and time.monotonic() - first > 5.0:
                        lines, first = [], None        # half a dump: drop it
                        with self.lock:
                            self.busy = False
                        self.arm()
                    continue
                line = raw.decode("ascii", "replace").strip()
                if '"sample_time"' in line:
                    lines, first = [line], time.monotonic()
                    with self.lock:
                        self.busy = True
                    continue
                if first is None:
                    if "trigger_velocity_detected" in line and on_notice is not None:
                        try:
                            on_notice(time.monotonic())
                        except Exception as e:
                            print(f"Trigger notice handler error: {type(e).__name__}: {e}")
                    elif line and self.verbose:
                        print(f"  radar: {line[:120]}")
                    continue
                lines.append(line)
                if line.startswith('{"Q"'):
                    cap = parse_dump(lines, first, rate)
                    lines, first = [], None
                    with self.lock:
                        self.busy = False
                    self.arm()                          # recording again
                    if cap is not None:
                        try:
                            on_capture(cap)
                        except Exception as e:
                            print(f"Capture handler error: {type(e).__name__}: {e}")
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        try:
            self.ser.write(b"PI")
        except Exception:
            pass
        self.ser.close()


# --------------------------------------------------------------------------
# Command line test tool
# --------------------------------------------------------------------------
def describe(cap: Capture, shot: Optional[Shot], reports: list[Report], blocks: bool) -> None:
    trig_ms = (cap.trigger_time - cap.sample_time) * 1000
    print(f"Capture: {cap.duration * 1000:.0f} ms of samples, trigger {trig_ms:.0f} ms in")
    if blocks:
        t0 = cap.pi_time(cap.trigger_time)
        for r in reports:
            print(f"   {1000 * (r.t - t0):+6.0f} ms  " + "  ".join(f"{s:6.1f}" for s in r.speeds))
    if shot is None:
        print("  no ball in this capture")
    else:
        club = "--" if shot.club_mph is None else f"{shot.club_mph:.1f}"
        smash = "--" if shot.smash is None else f"{shot.smash:.2f}"
        print(f"SHOT  ball {shot.ball_mph:.1f} mph   club {club} mph   smash {smash}")


def main(argv: Optional[list[str]] = None) -> None:
    p = argparse.ArgumentParser(description="MODUS OPS243-A rolling-buffer test")
    p.add_argument("--port", default="/dev/ttyAMA0")
    p.add_argument("--reset-gpio", type=int, default=23)
    p.add_argument("--split", type=int, default=4, help="blocks (of 32) kept from before the trigger")
    p.add_argument("--speed-trigger-mph", type=float, default=40.0,
                   help="radar triggers itself on anything moving away faster; 0 = off")
    p.add_argument("--min-ball", type=float, default=30.0)
    p.add_argument("--blocks", action="store_true", help="print every block's speeds")
    p.add_argument("--save", help="folder to save each capture to (JSON)")
    p.add_argument("--replay", help="process a saved capture instead of the radar")
    a = p.parse_args(argv)
    dcfg = DetectorConfig(min_ball_mph=a.min_ball)

    if a.replay:
        with open(a.replay) as f:
            cap = Capture.from_json(json.load(f))
        shot, reports = find_shot(cap, dcfg=dcfg)
        describe(cap, shot, reports, True)
        return

    cfg = CaptureConfig(split=a.split, speed_trigger_mph=a.speed_trigger_mph or None)
    radar = RollingBufferRadar(a.port, cfg, reset_gpio=a.reset_gpio)
    print("Setting up the rolling buffer:")
    radar.setup()
    if a.save:
        os.makedirs(a.save, exist_ok=True)

    def on_capture(cap: Capture) -> None:
        took = time.monotonic() - cap.received
        shot, reports = find_shot(cap, dcfg=DetectorConfig(min_ball_mph=a.min_ball))
        print(f"\n[{time.strftime('%H:%M:%S')}] dump received ({took:.1f} s to read)")
        describe(cap, shot, reports, a.blocks)
        if a.save:
            path = os.path.join(a.save, time.strftime("cap_%Y%m%d_%H%M%S.json"))
            with open(path, "w") as f:
                json.dump(cap.as_json(), f)
            print(f"  saved {path}")

    radar.start(on_capture)
    print("Armed. Swing (speed trigger" + (" on" if cfg.speed_trigger_mph else " off")
          + ") or press Enter to trigger. Ctrl+C to stop.")
    try:
        while True:
            r, _, _ = select.select([sys.stdin], [], [], 0.2)
            if r:
                sys.stdin.readline()
                radar.trigger()
    except KeyboardInterrupt:
        pass
    finally:
        radar.close()


if __name__ == "__main__":
    main()
