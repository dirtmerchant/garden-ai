terraform {
  backend "gcs" {
    bucket = "garden-ai-467116-tfstate"
    prefix = "garden-monitor"
  }
}
