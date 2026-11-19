r"""Retrain the camera's golf ball model on pictures from OUR camera.

The ball model is the neural network that puts the box on the ball in the
camera picture. It is the only one the kiosk uses. It is trained on our own
pictures (our camera, mat, grass, sun, shade, low light), starting from
Ultralytics' generic YOLO11n detector (yolo11n.pt, which knows shapes in
general but nothing about golf balls; Ultralytics downloads it the first
time). All the logic around the model (hitting zone, confirming a ball, the
small-ball finder, motion trigger, shadow guard, cover guard) is our own code.

(Our first model, the one in use until this is run again, was retrained
from OpenFlight's golf ball model, which needed fewer pictures. Starting from
the generic yolo11n.pt leaves nothing of OpenFlight's in the model, but
needs about twice the pictures: 300+ ball pictures. Use --compare with the
model in use to check the new one is at least as good before switching.)

1. Collect pictures on the Pi: Camera view -> "Save frame".
     - With the green box on the ball: saves the ball (in different spots,
       sun, shade and low light, club behind it, on grass and on the mat).
       If the box isn't on the ball, tap the ball first so it is.
     - With no ball in the zone: saves "no ball here" pictures (tees, marks,
       shadows, your feet in the zone are all useful).
   Aim for 150+ ball and 50+ empty (each Save frame gives 2 ball pictures).
   They go to shots/training/ on the Pi.
2. Copy them to this computer (outside the MODUS-Golf folder, so the
   pictures don't end up in git), e.g. in PowerShell:
     scp -r modusgolf@modus.local:~/MODUS-Golf/shots/training C:\Users\<you>\Documents\modus_training
   Look through review/: if a picture's green box is NOT on the ball, delete
   the files with the same name start from images/ and labels/.
3. (The starting point, yolo11n.pt, downloads by itself the first time.)
4. Train (needs: pip install ultralytics):
     python camera/train_ball_model.py --data C:\Users\<you>\Documents\modus_training
   Add --compare <the model in use, its best.pt> to score it on the same
   held-back pictures, to show whether the new one is better.
   A laptop CPU takes roughly 10-30 minutes; a GPU a few minutes.
   The copies of the pictures and the results go in a work folder next to
   the training folder (e.g. Documents\modus_training_work, or --work): not
   in this git folder, and not in OneDrive, which locks the folder while it
   syncs and asks about every few hundred files deleted.
   Already trained (say the run stopped after training)? Add
     --trained <the best.pt it made>
   to skip the training and just score, compare and export that model.
5. Copy the new model to the Pi and use it:
     ssh modusgolf@modus.local mkdir -p MODUS-Golf/models
     scp <work folder>/runs/ball/weights/best_256.onnx modusgolf@modus.local:~/MODUS-Golf/models/modus_ball_256.onnx
   (the script prints these with the model's real path at the end); start_kiosk.sh
   uses MODEL=~/MODUS-Golf/models/modus_ball_256.onnx. Restart the kiosk.
"""
import argparse
import os
import random
import shutil
import sys
import time


def _clear(folder):
    """Delete the last run's copy of the pictures. A folder that OneDrive (or
    an open Explorer window) is holding can refuse for a moment: try again."""
    for attempt in range(5):
        if not os.path.exists(folder):
            return
        try:
            shutil.rmtree(folder)
            return
        except OSError as e:
            err = e
            time.sleep(1.0)
    sys.exit(f"Couldn't clear {folder} ({err}). Something is holding it (OneDrive syncing, or a "
             "window open on it): close that, or delete the folder yourself, and run again.")


def build_dataset(srcs, dst, val_share, seed):
    """Split images/labels (from one or more training folders) into train/val
    folders and write the dataset file."""
    pairs = []
    for src in srcs:
        images = sorted(f for f in os.listdir(os.path.join(src, "images")) if f.endswith(".png"))
        pairs += [(src, f) for f in images if os.path.exists(os.path.join(src, "labels", f[:-4] + ".txt"))]
    if not pairs:
        sys.exit(f"No pictures with labels in {', '.join(srcs)} (images/ and labels/)")
    # Both tiles of one save share a name start: keep them in the same split.
    groups = {}
    for src, f in pairs:
        groups.setdefault((src, f.rsplit("_", 1)[0]), []).append((src, f))
    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    n_val = max(1, int(len(keys) * val_share))
    split = {k: ("val" if i < n_val else "train") for i, k in enumerate(keys)}
    _clear(dst)
    counts = {"train": [0, 0], "val": [0, 0]}
    for k, files in groups.items():
        part = split[k]
        for src, f in files:
            for sub, ext in (("images", ".png"), ("labels", ".txt")):
                os.makedirs(os.path.join(dst, sub, part), exist_ok=True)
                shutil.copy(os.path.join(src, sub, f[:-4] + ext), os.path.join(dst, sub, part, f[:-4] + ext))
            counts[part][0 if "_ball_" in f else 1] += 1
    yaml = os.path.join(dst, "data.yaml")
    with open(yaml, "w") as fh:
        fh.write(f"path: {os.path.abspath(dst)}\ntrain: images/train\nval: images/val\n"
                 "names:\n  0: golf_ball\n")
    for part, (b, e) in counts.items():
        print(f"{part}: {b} ball, {e} empty")
    balls = counts["train"][0] + counts["val"][0]
    return yaml, balls


def main():
    p = argparse.ArgumentParser(description="Retrain the golf ball model on this camera's pictures")
    p.add_argument("--data", action="append", default=None,
                   help="a training folder copied from the Pi (give it more than once to combine; "
                        "default: training)")
    p.add_argument("--base", default="yolo11n.pt",
                   help="model to start from: yolo11n.pt (Ultralytics' generic detector, downloaded "
                        "the first time), or one of our earlier models to keep training it")
    p.add_argument("--compare", default=None,
                   help="another model (e.g. the one in use) to score on the same held-back pictures")
    p.add_argument("--min-balls", type=int, default=None,
                   help="refuse to train with fewer ball pictures than this (default 150, or 300 from "
                        "the generic yolo11n.pt; 0 = train anyway)")
    p.add_argument("--epochs", type=int, default=None, help="default 80 (150 from yolo11n.pt)")
    p.add_argument("--trained", default=None,
                   help="skip training: score, compare and export this already-trained model "
                        "(the best.pt of an earlier run)")
    p.add_argument("--work", default=None,
                   help="folder for the copies of the pictures and the training results (default: "
                        "<training folder>_work next to the first --data folder)")
    p.add_argument("--imgsz", type=int, default=256, help="must match the kiosk's --imgsz (256)")
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--device", default=None, help="e.g. cpu, 0 (first GPU), mps (Apple)")
    p.add_argument("--val-share", type=float, default=0.15)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    try:
        from ultralytics import YOLO
    except ImportError:
        sys.exit("Install the training library first:  pip install ultralytics")
    generic = os.path.basename(args.base) == "yolo11n.pt"
    if args.trained and not os.path.exists(args.trained):
        sys.exit(f"{args.trained} not found")
    if not args.trained and not os.path.exists(args.base) and not generic:
        sys.exit(f"{args.base} not found (leave --base out to start from the generic yolo11n.pt)")
    min_balls = args.min_balls if args.min_balls is not None else (300 if generic else 150)
    epochs = args.epochs or (150 if generic else 80)

    # (The same --seed gives the same held-back pictures every run, so a
    # --trained model is scored on pictures it never trained on.)
    data = args.data or ["training"]
    work = os.path.abspath(args.work or os.path.abspath(data[0]).rstrip("\\/") + "_work")
    runs = os.path.join(work, "runs")
    print(f"Work folder (picture copies and results): {work}")
    yaml, balls = build_dataset(data, os.path.join(work, "dataset"), args.val_share, args.seed)
    if args.trained:
        best = args.trained
    else:
        if balls < min_balls:
            sys.exit(f"Only {balls} ball pictures; about {min_balls}+ are needed for a reliable model. "
                     "Save more (Camera view -> Save frame), or use --min-balls 0 to train anyway.")
        model = YOLO(args.base)
        # The camera is black and white: no colour changes. Small shifts, scale and
        # brightness changes stand in for other ball spots and lighting. No
        # mosaic: it shrinks an already small ball. An absolute project folder:
        # newer Ultralytics versions put a relative one under runs/detect/.
        model.train(data=yaml, epochs=epochs, imgsz=args.imgsz, batch=args.batch,
                    device=args.device, project=runs, name="ball", exist_ok=True,
                    single_cls=True, patience=20 if not generic else 30, hsv_h=0.0, hsv_s=0.0, hsv_v=0.4,
                    degrees=0.0, translate=0.15, scale=0.3, fliplr=0.5, mosaic=0.0,
                    seed=args.seed, plots=True)
        # Where the training really saved it (asked from Ultralytics itself).
        save_dir = getattr(getattr(model, "trainer", None), "save_dir", None) \
            or os.path.join(runs, "ball")
        best = os.path.join(str(save_dir), "weights", "best.pt")
        if not os.path.exists(best):
            sys.exit(f"Training finished but {best} is missing; look for best.pt under {runs} or "
                     "runs/ and run again with --trained <that file>")
    tuned = YOLO(best)
    metrics = tuned.val(data=yaml, imgsz=args.imgsz, device=args.device, project=runs, name="val",
                        exist_ok=True)
    print(f"Retrained model on the held-back pictures: precision {metrics.box.mp:.2f}, "
          f"recall {metrics.box.mr:.2f}, mAP50 {metrics.box.map50:.2f}")
    if args.compare:
        other = YOLO(args.compare, task="detect").val(data=yaml, imgsz=args.imgsz, device=args.device,
                                                     single_cls=True, project=runs, name="val_compare",
                                                     exist_ok=True)
        print(f"{os.path.basename(args.compare)} on the same pictures: precision {other.box.mp:.2f}, "
              f"recall {other.box.mr:.2f}, mAP50 {other.box.map50:.2f}")
    onnx = tuned.export(format="onnx", imgsz=args.imgsz, simplify=True)
    out = os.path.join(os.path.dirname(best), f"best_{args.imgsz}.onnx")
    shutil.move(onnx, out)
    short = os.path.relpath(out) if os.path.splitdrive(out)[0] == os.path.splitdrive(os.getcwd())[0] else out
    out = short if not short.startswith("..") else out      # (a short path for the copy command, if any)
    print(f"\nNew model: {out}\nCopy it to the Pi:\n  ssh modusgolf@modus.local mkdir -p MODUS-Golf/models\n"
          f"  scp {out} modusgolf@modus.local:~/MODUS-Golf/models/modus_ball_256.onnx\n"
          "then set MODEL=~/MODUS-Golf/models/modus_ball_256.onnx in start_kiosk.sh")


if __name__ == "__main__":
    main()
