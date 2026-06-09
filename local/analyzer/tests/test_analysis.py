"""Tests for analysis.py — pure functions, no I/O dependencies."""

import numpy as np
import pytest
from PIL import Image

from analysis import AnalysisResult, compute_green_pixel_ratio, should_sample


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _solid_image(r: int, g: int, b: int, size: tuple[int, int] = (100, 100)) -> Image.Image:
    """Create a solid-color image. *size* is (width, height)."""
    w, h = size
    arr = np.full((h, w, 3), [r, g, b], dtype=np.uint8)
    return Image.fromarray(arr, "RGB")


# ---------------------------------------------------------------------------
# compute_green_pixel_ratio
# ---------------------------------------------------------------------------
class TestGreenPixelRatio:
    def test_all_green(self):
        img = _solid_image(0, 200, 0)
        result = compute_green_pixel_ratio(img)
        assert result.green_pixel_ratio == 1.0
        assert result.width == 100
        assert result.height == 100

    def test_no_green(self):
        img = _solid_image(200, 0, 0)
        result = compute_green_pixel_ratio(img)
        assert result.green_pixel_ratio == 0.0

    def test_all_white_not_green(self):
        """White pixels (255,255,255) should not count as green."""
        img = _solid_image(255, 255, 255)
        result = compute_green_pixel_ratio(img)
        assert result.green_pixel_ratio == 0.0

    def test_all_grey_not_green(self):
        """Grey pixels should not count as green (G doesn't dominate)."""
        img = _solid_image(128, 128, 128)
        result = compute_green_pixel_ratio(img)
        assert result.green_pixel_ratio == 0.0

    def test_half_green(self):
        """Top half green, bottom half red -> ~0.5."""
        arr = np.zeros((100, 100, 3), dtype=np.uint8)
        arr[:50, :] = [0, 200, 0]
        arr[50:, :] = [200, 0, 0]
        img = Image.fromarray(arr, "RGB")
        result = compute_green_pixel_ratio(img)
        assert result.green_pixel_ratio == pytest.approx(0.5)

    def test_tiny_image(self):
        img = _solid_image(0, 200, 0, size=(1, 1))
        result = compute_green_pixel_ratio(img)
        assert result.green_pixel_ratio == 1.0
        assert result.width == 1
        assert result.height == 1

    def test_near_green_below_margin(self):
        """G=130, R=120, B=120: difference is only 10, below margin of 15."""
        img = _solid_image(120, 130, 120)
        result = compute_green_pixel_ratio(img)
        assert result.green_pixel_ratio == 0.0

    def test_near_green_above_margin(self):
        """G=150, R=120, B=120: difference is 30, above margin."""
        img = _solid_image(120, 150, 120)
        result = compute_green_pixel_ratio(img)
        assert result.green_pixel_ratio == 1.0

    def test_rgba_converted(self):
        """RGBA images should be handled (converted to RGB)."""
        arr = np.full((10, 10, 4), [0, 200, 0, 255], dtype=np.uint8)
        img = Image.fromarray(arr, "RGBA")
        result = compute_green_pixel_ratio(img)
        assert result.green_pixel_ratio == 1.0

    def test_dimensions_reported(self):
        img = _solid_image(0, 0, 0, size=(320, 240))
        result = compute_green_pixel_ratio(img)
        assert result.width == 320
        assert result.height == 240


# ---------------------------------------------------------------------------
# should_sample
# ---------------------------------------------------------------------------
class TestShouldSample:
    def test_noon_always_samples(self):
        assert should_sample(0.5, 0.5, capture_hour_utc=18, noon_hour_utc=18) is True

    def test_non_noon_no_change(self):
        assert should_sample(0.5, 0.5, capture_hour_utc=10, noon_hour_utc=18) is False

    def test_large_increase(self):
        assert should_sample(0.6, 0.5, capture_hour_utc=10, ratio_threshold=0.05) is True

    def test_large_decrease(self):
        assert should_sample(0.4, 0.5, capture_hour_utc=10, ratio_threshold=0.05) is True

    def test_below_threshold(self):
        assert should_sample(0.52, 0.5, capture_hour_utc=10, ratio_threshold=0.05) is False

    def test_exactly_at_threshold(self):
        assert should_sample(0.55, 0.5, capture_hour_utc=10, ratio_threshold=0.05) is True

    def test_no_previous_ratio(self):
        """First capture ever — no previous, non-noon -> don't sample."""
        assert should_sample(0.5, None, capture_hour_utc=10) is False

    def test_no_previous_but_noon(self):
        """First capture at noon -> sample."""
        assert should_sample(0.5, None, capture_hour_utc=18) is True

    def test_custom_noon_hour(self):
        assert should_sample(0.5, 0.5, capture_hour_utc=12, noon_hour_utc=12) is True

    def test_custom_threshold(self):
        assert should_sample(0.6, 0.5, capture_hour_utc=10, ratio_threshold=0.2) is False
        assert should_sample(0.8, 0.5, capture_hour_utc=10, ratio_threshold=0.2) is True
