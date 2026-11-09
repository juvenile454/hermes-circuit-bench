"""Step 1: source photo -> statue crop and soft mask in WORK (src.png, alpha.png, meta.json).

  python prep.py                 crop the photo, take the committed mask (figure/mask.png, figure/mask.json)
  python prep.py --from-models   build the mask from WORK/mask-isnet.png + WORK/mask-birefnet.png (segment.py)
                                 and rewrite figure/mask.png and figure/mask.json

The photo is downloaded once into WORK and checked against its SHA-256. Needs numpy, opencv-python-headless, pillow.
"""

import hashlib
import json
import sys
import urllib.request

import cv2
import numpy as np
from common import CROP, HERE, PHOTO_CREDIT, PHOTO_SHA256, PHOTO_URL, work_dir
from PIL import Image

MARGIN = 24  # px around the statue in the saved crop


def photo():
    p = work_dir() / "photo.jpg"
    if not p.exists():
        req = urllib.request.Request(PHOTO_URL, headers={"User-Agent": "circuit-bench-banner/1 (build script)"})
        with urllib.request.urlopen(req, timeout=180) as r:
            p.write_bytes(r.read())
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    if digest != PHOTO_SHA256:
        sys.exit(f"photo checksum mismatch: {digest} (expected {PHOTO_SHA256}); delete {p} and retry")
    return p


def mask_from_models(shape):
    w = work_dir()
    a1 = np.asarray(Image.open(w / "mask-isnet.png"), np.float32) / 255
    a2 = np.asarray(Image.open(w / "mask-birefnet.png"), np.float32) / 255
    if a1.shape != shape or a2.shape != shape:
        sys.exit("model masks do not match the crop; run segment.py first")
    alpha = (a1 + a2) / 2
    hard = (alpha > 0.5).astype(np.uint8)
    _, lab, stats, _ = cv2.connectedComponentsWithStats(hard, 8)
    big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))  # the statue; drops specks and stains
    alpha *= cv2.dilate((lab == big).astype(np.uint8), np.ones((5, 5), np.uint8))
    ys, xs = np.nonzero(alpha > 0.02)
    x0, y0 = max(0, int(xs.min()) - MARGIN), max(0, int(ys.min()) - MARGIN)
    x1, y1 = min(shape[1], int(xs.max()) + MARGIN), min(shape[0], int(ys.max()) + MARGIN)
    box = [x0, y0, x1, y1]
    a = alpha[y0:y1, x0:x1]
    hm = a > 0.5
    ty = int(np.nonzero(hm.any(1))[0][0])
    tx = round(float(np.nonzero(hm[ty])[0].mean()), 1)
    iou = float(((a1 > 0.5) & (a2 > 0.5)).sum() / max(1, ((a1 > 0.5) | (a2 > 0.5)).sum()))
    meta = {"bbox_in_crop": box, "size": [x1 - x0, y1 - y0], "fingertip": [tx, ty], "source": PHOTO_CREDIT,
            "masks": "rembg isnet-general-use + birefnet-general, tiled, mean", "model_iou": round(iou, 4)}
    Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8)).save(HERE / "mask.png")
    (HERE / "mask.json").write_text(json.dumps(meta, indent=1) + "\n")
    return meta


def main() -> None:
    Image.MAX_IMAGE_PIXELS = None
    rgb = np.asarray(Image.open(photo()).convert("RGB").crop(CROP))
    meta = mask_from_models(rgb.shape[:2]) if "--from-models" in sys.argv else json.loads((HERE / "mask.json").read_text())
    x0, y0, x1, y1 = meta["bbox_in_crop"]
    alpha = Image.open(HERE / "mask.png")
    if alpha.size != (x1 - x0, y1 - y0):
        sys.exit("figure/mask.png does not match figure/mask.json")
    w = work_dir()
    Image.fromarray(rgb[y0:y1, x0:x1]).save(w / "src.png")
    alpha.save(w / "alpha.png")
    (w / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    print("crop", meta["size"], "fingertip", meta["fingertip"], "->", w)


if __name__ == "__main__":
    main()
