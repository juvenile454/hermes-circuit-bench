# Catalog banner

Generator of the Circuit Bench banner (plugin catalog `image`, README header, 1200×600). Tooling for the catalog
image only, not part of the plugin (`circuit_bench/`).

The banner shows *Mercury* after Giambologna sending one signal: fingertip → trace into the I of CIRCUIT → the
lettering → out of the H of BENCH → pin IO14 (LASER) of an ESP32-S3-DevKitC-1. The board is the app's own board
model, drawn by `desktop-src/lib/art-board.js` with the inputs of the PLAN station (N16R8 pin map with Wi-Fi, demo
project `project.laser-trigger.json`), never by hand.

## Contents

| File | Purpose |
|---|---|
| `banner.mjs` | builds the banner page: board SVG from `desktop-src/lib/art-board.js`, lettering, signal path, self-check |
| `mercury@1x.png`, `mercury@2x.png`, `mercury.json` | the figure for 1x and 2x (RGBA, mirrored); width, height, fingertip in CSS px |
| `figure/mask.png`, `figure/mask.json` | soft mask of the statue in the crop; box, fingertip, paper windows |
| `figure/prep.py` | download the photo (SHA-256 checked), crop, apply the mask |
| `figure/retouch.py` | retouch: anatomical detail removed for a public repository (smooth contour, fill from the surrounding bronze) |
| `figure/render.py` | grain duotone, highlight plate, contour, thin parts solid; writes `mercury@*` |
| `figure/segment.py` | optional: how the mask was made (two segmentation models) |

Test: `node --test tests-js/test_banner.mjs` (board from `art-board.js`, no network URLs, figure files, label
position, deterministic output).

## Building the banner

```
node scripts/banner/banner.mjs [out.html]    # default: $TMPDIR/cb-banner.html
```

This writes a self-contained HTML page of 1200×600 CSS px; the only assets are file URLs into this checkout, nothing
is loaded from the network. Render it with a headless browser at 1x or 2x to get the PNG; the catalog image must stay
at 1200×600 and at most 600 KB. The optional query `?font=<folder URL>` loads `JetBrainsMono-Regular.woff2` and
`JetBrainsMono-Bold.woff2` from that folder; without it the page uses the local monospace fallback.

The page checks itself and reports on `<html>`: `data-ready`, `data-error` (overlap, anything outside the 16 px frame,
the label not under the trace end, more than 12 px from the board or less than 24 px below the "pins · …" line),
`data-font` (`loaded` or `fallback`) and `data-layout` (the measured boxes).

Composition:
- Board: the same as in the app and its screenshots, cropped to the pcb without the app's label columns; the label
  names the assignment.
- Materials exactly from `desktop-src/lib/tokens.js` (`MATERIAL`: green pcb, silver module printed "ESP32-S3").
- Pin states in the banner palette, the way the app's Phosphor and Follow themes vary them: free dim cyan, assigned
  app cyan, caution app amber, blocked and power muted.
- A bench under the board (fine grid, two HUD corners), so it sits on something instead of floating.

## Source and licence

- Photo: Rijksmuseum RP-F-00-9348, "Bronzen beeld van Mercurius door Giovanni da Bologna of Giambologna", photograph
  1850–1900, **CC0 1.0**, via Wikimedia Commons
  (`File:Bronzen beeld van Mercurius door Giovanni da Bologna of Giambologna, RP-F-00-9348.jpg`, 5326×7106,
  SHA-256 `68bf6e3b669ccd823ba29d72b6e7a9612228c6119bbe83c692ea2710e96d8a92`). Licence read from the Commons API
  (extmetadata `LicenseShortName` = CC0) on 2026-11-07. No attribution required; the banner credits it anyway
  ("Mercury after Giambologna · photo Rijksmuseum, CC0").
- The photo is not in the repository; `figure/prep.py` downloads it and checks the checksum.
- Retouch: anatomical detail removed for a public repository; nothing is laid on top of the figure.
- No images, logos or typefaces of Nous Research; only the general style direction.

## Rebuilding the figure

A separate virtual environment outside the repository (no project dependency): `numpy>=1.26,<3`,
`opencv-python-headless>=4.8,<5`, `scipy>=1.11,<2`, `pillow>=10,<13`; for `segment.py` also `rembg[cpu]>=2.0.60,<3`
(downloads ~1.1 GB of models). Intermediate files go to `$CB_BANNER_WORK` (default `$TMPDIR/cb-banner-figure`).

```
python scripts/banner/figure/prep.py        # photo + figure/mask.png -> WORK/src.png, alpha.png
python scripts/banner/figure/retouch.py     # -> WORK/src-retouched.png, alpha-retouched.png
python scripts/banner/figure/render.py      # -> mercury@1x.png, mercury@2x.png, mercury.json
```

This path reproduces the committed `mercury@1x.png` and `mercury@2x.png` pixel for pixel.

Mask from the models again: `python scripts/banner/figure/segment.py`, then
`python scripts/banner/figure/prep.py --from-models`. Both models (`isnet-general-use`, `birefnet-general`, each on
four overlapping tiles) agree with IoU 0.993; the mask is their mean.

## Why it is built this way

- Threshold cut-outs fail on bronze: lit belly, hip and finger edges are as bright as the paper.
- Average tones come from statue pixels only; otherwise the paper tints every edge row (yellow seams, double
  contours).
- Line screens and contour hatching turn the finger into a ladder and the fist into noise; a six-level grain duotone
  keeps face, hand and snakes.
- A separate 1x file instead of a downscaled 2x; the banner's scanlines run under the figure, not across it.
- The board is the app's board model, so banner and screenshots show the same board; only the pin states get the
  banner colours.
