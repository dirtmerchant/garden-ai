"""Pure analysis functions — no I/O, no MinIO/Postgres/cloud imports.

Unit-testable offline.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class AnalysisResult:
    green_pixel_ratio: float
    width: int
    height: int


def compute_green_pixel_ratio(image: Image.Image) -> AnalysisResult:
    """Return the fraction of pixels where the green channel dominates.

    A pixel is "green" when its G value exceeds both R and B by at least
    a small margin (avoids counting grey/white pixels as green).
    """
    arr = np.asarray(image.convert("RGB"), dtype=np.int16)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

    margin = 15  # minimum difference G must exceed R and B by
    green_mask = (g > r + margin) & (g > b + margin)

    total = green_mask.size
    ratio = float(green_mask.sum()) / total if total > 0 else 0.0

    return AnalysisResult(
        green_pixel_ratio=ratio,
        width=image.width,
        height=image.height,
    )


def should_sample(
    current_ratio: float,
    previous_ratio: float | None,
    capture_hour_utc: int,
    noon_hour_utc: int = 18,
    ratio_threshold: float = 0.05,
) -> bool:
    """Decide whether an image should be synced to GCS.

    Sampling policy (from CLAUDE.md):
    - One image per day: the capture closest to solar noon (configurable hour).
    - Any image whose green_pixel_ratio changes by more than *ratio_threshold*
      vs. the prior reading.
    """
    # Solar-noon sample.
    if capture_hour_utc == noon_hour_utc:
        return True

    # Significant-change sample.
    if previous_ratio is not None:
        if abs(current_ratio - previous_ratio) >= ratio_threshold:
            return True

    return False
