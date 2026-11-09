"""Step 2: retouch, nothing laid on top: anatomical detail removed for a public repository.
WORK/src.png + alpha.png -> WORK/src-retouched.png + alpha-retouched.png.

1. Silhouette: the bulge of the front edge (hanging part, y 1975-2028) is cut along a smooth quadratic Bezier from
   the abdomen line into the thigh front (anti-aliased, ~700 px).
2. Inside the silhouette: membrane (Laplace) fill from the surrounding bronze, the smoothest surface that meets the
   border, plus fine grain at the strength measured around the region. Inpainting and copied texture left blotches.

Coordinates are in the statue crop of figure/mask.json. Retouched region from several independent estimates and the
silhouette profile: x 625-702, y 1890-2035. Needs numpy, scipy, opencv-python-headless, pillow.
"""

import json

import cv2
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl
from common import work_dir
from PIL import Image

P0, P1, P2 = np.array([636.0, 1958.0]), np.array([641.0, 2002.0]), np.array([658.0, 2034.0])  # new front contour
ELLIPSE = (663.5, 1962.5, 50.0, 84.0)  # centre x, y and half axes of the retouched region
RETOUCH_BOX = [625, 1890, 702, 2035]  # bounding box of the retouched region (x0, y0, x1, y1)


def membrane_fill(work: np.ndarray, region: np.ndarray) -> np.ndarray:
    """Solve the discrete Laplace equation inside `region` with the values of `work` on its border."""
    h, w = region.shape
    ys, xs = np.nonzero(region)
    idx = -np.ones((h, w), np.int64)
    idx[ys, xs] = np.arange(len(ys))
    rows, cols, vals = [], [], []
    rhs = np.zeros(len(ys))
    src = work.astype(np.float64)
    for k, (y, x) in enumerate(zip(ys, xs, strict=True)):
        rows.append(k)
        cols.append(k)
        vals.append(4.0)
        for y2, x2 in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            j = idx[y2, x2]
            if j >= 0:
                rows.append(k)
                cols.append(j)
                vals.append(-1.0)
            else:
                rhs[k] += src[y2, x2]
    a = sp.csr_matrix((vals, (rows, cols)), shape=(len(ys), len(ys)))
    out = work.astype(np.float32).copy()
    out[ys, xs] = spl.spsolve(a, rhs)
    return out


def main() -> None:
    d = work_dir()
    rgb = np.asarray(Image.open(d / "src.png").convert("RGB")).copy()
    alpha = np.asarray(Image.open(d / "alpha.png"), np.float32) / 255
    meta = json.loads((d / "meta.json").read_text())
    h, w = alpha.shape
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    # 1) silhouette
    s = np.linspace(0, 1, 400)[:, None]
    curve = (1 - s) ** 2 * P0 + 2 * (1 - s) * s * P1 + s ** 2 * P2
    xcut = np.full(h, -1.0, np.float32)
    for y in range(int(P0[1]), int(P2[1]) + 1):
        xcut[y] = np.interp(y, curve[:, 1], curve[:, 0])
    band = (xx >= 590) & (xx <= 700) & (xcut[:, None] > 0)
    keep = np.clip(xx - xcut[:, None] + 0.5, 0, 1)
    alpha_new = np.where(band, alpha * keep, alpha)

    # 2) tone inside the new silhouette
    cx, cy, ax, ay = ELLIPSE
    region = ((((xx - cx) / ax) ** 2 + ((yy - cy) / ay) ** 2) <= 1) & (alpha_new > 0.3)
    region = cv2.dilate(region.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))) > 0
    region &= alpha_new > 0.05
    # the border values must be bronze: paper next to the silhouette is first replaced by nearby bronze
    outside = (alpha_new < 0.5) & (cv2.dilate(region.astype(np.uint8), np.ones((41, 41), np.uint8)) > 0)
    work = cv2.inpaint(gray.copy(), outside.astype(np.uint8), 9, cv2.INPAINT_TELEA)
    fill = membrane_fill(work, region)
    lum = gray.astype(np.float32)
    hp = lum - cv2.GaussianBlur(lum, (0, 0), 2)
    ring = (cv2.dilate(region.astype(np.uint8), np.ones((31, 31), np.uint8)) > 0) & ~region & (alpha_new > 0.5)
    grain = float(hp[ring].std())
    noise = cv2.GaussianBlur(np.random.default_rng(9).normal(0, 1, (h, w)).astype(np.float32), (0, 0), 1.0)
    noise *= grain / max(float(noise[region].std()), 1e-6)
    fill = fill + noise
    feather = np.clip(cv2.GaussianBlur(region.astype(np.float32), (0, 0), 5) * 1.6, 0, 1)
    lum_new = lum * (1 - feather) + fill * feather
    for c in range(3):
        rgb[..., c] = np.clip(rgb[..., c].astype(np.float32) + (lum_new - lum), 0, 255).astype(np.uint8)

    Image.fromarray(rgb).save(d / "src-retouched.png")
    Image.fromarray(np.clip(alpha_new * 255, 0, 255).astype(np.uint8)).save(d / "alpha-retouched.png")
    meta["retouch"] = {"box": RETOUCH_BOX, "contour": [P0.tolist(), P1.tolist(), P2.tolist()],
                       "silhouette_px_removed": int(((alpha > 0.5) & (alpha_new <= 0.5)).sum()),
                       "filled_px": int(region.sum()), "grain_std": round(grain, 2)}
    (d / "meta-retouched.json").write_text(json.dumps(meta, indent=1) + "\n")
    print("retouch", meta["retouch"])


if __name__ == "__main__":
    main()
