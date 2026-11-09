"""Step 3: render the (retouched) statue as the banner figure: scripts/banner/mercury@1x.png, @2x.png, mercury.json.

Look: grain duotone after the Hermes 3 / Hermes 4 model covers, in the banner palette.
- tone from statue pixels only (a plain resize mixes the paper into every edge pixel: bright rims, doubled
  contours), global stretch + CLAHE, unsharp mask at render scale
- 6-level Floyd-Steinberg grain (serpentine) in the cyan family; dark bronze keeps a sparse floor of grain
- yellow only as a hard-edged highlight plate (blurred tone > 0.82, no islands < ~2 CSS px^2)
- crisp contour from the soft mask; thin parts (finger, staff, snakes, wing tips) solid and posterized
- separate 1x and 2x assets (browser downscaling of the 2x grain muddies face and fingers); mirrored, he faces right

  python render.py [--src original]   default: the retouched crop from retouch.py
Needs numpy, opencv-python-headless, pillow.
"""

import json
import sys

import cv2
import numpy as np
from common import OUT, work_dir
from PIL import Image

CSS_H = 556  # figure height in the 1200x600 banner
PAL = np.array([[0, 0, 0], [0x10, 0x4C, 0x63], [0x16, 0x7C, 0x9B], [0x22, 0xB4, 0xD8], [0x5A, 0xCA, 0xE8],
                [0x8E, 0xE1, 0xF5]], np.float32)  # none, 2 dim steps, cyan, 2 light steps
YELLOW = np.array([0xF2, 0xE6, 0x34], np.float32)
CONTOUR = np.array([0x5C, 0xCC, 0xEA], np.float32)
HI = 0.82  # highlight plate threshold
HI_THIN = 0.72  # yellow on thin parts


def diffuse(v: np.ndarray, levels: int) -> np.ndarray:
    """Floyd-Steinberg error diffusion of v (0..1) onto `levels` evenly spaced values; returns level indices."""
    h, w = v.shape
    buf = v.astype(np.float64).tolist()
    out = np.zeros((h, w), np.uint8)
    n = levels - 1
    for y in range(h):
        row, nxt = buf[y], (buf[y + 1] if y + 1 < h else None)
        s = -1 if y % 2 else 1  # serpentine scan against directional worms
        orow = out[y]
        for x in (range(w - 1, -1, -1) if s < 0 else range(w)):
            old = row[x]
            q = min(n, max(0, int(old * n + 0.5)))
            orow[x] = q
            e = old - q / n
            if e == 0.0:
                continue
            x1 = x + s
            if 0 <= x1 < w:
                row[x1] += e * 0.4375
            if nxt is not None:
                if 0 <= x - s < w:
                    nxt[x - s] += e * 0.1875
                nxt[x] += e * 0.3125
                if 0 <= x1 < w:
                    nxt[x1] += e * 0.0625
    return out


def tone_map(gray: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    inside = alpha > 0.5
    lo, hi = np.percentile(gray[inside], 1.0), np.percentile(gray[inside], 99.6)
    g = np.clip((gray.astype(np.float32) - lo) / (hi - lo), 0, 1)
    loc = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(12, 28)).apply((g * 255).astype(np.uint8)).astype(np.float32) / 255
    return np.clip(0.5 * g + 0.5 * loc, 0, 1)


def render(tone0: np.ndarray, alpha0: np.ndarray, scale: int) -> np.ndarray:
    h0, w0 = alpha0.shape
    h = round(CSS_H * scale)
    w = round(w0 * h / h0)
    a = np.clip(cv2.resize(alpha0, (w, h), interpolation=cv2.INTER_AREA), 0, 1)
    m = a > 0.5
    wgt = (alpha0 > 0.92).astype(np.float32)
    den = cv2.resize(wgt, (w, h), interpolation=cv2.INTER_AREA)
    t = cv2.resize(tone0 * wgt, (w, h), interpolation=cv2.INTER_AREA) / np.maximum(den, 1e-4)
    near = cv2.dilate(m.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    hole = ((den < 0.15) & near).astype(np.uint8)
    t8 = (np.clip(np.where(den >= 0.15, t, 0), 0, 1) * 255).astype(np.uint8)
    t = cv2.inpaint(t8, hole, 3, cv2.INPAINT_TELEA).astype(np.float32) / 255
    t = np.clip(t + 0.7 * (t - cv2.GaussianBlur(t, (0, 0), 1.2 * scale)), 0, 1)
    fade = np.clip((1.0 - np.arange(h)[:, None] / h) / 0.05, 0, 1) ** 1.2  # the wind-head dissolves at the bottom

    q = diffuse(np.where(m, (0.16 + 0.84 * t ** 0.9) * fade, 0.0), len(PAL))
    col = PAL[q]
    cov = (q > 0).astype(np.float32) * np.clip((a - 0.3) * 3, 0, 1)  # no grain specks in the soft edge

    ts = cv2.GaussianBlur(t, (0, 0), 0.8 * scale)
    hp = ((ts > HI) & m & (fade > 0.6)).astype(np.uint8)
    kk = np.ones((2, 2), np.uint8) if scale > 1 else np.ones((1, 1), np.uint8)
    hp = cv2.morphologyEx(cv2.morphologyEx(hp, cv2.MORPH_OPEN, kk), cv2.MORPH_CLOSE, kk)
    n, lab, st, _ = cv2.connectedComponentsWithStats(hp, 8)
    hp[np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] < 2.5 * scale * scale])] = 0
    col = np.where(hp[..., None] > 0, YELLOW, col)
    cov = np.maximum(cov, hp.astype(np.float32))

    er = max(1, round(1.0 * scale))
    ring = np.clip((a - cv2.erode(a, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * er + 1, 2 * er + 1)))) * 1.7, 0, 1)
    col = np.where((ring > 0.35)[..., None] & (hp[..., None] == 0), CONTOUR, col)
    cov = np.maximum(cov, ring) * np.clip(a * 1.6, 0, 1)
    cov = np.where(ring > 0.35, cov * fade, cov)

    d = max(3, round(5 * scale) | 1)
    mm = m.astype(np.uint8)
    thick = cv2.morphologyEx(mm, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d)))
    thin = (mm > 0) & (cv2.dilate(thick, np.ones((3, 3), np.uint8)) == 0)
    tt = cv2.GaussianBlur(t, (0, 0), 0.6 * scale)
    tcol = np.where((tt > HI_THIN)[..., None], YELLOW, np.where((tt > 0.38)[..., None], PAL[5], PAL[3]))
    a_d = cv2.dilate(a, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))) if scale > 1 else np.clip(a * 1.25, 0, 1)
    thin = cv2.dilate(thin.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & (a_d > 0.25) & ~(thick > 0)
    col = np.where(thin[..., None], tcol, col)
    cov = np.where(thin, np.maximum(cov, np.clip(a_d * 1.8, 0, 1) * fade), cov)

    out = np.zeros((h, w, 4), np.uint8)
    out[..., :3] = np.clip(col, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(cov * 255, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(out[:, ::-1])  # mirrored


def main() -> None:
    d = work_dir()
    tag = "" if "--src" in sys.argv and sys.argv[sys.argv.index("--src") + 1] == "original" else "-retouched"
    rgb = np.asarray(Image.open(d / f"src{tag}.png").convert("RGB"))
    alpha0 = np.asarray(Image.open(d / f"alpha{tag}.png"), np.float32) / 255
    meta = json.loads((d / f"meta{tag}.json").read_text())
    tone0 = tone_map(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), alpha0)
    for scale in (1, 2):
        Image.fromarray(render(tone0, alpha0, scale), "RGBA").save(OUT / f"mercury@{scale}x.png", optimize=True)
    h0, w0 = alpha0.shape
    k = CSS_H / h0
    fx, fy = meta["fingertip"]
    info = {"css_w": round(w0 * k), "css_h": CSS_H, "fingertip": [round((w0 - 1 - fx) * k, 1), round(fy * k, 1)],
            "source": meta["source"], "retouched": bool(tag), "mirrored": True}
    (OUT / "mercury.json").write_text(json.dumps(info, indent=1) + "\n")
    print(info)


if __name__ == "__main__":
    main()
