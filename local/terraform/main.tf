resource "kubernetes_namespace" "garden" {
  metadata {
    name = "garden"

    labels = {
      "pod-security.kubernetes.io/enforce" = "baseline"
      "pod-security.kubernetes.io/warn"    = "restricted"
      "pod-security.kubernetes.io/audit"   = "restricted"
    }
  }
}

resource "kubernetes_persistent_volume" "minio_nfs" {
  metadata {
    name = "minio-nfs"
  }

  spec {
    capacity = {
      storage = var.minio_nfs_capacity
    }

    access_modes                     = ["ReadWriteOnce"]
    persistent_volume_reclaim_policy = "Retain"

    persistent_volume_source {
      nfs {
        server = var.nas_ip
        path   = var.nas_nfs_path
      }
    }
  }
}

resource "kubernetes_persistent_volume" "landing_zone_nfs" {
  metadata {
    name = "landing-zone-nfs"
  }

  spec {
    capacity = {
      storage = "10Gi"
    }

    access_modes                     = ["ReadWriteOnce"]
    persistent_volume_reclaim_policy = "Retain"

    persistent_volume_source {
      nfs {
        server = var.nas_ip
        path   = var.nas_landing_path
      }
    }
  }
}

resource "kubernetes_manifest" "argocd_repo_credential" {
  manifest = {
    apiVersion = "external-secrets.io/v1"
    kind       = "ExternalSecret"

    metadata = {
      name      = "garden-bot-repo"
      namespace = "argocd"
    }

    spec = {
      refreshInterval = "1h"

      secretStoreRef = {
        name = "onepassword"
        kind = "ClusterSecretStore"
      }

      target = {
        name           = "garden-bot-repo"
        creationPolicy = "Owner"

        template = {
          metadata = {
            labels = {
              "argocd.argoproj.io/secret-type" = "repository"
            }
          }
        }
      }

      data = [
        {
          secretKey = "type"
          remoteRef = { key = "garden-bot-repo", property = "type" }
        },
        {
          secretKey = "url"
          remoteRef = { key = "garden-bot-repo", property = "url" }
        },
        {
          secretKey = "username"
          remoteRef = { key = "garden-bot-repo", property = "username" }
        },
        {
          secretKey = "password"
          remoteRef = { key = "garden-bot-repo", property = "password" }
        },
      ]
    }
  }
}

resource "kubernetes_manifest" "argocd_application" {
  manifest = {
    apiVersion = "argoproj.io/v1alpha1"
    kind       = "Application"

    metadata = {
      name      = "garden-bot"
      namespace = "argocd"

      finalizers = [
        "resources-finalizer.argocd.argoproj.io"
      ]
    }

    spec = {
      project = "default"

      source = {
        repoURL        = var.repo_url
        targetRevision = "main"
        path           = "local/manifests"
      }

      destination = {
        server    = "https://kubernetes.default.svc"
        namespace = kubernetes_namespace.garden.metadata[0].name
      }

      syncPolicy = {
        automated = {
          prune    = true
          selfHeal = true
        }
      }
    }
  }
}
