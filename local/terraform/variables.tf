variable "repo_url" {
  description = "Git repository URL for the garden-bot source"
  type        = string
  default     = "https://github.com/dirtmerchant/garden_ai.git"
}

variable "nas_ip" {
  description = "Synology NAS IP address"
  type        = string
  default     = "192.168.1.10"
}

variable "nas_nfs_path" {
  description = "NFS export path on the NAS for MinIO data"
  type        = string
  default     = "/volume1/garden-minio"
}

variable "minio_nfs_capacity" {
  description = "Capacity to advertise for the MinIO NFS PV"
  type        = string
  default     = "500Gi"
}
