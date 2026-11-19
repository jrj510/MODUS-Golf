"""
Fit MODUS-Golf's own radar calibration (camera/radar_calibration.py) from
shots, and show what is in use. Run from ~/MODUS-Golf (the kiosk can stay
running, except for ti-capture):

  python3 camera/calibrate_radars.py show
      what each radar's calibration is now, and our speed correction next to
      OpenFlight's for typical shots

  python3 camera/calibrate_radars.py ops REFERENCE.csv [--session logs/sessions/session_X.csv]
      speed radar trim: hit 15-30 shots with another launch monitor (TrackMan,
      GCQuad, Mevo+, R10 ... anything that exports a CSV) watching the same
      shots, export its CSV, copy it here. Shots are matched in order (shots
      only one of them caught are skipped). Default session: the newest.

  python3 camera/calibrate_radars.py ti [--session FILE ...] [--reference REFERENCE.csv]
      TI angle trim: against the camera's launch angles (inside, fits rated
      good; default: every session CSV) or a reference launch monitor's.

  python3 camera/calibrate_radars.py ti-capture
      TI array: capture a corner reflector held still at tape-measured spots
      (stop the kiosk first; it holds the TI's port). Then:
  python3 camera/calibrate_radars.py ti-array calibration/ti_YYYYMMDD_HHMM/positions.csv

  python3 camera/calibrate_radars.py reset ops|ti|ti-array

Geometry (distances, heights, tilt) is read from start_kiosk.sh, as the
kiosk gets it. Every fit shows before/after and asks before saving; the
kiosk picks up a saved calibration the next time it starts.
"""

import argparse
import glob
import math
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import radar_calibration as rc              # noqa: E402
from ballflight import club_defaults       # noqa: E402

ROOT = os.path.dirname(HERE)


def kiosk_settings(path=None):
    """NAME=value settings from start_kiosk.sh (comments stripped)."""
    path = path or os.path.join(ROOT, "start_kiosk.sh")
    out = {}
    try:
        for line in open(path):
            m = re.match(r"^([A-Z_][A-Z0-9_]*)=([^#\s]*)", line.strip())
            if m:
                out[m.group(1)] = m.group(2).strip("'\"")
    except OSError:
        pass
    return out


def _f(settings, name, default):
    try:
        return float(settings.get(name, default))
    except (TypeError, ValueError):
        return default


class Geometry:
    """The kiosk's radar arguments, from start_kiosk.sh."""

    def __init__(self, settings, out, inside=False):
        self.iwr_tee_m = _f(settings, "TEE_M", 1.575)
        self.iwr_net_m = _f(settings, "NET_M", 4.6)
        self.iwr_tilt_deg = _f(settings, "TILT_DEG", 10.0)
        self.iwr_radar_height_m = _f(settings, "RADAR_H", 0.06985)
        self.iwr_ball_height_m = _f(settings, "BALL_H", 0.021)
        self.iwr_azimuth_offset_deg = _f(settings, "AZIMUTH_DEG", 0.0)
        self.ops_window_ms = _f(settings, "OPS_WINDOW_MS", 90.0)
        self.speed_net = "on" if inside else "off"
        self.out = out


def _openflight(path):
    src = os.path.join(os.path.expanduser(path), "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def _ask(question, yes):
    if yes:
        return True
    try:
        return input(question + " [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _sessions(given, newest_only):
    if given:
        return given
    files = sorted(glob.glob(os.path.join("logs", "sessions", "session_*.csv")))
    return files[-1:] if newest_only else files


def _num(row, *names):
    for n in names:
        v = rc._num(row.get(n))
        if v is not None:
            return v
    return None


# --------------------------------------------------------------------------
def cmd_show(a):
    geo = Geometry(kiosk_settings(), a.out, inside=False)
    ops = rc.OPSCalibration.from_args(geo)
    ti = rc.TICalibration.from_args(geo)
    print("Speed radar: " + ops.text())
    print("TI radar:    " + ti.text(tilt_deg=geo.iwr_tilt_deg))
    try:
        _openflight(a.openflight)
        from openflight.speed_correction import correct_ball_speed
    except Exception:
        correct_ball_speed = None
    print()
    print("Ball speed for typical shots (radar reading -> corrected), outside / inside (net):")
    print("  club     reading  launch   MODUS out   MODUS in" + ("   OpenFlight" if correct_ball_speed else ""))
    geo_in = Geometry(kiosk_settings(), a.out, inside=True)
    ops_in = rc.OPSCalibration.from_args(geo_in)
    for club, raw in (("driver", 150), ("driver", 120), ("3w", 140), ("7i", 110), ("7i", 90),
                      ("pw", 85), ("sw", 70)):
        la = club_defaults(club)[0]
        line = f"  {club:7s} {raw:6.0f}  {la:5.1f}   {ops.correct(raw, la, 0, club):9.1f}  {ops_in.correct(raw, la, 0, club):9.1f}"
        if correct_ball_speed:
            dist = geo.iwr_tee_m * 3.28084
            above = (geo.iwr_ball_height_m - geo.iwr_radar_height_m) * 3.28084
            line += f"   {correct_ball_speed(raw, la, dist, above):10.1f}"
        print(line)


def cmd_ops(a):
    settings = kiosk_settings()
    geo = Geometry(settings, a.out, inside=a.inside)
    cal = rc.OPSCalibration.from_args(geo)
    theirs = rc.read_reference(a.reference)
    rows = rc.read_sessions(_sessions(a.session, newest_only=True))
    ours = []
    for r in rows:
        raw = _num(r, "ball_speed_raw_mph")
        if raw is None:
            continue
        model = _num(r, "ball_speed_model_mph")
        if model is None:          # an older session: work it out now
            model, _ = cal.model(raw, _num(r, "launch_deg"), _num(r, "launch_dir_deg"), r.get("club"))
        ours.append({"shot": r.get("shot"), "file": r["_file"], "raw": raw, "model": model,
                     "shown": _num(r, "ball_speed_mph")})
    print(f"{len(ours)} of our shots with a raw radar speed, {len(theirs)} reference shots ({a.reference})")
    pairs = rc.match_shots(ours, theirs, key=lambda s: s["model"] if "model" in s else s["speed_mph"])
    try:
        fit = rc.fit_trim([(ours[i]["model"], theirs[j]["speed_mph"]) for i, j in pairs], unit="mph")
    except ValueError as e:
        print(f"Can't fit: {e}. Hit more shots with both running (15-30 is good).")
        return 1
    kept = set(fit["kept"])
    print("\n  shot  radar  MODUS model  reference   diff")
    for i, j in pairs:
        o, t = ours[i], theirs[j]
        flag = "" if (o["model"], t["speed_mph"]) in kept else "   left out (too far off the rest)"
        print(f"  {str(o['shot']):>4}  {o['raw']:5.1f}  {o['model']:11.1f}  {t['speed_mph']:9.1f}  "
              f"{t['speed_mph'] - o['model']:+5.1f}{flag}")
    print(f"\n{len(fit['kept'])} shots used, {len(fit['dropped'])} left out; speeds spread {fit['spread']} mph")
    print(f"  model alone:  off by {fit['before']['mean']:+.2f} mph on average "
          f"(typical miss {fit['before']['mean_abs']:.2f}, scatter {fit['before']['sd']:.2f})")
    print(f"  with trim:    off by {fit['after']['mean']:+.2f} mph on average "
          f"(typical miss {fit['after']['mean_abs']:.2f}, scatter {fit['after']['sd']:.2f})")
    print(f"  trim: speed = {fit['scale']:.4f} x model {fit['offset']:+.2f} mph"
          + ("" if fit["scaled"] else "  (offset only: the speeds don't spread enough for a scale)"))
    big = abs(fit["offset"]) > 6.0 or abs(fit["scale"] - 1.0) > 0.05
    if big and not a.force:
        print("\nThat is a big change. Check TEE_M, RADAR_H and BALL_H in start_kiosk.sh and that the "
              "shots really line up; run again with --force to save it anyway.")
        return 1
    if a.dry_run:
        return 0
    if _ask(f"Save this to {cal.path}?", a.yes):
        cal.save(fit["scale"], fit["offset"], {
            "pairs": len(fit["kept"]), "dropped": len(fit["dropped"]),
            "reference": os.path.basename(a.reference), "date": rc._now(),
            "before": fit["before"], "after": fit["after"], "spread_mph": fit["spread"]})
        print("Saved. The kiosk uses it from its next start.")
    return 0


def cmd_ti(a):
    settings = kiosk_settings()
    geo = Geometry(settings, a.out)
    cal = rc.TICalibration.from_args(geo)
    rows = rc.read_sessions(_sessions(a.session, newest_only=False))
    angle, direction, source = [], [], "camera"
    if a.reference:
        source = os.path.basename(a.reference)
        theirs = rc.read_reference(a.reference)
        ours = [r for r in rows if _num(r, "ball_speed_mph") is not None]
        for i, j in rc.match_shots(ours, theirs, key=lambda s: _num(s, "ball_speed_mph") if "_file" in s
                                   else s["speed_mph"]):
            ti = _num(ours[i], "ti_launch_raw_deg", "ti_launch_deg")
            if ti is not None and theirs[j]["launch"] is not None:
                angle.append((ti, theirs[j]["launch"]))
            td = _num(ours[i], "ti_dir_raw_deg")
            if td is not None and theirs[j]["direction"] is not None:
                direction.append((td, theirs[j]["direction"]))
    else:
        for r in rows:
            if (r.get("cam_quality") or "") != "good":
                continue
            ti = _num(r, "ti_launch_raw_deg", "ti_launch_deg")
            cam = _num(r, "cam_launch_deg")
            if ti is not None and cam is not None:
                angle.append((ti, cam))
            td, cd = _num(r, "ti_dir_raw_deg"), _num(r, "cam_dir_deg")
            if td is not None and cd is not None:
                direction.append((td, cd))
    print(f"{len(angle)} shots with both the TI's launch angle and the {source}'s"
          + (" (camera fits rated good)" if source == "camera" else ""))
    try:
        fit = rc.fit_trim(angle, unit="deg", spread_for_scale=8.0)
    except ValueError as e:
        print(f"Can't fit: {e}.")
        return 1
    dir_off, dir_n = 0.0, 0
    try:
        dfit = rc.fit_trim(direction, unit="deg", spread_for_scale=1e9)
        dir_off, dir_n = dfit["offset"], len(dfit["kept"])
    except ValueError:
        pass
    print(f"  TI alone:   off by {fit['before']['mean']:+.2f} deg on average (typical miss "
          f"{fit['before']['mean_abs']:.2f}, scatter {fit['before']['sd']:.2f}); {len(fit['dropped'])} left out")
    print(f"  with trim:  off by {fit['after']['mean']:+.2f} deg (typical miss {fit['after']['mean_abs']:.2f})")
    print(f"  trim: launch = {fit['scale']:.3f} x TI {fit['offset']:+.2f} deg"
          + ("" if fit["scaled"] else "  (offset only)"))
    if not fit["scaled"]:
        print(f"  (the same as TILT_DEG being off by {fit['offset']:+.1f} deg: you can also fix it there "
              f"and leave the trim at zero)")
    print(f"  direction: {dir_off:+.2f} deg from {dir_n} shots" if dir_n else
          "  direction: not enough shots with both directions; left at 0")
    if abs(fit["offset"]) > 4.0 and not a.force:
        print("\nThat is a big offset: check TILT_DEG and RADAR_H in start_kiosk.sh first; "
              "run again with --force to save it anyway.")
        return 1
    if a.dry_run:
        return 0
    if _ask(f"Save this to {cal.path}?", a.yes):
        cal.save_trim(fit["scale"], fit["offset"], dir_off, {
            "pairs": len(fit["kept"]), "dir_pairs": dir_n, "reference": source, "date": rc._now(),
            "before": fit["before"], "after": fit["after"]})
        print("Saved. The kiosk uses it from its next start.")
    return 0


def cmd_ti_capture(a):
    settings = kiosk_settings()
    _openflight(a.openflight)
    from openflight.iwr6843.monitor import IWR6843CaptureMonitor
    folder = a.folder or os.path.join("calibration", time.strftime("ti_%Y%m%d_%H%M"))
    os.makedirs(folder, exist_ok=True)
    config = a.iwr_config if os.path.isabs(a.iwr_config) else \
        os.path.join(os.path.expanduser(a.openflight), a.iwr_config)
    gpio = int(_f(settings, "GATE_GPIO", 20))
    print("TI array calibration: captures go to " + folder)
    print("You need: a corner reflector (or a small metal plate held square to the radar) on a stand,\n"
          "a tape measure, and the TI aimed and tilted exactly as it is for shots. Measure each spot as\n"
          "  ground_m = along the ground, from the point under the radar's antenna to the point under\n"
          "             the reflector's centre;  height_m = the reflector's centre above the ground.\n"
          "Use 4-6 spots 1-3.5 m away, at different heights (0.2-0.9 m), inside the radar's view.\n"
          "Nothing else in front of the radar may move while capturing.")
    mon = IWR6843CaptureMonitor(config_path=config, output_dir=folder, port=a.iwr_port, gpio_pin=gpio,
                                save_dumps=True)
    mon.start(armed=True)
    rows = ["file,ground_m,height_m"]

    def grab(label):
        t = time.time()
        if not mon.notify_trigger(t):
            print("  the radar is busy; try again")
            return None
        cap = mon.capture_for_shot(t, timeout_s=25.0)
        if cap is None or not cap.valid or cap.path is None:
            print(f"  capture failed: {getattr(cap, 'error', None) or 'no capture'}")
            return None
        name = f"{label}.l3dump"
        os.replace(str(cap.path), os.path.join(folder, name))
        print(f"  saved {name}")
        return name

    try:
        input("\n1) Empty scene: take the reflector away (room as it is), then press Enter ")
        name = grab("empty")
        if name:
            rows.append(f"{name},empty,")
        n = 0
        while True:
            text = input("\nPlace the reflector; type 'ground_m height_m' (e.g. 1.50 0.47), "
                         "or just Enter when done: ").strip()
            if not text:
                break
            try:
                g, h = (float(x) for x in text.replace(",", " ").split())
            except ValueError:
                print("  two numbers, in metres")
                continue
            n += 1
            for rep in range(2):
                name = grab(f"spot{n:02d}_{rep + 1}")
                if name:
                    rows.append(f"{name},{g},{h}")
    finally:
        mon.stop()
        path = os.path.join(folder, "positions.csv")
        open(path, "w").write("\n".join(rows) + "\n")
        print(f"\nWrote {path}. Next: python3 camera/calibrate_radars.py ti-array {path}")
    return 0


def cmd_ti_array(a):
    settings = kiosk_settings()
    geo = Geometry(settings, a.out)
    _openflight(a.openflight)
    tx_order = "normal"
    try:
        from openflight.iwr6843.monitor import tx_order_from_config
        config = a.iwr_config if os.path.isabs(a.iwr_config) else \
            os.path.join(os.path.expanduser(a.openflight), a.iwr_config)
        tx_order = tx_order_from_config(config)
    except Exception as e:
        print(f"(TX order from the radar config not available: {e}; using normal)")
    res = rc.array_from_captures(a.positions, geo.iwr_radar_height_m, geo.iwr_tilt_deg,
                                 tx_order=tx_order, floor_echo=not a.direct_only)
    print(f"Array solved from {len(res['positions'])} spots (radar {geo.iwr_radar_height_m:g} m up, "
          f"tilt {geo.iwr_tilt_deg:g} deg, {tx_order} TX order, "
          + ("empty scene removed" if res["background"] else "NO empty-scene capture") + ")")
    print("  ground  height  angle   echo  fit err   snr   range vs tape")
    for p in res["positions"]:
        rng = (f"{p['range_m']:.3f} vs {p['slant_m']:.3f}" if "range_m" in p else "")
        print(f"  {p['ground_m']:6.2f}  {p['height_m']:6.2f}  {p['angle_deg']:5.1f}  {p['echo']:5.2f}  "
              f"{p['fit_error']:7.1%}  {p.get('snr', 0):5.0f}   {rng}")
    print("  element phase (deg): " + " ".join(f"{math.degrees(v):+6.1f}" for v in res["elem_phase_rad"]))
    print("  element gain:        " + " ".join(f"{v:6.3f}" for v in res["elem_gain"]))
    print(f"  range bias {res['range_bias_m'] * 100:+.1f} cm; fit residual {res['residual']:.1%}")
    warn = []
    if len(res["positions"]) < 4:
        warn.append("fewer than 4 spots")
    if res["residual"] > 0.05:
        warn.append("the fit leaves more than 5% unexplained (something moved, or a spot was mis-measured)")
    bad = [p for p in res["positions"] if p["fit_error"] > 0.10]
    if bad:
        warn.append(f"{len(bad)} spot(s) fit badly: " + ", ".join(f"{p['ground_m']}/{p['height_m']}" for p in bad))
    if not res["background"]:
        warn.append("no empty-scene capture, so the room's still clutter is in the snapshots")
    for w in warn:
        print("  WARNING: " + w)
    if a.dry_run:
        return 0
    cal = rc.TICalibration.from_args(geo)
    if _ask(f"Save this array calibration to {cal.path}?", a.yes):
        cal.save_array(res)
        print("Saved. The kiosk uses it (instead of OpenFlight's reference board) from its next start.")
    return 0


def cmd_reset(a):
    geo = Geometry(kiosk_settings(), a.out)
    if a.what == "ops":
        path = os.path.join(a.out, rc.OPS_FILE)
        if os.path.exists(path):
            os.remove(path)
        print("Speed radar trim removed (MODUS model alone).")
    else:
        cal = rc.TICalibration.from_args(geo)
        cal.clear("trim" if a.what == "ti" else "array")
        print("TI angle trim removed." if a.what == "ti" else
              "TI array calibration removed (OpenFlight's reference board again).")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="MODUS-Golf radar calibration",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--out", default="shots", help="where the kiosk keeps its calibration files")
    p.add_argument("--openflight", default="~/openflight")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    o = sub.add_parser("ops")
    o.add_argument("reference", help="the other launch monitor's CSV export")
    o.add_argument("--session", action="append", help="our session CSV(s); default the newest")
    o.add_argument("--inside", action="store_true", help="(older sessions only) shots were inside, into the net")
    t = sub.add_parser("ti")
    t.add_argument("--session", action="append", help="our session CSV(s); default all of them")
    t.add_argument("--reference", help="fit against this launch monitor's CSV instead of the camera")
    for s in (o, t):
        s.add_argument("--yes", action="store_true", help="save without asking")
        s.add_argument("--force", action="store_true", help="save even a big change")
        s.add_argument("--dry-run", action="store_true", help="show the fit, don't save")
    c = sub.add_parser("ti-capture")
    c.add_argument("--folder")
    ar = sub.add_parser("ti-array")
    ar.add_argument("positions", help="positions.csv written by ti-capture")
    ar.add_argument("--direct-only", action="store_true", help="don't model the floor echo")
    ar.add_argument("--yes", action="store_true")
    ar.add_argument("--dry-run", action="store_true")
    for s in (c, ar):
        s.add_argument("--iwr-port", default="/dev/ttyUSB0")
        s.add_argument("--iwr-config", default="config/iwr6843_l3dump_wide_24f3ms_53bin_iq16.cfg")
    r = sub.add_parser("reset")
    r.add_argument("what", choices=("ops", "ti", "ti-array"))
    a = p.parse_args(argv)
    try:
        return {"show": cmd_show, "ops": cmd_ops, "ti": cmd_ti, "ti-capture": cmd_ti_capture,
                "ti-array": cmd_ti_array, "reset": cmd_reset}[a.cmd](a)
    except (OSError, ValueError) as e:
        print(f"Stopped: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
