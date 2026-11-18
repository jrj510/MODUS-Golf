r"""Retrain the camera's golf ball model on pictures from OUR camera.

The ball model is the neural network that puts the box on the ball in the
camera picture. It started as OpenFlight's model (a YOLO11n detector trained
on OpenFlight's camera set-up; OpenFlight, AGPL-3.0). This script uses that
model as the starting point and retrains it on our own pictures (our camera,
mat, grass, sun, shade, low light), so it is conformed to our system. Starting
from it rather than from nothing means far fewer pictures are needed. All the
logic around the model (hitting zone, confirming a ball, the small-ball
finder, motion trigger, shadow guard, exposure) is our own code.
(Starting instead from Ultralytics' generic yolo11n.pt also works:
--base yolo11n.pt, but it needs about twice the pictures.)

On the Pi, the original OpenFlight model can stay as the backup
(BACKUP_MODEL in start_kiosk.sh): it looks when ours finds nothing, and the
log says when it found a ball ours missed.

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
3. Get the starting model (once):
     scp modusgolf@modus.local:~/openflight/models/golf_ball_yolo11n_new.pt .
4. Train (needs: pip install ultralytics):
     python camera/train_ball_model.py --data C:\Users\<you>\Documents\modus_training
   Add --compare golf_ball_yolo11n_new.pt to score the original model on the
   same held-back pictures, to show what the retraining gained.
   A laptop CPU takes roughly 10-30 minutes; a GPU a few minutes.
5. Copy the new model to the Pi and use it:
     ssh modusgolf@modus.local mkdir -p MODUS-Golf/models
     scp runs_modus/ball/weights/best_256.onnx modusgolf@modus.local:~/MODUS-Golf/models/modus_ball_256.onnx
   then in start_kiosk.sh set  MODEL=~/MODUS-Golf/models/modus_ball_256.onnx
   (the original model becomes the backup automatically) and restart.
"""
import argparse
import os
import random
import shutil
import sys


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
    if os.path.exists(dst):
        shutil.rmtree(dst)
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
    p.add_argument("--base", default="golf_ball_yolo11n_new.pt",
                   help="model to start from: OpenFlight's golf ball model (copy it from the Pi, see the "
                        "top of this file), or yolo11n.pt (Ultralytics' generic one, needs more pictures)")
    p.add_argument("--compare", default=None,
                   help="another model (e.g. OpenFlight's golf_ball_yolo11n_new.pt) to score on the "
                        "same held-back pictures")
    p.add_argument("--min-balls", type=int, default=None,
                   help="refuse to train with fewer ball pictures than this (default 150, or 300 from "
                        "the generic yolo11n.pt; 0 = train anyway)")
    p.add_argument("--epochs", type=int, default=None, help="default 80 (150 from yolo11n.pt)")
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
    if not os.path.exists(args.base) and not generic:
        sys.exit(f"{args.base} not found. Copy it from the Pi (see the top of this file), "
                 "or use --base yolo11n.pt")
    min_balls = args.min_balls if args.min_balls is not None else (300 if generic else 150)
    epochs = args.epochs or (150 if generic else 80)

    yaml, balls = build_dataset(args.data or ["training"], "dataset_modus", args.val_share, args.seed)
    if balls < min_balls:
        sys.exit(f"Only {balls} ball pictures; about {min_balls}+ are needed for a reliable model. "
                 "Save more (Camera view -> Save frame), or use --min-balls 0 to train anyway.")
    model = YOLO(args.base)
    # The camera is black and white: no colour changes. Small shifts, scale and
    # brightness changes stand in for other ball spots and lighting. No
    # mosaic: it shrinks an already small ball.
    model.train(data=yaml, epochs=epochs, imgsz=args.imgsz, batch=args.batch,
                device=args.device, project="runs_modus", name="ball", exist_ok=True,
                single_cls=True, patience=20 if not generic else 30, hsv_h=0.0, hsv_s=0.0, hsv_v=0.4,
                degrees=0.0, translate=0.15, scale=0.3, fliplr=0.5, mosaic=0.0,
                seed=args.seed, plots=True)
    best = os.path.join("runs_modus", "ball", "weights", "best.pt")
    tuned = YOLO(best)
    metrics = tuned.val(data=yaml, imgsz=args.imgsz, device=args.device)
    print(f"Retrained model on the held-back pictures: precision {metrics.box.mp:.2f}, "
          f"recall {metrics.box.mr:.2f}, mAP50 {metrics.box.map50:.2f}")
    if args.compare:
        other = YOLO(args.compare, task="detect").val(data=yaml, imgsz=args.imgsz, device=args.device,
                                                     single_cls=True)
        print(f"{os.path.basename(args.compare)} on the same pictures: precision {other.box.mp:.2f}, "
              f"recall {other.box.mr:.2f}, mAP50 {other.box.map50:.2f}")
    onnx = tuned.export(format="onnx", imgsz=args.imgsz, simplify=True)
    out = os.path.join(os.path.dirname(best), f"best_{args.imgsz}.onnx")
    shutil.move(onnx, out)
    print(f"\nNew model: {out}\nCopy it to the Pi:\n  ssh modusgolf@modus.local mkdir -p MODUS-Golf/models\n"
          f"  scp {out} modusgolf@modus.local:~/MODUS-Golf/models/modus_ball_256.onnx\n"
          "then set MODEL=~/MODUS-Golf/models/modus_ball_256.onnx in start_kiosk.sh")


if __name__ == "__main__":
    main()
