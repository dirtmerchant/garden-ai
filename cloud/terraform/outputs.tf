output "gcs_bucket" {
  description = "GCS bucket for sampled images"
  value       = google_storage_bucket.images.name
}

output "bq_table" {
  description = "BigQuery table for plant metrics"
  value       = "${var.project_id}.${google_bigquery_dataset.garden.dataset_id}.${google_bigquery_table.plant_metrics.table_id}"
}

output "service_account_email" {
  description = "Service account email for the local analyzer"
  value       = google_service_account.analyzer_push.email
}

output "service_account_key" {
  description = "Service account key (base64-encoded JSON) — store in 1Password"
  value       = google_service_account_key.analyzer_push.private_key
  sensitive   = true
}
