variable "project_id" {
  description = "GCP project ID"
  type        = string
  default     = "garden-ai-467116"
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "gcs_bucket_name" {
  description = "GCS bucket for sampled images"
  type        = string
  default     = "garden-monitor-images"
}

variable "bq_dataset_id" {
  description = "BigQuery dataset ID"
  type        = string
  default     = "garden_monitor"
}
