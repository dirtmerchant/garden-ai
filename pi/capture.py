#!/usr/bin/env python3
"""Capture a still from the Naturebytes camera and write it to the NAS landing zone.

Designed for Raspberry Pi Model A+ v1 (ARMv6, 512MB RAM).
Uses rpicam-still (Bookworm-era replacement for raspistill).
"""

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

LANDING_ZONE = os.environ.get("LANDING_ZONE", "/mnt/garden-landing")


def capture_image(output_path: str) -> None:
    """Invoke rpicam-still to capture a JPEG to *output_path*."""
    cmd = [
        "rpicam-still",
        "--nopreview",
        "--timeout", "2000",
        "--output", output_path,
    ]
    subprocess.run(cmd, check=True, timeout=30)


def main() -> None:
    now = datetime.now(timezone.utc)
    # Key convention: YYYY/MM/DD/HHMMSS.jpg (UTC)
    relative_key = now.strftime("%Y/%m/%d/%H%M%S.jpg")
    dest = Path(LANDING_ZONE) / relative_key

    dest.parent.mkdir(parents=True, exist_ok=True)

    # Capture to a temp file first, then move — avoids partial files in the
    # landing zone if the camera fails mid-write.
    with tempfile.NamedTemporaryFile(
        suffix=".jpg", dir=dest.parent, delete=False
    ) as tmp:
        tmp_path = tmp.name

    try:
        capture_image(tmp_path)
        os.rename(tmp_path, str(dest))
        print(f"captured {relative_key}")
    except Exception:
        # Clean up partial file on failure.
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"capture failed: {exc}", file=sys.stderr)
        sys.exit(1)
