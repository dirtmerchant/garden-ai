"""Sync metrics to BigQuery and sampled images to GCS.

Best-effort, async push. Local correctness never depends on GCP being up.
"""

from __future__ import annotations

import logging
import os

from google.cloud import bigquery, storage

logger = logging.getLogger(__name__)

GCS_BUCKET = os.environ.get("GCS_BUCKET", "garden-monitor-images")
BQ_DATASET = os.environ.get("BQ_DATASET", "garden_monitor")
BQ_TABLE = os.environ.get("BQ_TABLE", "plant_metrics")
GCP_PROJECT = os.environ.get("GCP_PROJECT", "")


def push_metric_to_bq(row: dict) -> bool:
    """Insert a single metrics row into BigQuery. Returns True on success."""
    try:
        client = bigquery.Client(project=GCP_PROJECT)
        table_ref = f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}"
        errors = client.insert_rows_json(
            table_ref, [row], row_ids=[row.get("image_key", "")]
        )
        if errors:
            logger.error("BigQuery insert errors: %s", errors)
            return False
        return True
    except Exception:
        logger.exception("Failed to push metric to BigQuery")
        return False


def push_image_to_gcs(image_key: str, image_bytes: bytes) -> bool:
    """Upload an image to GCS. Returns True on success."""
    try:
        client = storage.Client(project=GCP_PROJECT)
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(image_key)
        blob.upload_from_string(image_bytes, content_type="image/jpeg")
        return True
    except Exception:
        logger.exception("Failed to push image to GCS: %s", image_key)
        return False
