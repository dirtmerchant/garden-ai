terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# GCS bucket for sampled images
# ---------------------------------------------------------------------------
resource "google_storage_bucket" "images" {
  name     = var.gcs_bucket_name
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }
}

# ---------------------------------------------------------------------------
# BigQuery dataset + table
# ---------------------------------------------------------------------------
resource "google_bigquery_dataset" "garden" {
  dataset_id = var.bq_dataset_id
  location   = var.region
}

resource "google_bigquery_table" "plant_metrics" {
  dataset_id          = google_bigquery_dataset.garden.dataset_id
  table_id            = "plant_metrics"
  deletion_protection = false

  time_partitioning {
    type  = "DAY"
    field = "capture_time"
  }

  schema = jsonencode([
    { name = "capture_time", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "ingest_time", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "image_key", type = "STRING", mode = "REQUIRED" },
    { name = "green_pixel_ratio", type = "FLOAT", mode = "REQUIRED" },
    { name = "image_width", type = "INTEGER", mode = "REQUIRED" },
    { name = "image_height", type = "INTEGER", mode = "REQUIRED" },
    { name = "synced_to_gcs", type = "BOOLEAN", mode = "REQUIRED" },
    { name = "device_id", type = "STRING", mode = "REQUIRED" },
  ])
}

# ---------------------------------------------------------------------------
# Service account — least privilege for the local analyzer to push
# ---------------------------------------------------------------------------
resource "google_service_account" "analyzer_push" {
  account_id   = "garden-analyzer-push"
  display_name = "Garden Analyzer Push (local tier)"
}

resource "google_storage_bucket_iam_member" "analyzer_gcs" {
  bucket = google_storage_bucket.images.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.analyzer_push.email}"
}

resource "google_bigquery_dataset_iam_member" "analyzer_bq" {
  dataset_id = google_bigquery_dataset.garden.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.analyzer_push.email}"
}

resource "google_project_iam_member" "analyzer_bq_job" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.analyzer_push.email}"
}

resource "google_service_account_key" "analyzer_push" {
  service_account_id = google_service_account.analyzer_push.name
}
