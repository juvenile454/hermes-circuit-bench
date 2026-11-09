"""Optional: segmentation masks of the statue with two models (how figure/mask.png was made).

  python segment.py      writes WORK/mask-isnet.png and WORK/mask-birefnet.png (full crop size, soft L masks)

Needs rembg[cpu] >=2.0.60,<3 (onnxruntime) in a separate venv; the models (~1.1 GB) are downloaded by rembg into
$U2NET_HOME. Each model runs on four overlapping vertical tiles of the crop, blended with linear ramps, so the tall
figure is seen at about twice the resolution of one square pass. The committed mask is the mean of both
(prep.py --from-models); on 2026-11-07 the two masks agreed at IoU 0.993.
"""

import numpy as np
from common import CROP, work_dir
from PIL import Image
from prep import photo
from rembg import new_session, remove

MODELS = {"isnet": "isnet-general-use", "birefnet": "birefnet-general"}


def tiled_mask(src: Image.Image, model: str) -> np.ndarray:
    sess = new_session(model)
    w, h = src.size
    th = int(w * 1.15)
    acc = np.zeros((h, w), np.float32)
    wsum = np.zeros((h, w), np.float32)
    for y0 in np.linspace(0, h - th, 4).astype(int):
        m = np.asarray(remove(src.crop((0, y0, w, y0 + th)), session=sess, only_mask=True), np.float32) / 255
        ramp = np.ones(th, np.float32)
        r = th // 6
        if y0 > 0:
            ramp[:r] = np.linspace(0.02, 1, r)
        if y0 + th < h:
            ramp[-r:] = np.linspace(1, 0.02, r)
        acc[y0:y0 + th] += m * ramp[:, None]
        wsum[y0:y0 + th] += ramp[:, None]
    return acc / np.maximum(wsum, 1e-6)


def main() -> None:
    Image.MAX_IMAGE_PIXELS = None
    src = Image.open(photo()).convert("RGB").crop(CROP)
    for short, model in MODELS.items():
        m = tiled_mask(src, model)
        Image.fromarray((m * 255).astype(np.uint8)).save(work_dir() / f"mask-{short}.png")
        print(model, f"coverage {(m > 0.5).mean():.3f}")


if __name__ == "__main__":
    main()
