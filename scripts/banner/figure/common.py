"""Shared paths and source facts for the banner figure (Giambologna's Mercury). Tool only, not part of the plugin.

Source photo: Rijksmuseum RP-F-00-9348, "Bronzen beeld van Mercurius door Giovanni da Bologna of Giambologna"
(photograph, 1850-1900), CC0 1.0, via Wikimedia Commons; licence read from the Commons API (extmetadata
LicenseShortName = CC0) on 2026-11-07.
"""

import os
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent  # scripts/banner/figure
OUT = HERE.parent  # scripts/banner: the rendered assets mercury@1x.png, mercury@2x.png, mercury.json
WORK = Path(os.environ.get("CB_BANNER_WORK") or Path(tempfile.gettempdir()) / "cb-banner-figure")

PHOTO_URL = ("https://commons.wikimedia.org/wiki/Special:FilePath/"
             "Bronzen_beeld_van_Mercurius_door_Giovanni_da_Bologna_of_Giambologna,_RP-F-00-9348.jpg")
PHOTO_SHA256 = "68bf6e3b669ccd823ba29d72b6e7a9612228c6119bbe83c692ea2710e96d8a92"  # 5326x7106 JPEG
PHOTO_CREDIT = "Rijksmuseum RP-F-00-9348, CC0"
CROP = (1600, 1550, 3750, 5950)  # statue incl. the raised finger (tip at y ~1622) in full-resolution pixels


def work_dir() -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    return WORK
