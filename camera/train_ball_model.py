"""Retrain the golf ball model on pictures from YOUR camera.

The model the kiosk uses was trained on OpenFlight's camera set-up. Fine-tuning
it on a few hundred pictures from this camera, mat and lighting makes it far
surer of your ball and much less likely to box a look-alike.

1. Collect pictures on the Pi: Camera view -> "Save frame".
     - With the green box on the ball: saves the ball (do this with the ball in
       different spots, different lighting, club behind it, indoors and out).
     - With no ball in the zone: saves "no ball here" pictures (tees, marks,
       shadows, your feet in the zone are all useful).
   Aim for 150+ ball and 50+ empty. They go to shots/training/ on the Pi.
2. Copy them to this computer (in the MODUS-Golf folder):
     scp -r modusgolf@modus.local:~/MODUS-Golf/shots/training ./training
   Look through training/review/: if a picture's green box is NOT on the ball,
   delete the files with the same name start from images/ and labels/.
3. Get the starting model (once):
     scp modusgolf@modus.local:~/openflight/models/golf_ball_yolo11n_new.pt .
4. Train (needs: pip install ultralytics):
     python camera/train_ball_model.py --data training --base golf_ball_yolo11n_new.pt
   A laptop CPU takes roughly 10-30 minutes; a GPU a few minutes.
5. Copy the new model to the Pi and use it:
     scp runs_modus/ball/weights/best_256.onnx modusgolf@modus.local:~/openflight/models/modus_ball_256.onnx
   then on the Pi add  '--model','~/openflight/models/modus_ball_256.onnx',  to the
   kiosk line in start_kiosk.sh (or set MODEL= there) and restart.
"""
import argparse
import os
import random
import shutil
import sys


def build_dataset(src, dst, val_share, seed):
    """Split images/labels into train/val folders and write the dataset file."""
    images = sorted(f for f in os.listdir(os.path.join(src, "images")) if f.endswith(".png"))
    pairs = [f for f in images if os.path.exists(os.path.join(src, "labels", f[:-4] + ".txt"))]
    if not pairs:
        sys.exit(f"No pictures with labels in {src}/images and {src}/labels")
    # Both tiles of one save share a name start: keep them in the same split.
    groups = {}
    for f in pairs:
        groups.setdefault(f.rsplit("_", 1)[0], []).append(f)
    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    n_val = max(1, int(len(keys) * val_share))
    split = {k: ("val" if i < n_val else "train") for i, k in enumerate(keys)}
    if os.path.exists(dst):
        shutil.rmtree(dst)
    counts = {"train": [0, 0], "val": [0, 0]}
    for k, files in groups.items():
        part = split[k]
        for f in files:
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
    if counts["train"][0] < 50:
        print("Warning: under 50 ball pictures to train on; save more for a reliable model")
    return yaml


def main():
    p = argparse.ArgumentParser(description="Fine-tune the golf ball model on this camera's pictures")
    p.add_argument("--data", default="training", help="the training folder copied from the Pi")
    p.add_argument("--base", default="golf_ball_yolo11n_new.pt",
                   help="model to start from (OpenFlight's .pt; yolo11n.pt also works, but needs more pictures)")
    p.add_argument("--epochs", type=int, default=80)
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
    if not os.path.exists(args.base) and args.base != "yolo11n.pt":
        sys.exit(f"{args.base} not found. Copy it from the Pi (see the top of this file) "
                 "or use --base yolo11n.pt")

    yaml = build_dataset(args.data, "dataset_modus", args.val_share, args.seed)
    model = YOLO(args.base)
    # The camera is black and white: no colour changes. Small shifts, scale and
    # brightness changes stand in for other ball spots and lighting. No
    # mosaic: it shrinks an already small ball.
    model.train(data=yaml, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                device=args.device, project="runs_modus", name="ball", exist_ok=True,
                single_cls=True, patience=20, hsv_h=0.0, hsv_s=0.0, hsv_v=0.4,
                degrees=0.0, translate=0.15, scale=0.3, fliplr=0.5, mosaic=0.0,
                seed=args.seed, plots=True)
    best = os.path.join("runs_modus", "ball", "weights", "best.pt")
    tuned = YOLO(best)
    metrics = tuned.val(data=yaml, imgsz=args.imgsz, device=args.device)
    print(f"Validation: precision {metrics.box.mp:.2f}, recall {metrics.box.mr:.2f}, "
          f"mAP50 {metrics.box.map50:.2f}")
    onnx = tuned.export(format="onnx", imgsz=args.imgsz, simplify=True)
    out = os.path.join(os.path.dirname(best), f"best_{args.imgsz}.onnx")
    shutil.move(onnx, out)
    print(f"\nNew model: {out}\nCopy it to the Pi:\n  scp {out} "
          "modusgolf@modus.local:~/openflight/models/modus_ball_256.onnx")


if __name__ == "__main__":
    main()
