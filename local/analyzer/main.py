"""Analyzer HTTP service — receives MinIO webhook notifications, runs the
green-pixel heuristic, persists metrics, and syncs to GCP.
"""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime, timezone

import psycopg2
from flask import Flask, Response, jsonify, request
from minio import Minio
from PIL import Image
from prometheus_client import Counter, Histogram, generate_latest

from analysis import AnalysisResult, compute_green_pixel_ratio, should_sample
from sync import push_image_to_gcs, push_metric_to_bq

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio.garden.svc.cluster.local:9000")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "garden-images")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "")
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres.garden.svc.cluster.local")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "garden")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
SYNC_ENABLED = os.environ.get("SYNC_ENABLED", "true").lower() == "true"
SAMPLE_NOON_HOUR_UTC = int(os.environ.get("SAMPLE_NOON_HOUR_UTC", "18"))
SAMPLE_RATIO_THRESHOLD = float(os.environ.get("SAMPLE_RATIO_THRESHOLD", "0.05"))
DEVICE_ID = os.environ.get("DEVICE_ID", "pi-01")

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
IMAGES_PROCESSED = Counter("analyzer_images_processed_total", "Total images analyzed")
IMAGES_FAILED = Counter("analyzer_images_failed_total", "Images that failed analysis")
ANALYSIS_DURATION = Histogram(
    "analyzer_analysis_duration_seconds", "Time spent analyzing an image"
)

# ---------------------------------------------------------------------------
# Clients (lazy init)
# ---------------------------------------------------------------------------
_minio_client: Minio | None = None
_pg_conn = None


def get_minio() -> Minio:
    global _minio_client
    if _minio_client is None:
        _minio_client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=False,
        )
    return _minio_client


def get_pg():
    global _pg_conn
    if _pg_conn is None or _pg_conn.closed:
        _pg_conn = psycopg2.connect(
            host=POSTGRES_HOST,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
        )
        _pg_conn.autocommit = True
    return _pg_conn


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS plant_metrics (
    capture_time      TIMESTAMPTZ NOT NULL,
    ingest_time       TIMESTAMPTZ NOT NULL DEFAULT now(),
    image_key         TEXT        NOT NULL UNIQUE,
    green_pixel_ratio DOUBLE PRECISION NOT NULL,
    image_width       INTEGER     NOT NULL,
    image_height      INTEGER     NOT NULL,
    synced_to_gcs     BOOLEAN     NOT NULL DEFAULT false,
    device_id         TEXT        NOT NULL DEFAULT 'pi-01'
);
CREATE INDEX IF NOT EXISTS idx_plant_metrics_capture_time
    ON plant_metrics (capture_time);
"""

INSERT_SQL = """
INSERT INTO plant_metrics
    (capture_time, image_key, green_pixel_ratio, image_width, image_height,
     synced_to_gcs, device_id)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (image_key) DO NOTHING;
"""


def ensure_schema() -> None:
    conn = get_pg()
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)


def insert_metric(
    capture_time: datetime,
    image_key: str,
    result: AnalysisResult,
    synced: bool,
) -> None:
    conn = get_pg()
    with conn.cursor() as cur:
        cur.execute(
            INSERT_SQL,
            (
                capture_time,
                image_key,
                result.green_pixel_ratio,
                result.width,
                result.height,
                synced,
                DEVICE_ID,
            ),
        )


def get_previous_ratio() -> float | None:
    """Fetch the most recent green_pixel_ratio for sampling comparison."""
    conn = get_pg()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT green_pixel_ratio FROM plant_metrics "
            "ORDER BY capture_time DESC LIMIT 1"
        )
        row = cur.fetchone()
        return row[0] if row else None


def mark_synced(image_key: str) -> None:
    conn = get_pg()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE plant_metrics SET synced_to_gcs = true WHERE image_key = %s",
            (image_key,),
        )


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------
def parse_capture_time(image_key: str) -> datetime:
    """Parse YYYY/MM/DD/HHMMSS.jpg -> datetime (UTC)."""
    # Strip extension and parse
    stem = image_key.rsplit(".", 1)[0]  # YYYY/MM/DD/HHMMSS
    return datetime.strptime(stem, "%Y/%m/%d/%H%M%S").replace(tzinfo=timezone.utc)


def process_image(image_key: str) -> None:
    """Full pipeline: fetch -> analyze -> persist -> sync."""
    logger.info("Processing %s", image_key)

    # Fetch from MinIO
    client = get_minio()
    response = client.get_object(MINIO_BUCKET, image_key)
    image_bytes = response.read()
    response.close()
    response.release_conn()

    # Analyze
    image = Image.open(io.BytesIO(image_bytes))
    with ANALYSIS_DURATION.time():
        result = compute_green_pixel_ratio(image)

    capture_time = parse_capture_time(image_key)
    previous_ratio = get_previous_ratio()

    # Sync decision
    synced = False
    if SYNC_ENABLED:
        sample = should_sample(
            current_ratio=result.green_pixel_ratio,
            previous_ratio=previous_ratio,
            capture_hour_utc=capture_time.hour,
            noon_hour_utc=SAMPLE_NOON_HOUR_UTC,
            ratio_threshold=SAMPLE_RATIO_THRESHOLD,
        )

        # Always push metrics to BQ
        bq_row = {
            "capture_time": capture_time.isoformat(),
            "ingest_time": datetime.now(timezone.utc).isoformat(),
            "image_key": image_key,
            "green_pixel_ratio": result.green_pixel_ratio,
            "image_width": result.width,
            "image_height": result.height,
            "synced_to_gcs": sample,
            "device_id": DEVICE_ID,
        }
        push_metric_to_bq(bq_row)

        # Push sampled images to GCS
        if sample:
            if push_image_to_gcs(image_key, image_bytes):
                synced = True

    # Persist locally (always succeeds independently of GCP)
    insert_metric(capture_time, image_key, result, synced)
    IMAGES_PROCESSED.inc()

    logger.info(
        "Done: %s ratio=%.4f synced=%s",
        image_key, result.green_pixel_ratio, synced,
    )


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------
@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype="text/plain; version=0.0.4")


@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive MinIO bucket notification."""
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "empty payload"}), 400

    records = payload.get("Records", [])
    for record in records:
        s3_info = record.get("s3", {})
        obj = s3_info.get("object", {})
        key = obj.get("key", "")
        if not key:
            continue

        try:
            process_image(key)
        except Exception:
            IMAGES_FAILED.inc()
            logger.exception("Failed to process %s", key)

    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
with app.app_context():
    ensure_schema()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
