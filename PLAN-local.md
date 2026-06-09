# PLAN-local.md — k3s Core Tier

The operational core: capture → MinIO → analyzer (green-pixel + sampling + sync) → Postgres → Grafana. Runs free, works offline, is the source of truth. Read `CLAUDE.md` first — especially the sync contract, which this tier produces.

Build this tier **first**. It is a complete, useful system on its own; the cloud tier is additive.

## Design decisions (settled)

- **IaC split**: Terraform bootstraps the platform (namespace, ArgoCD Application); ArgoCD manages the application workloads. Standard pattern — Terraform handles what ArgoCD can't self-bootstrap, ArgoCD handles everything that benefits from continuous reconciliation.
- **Terraform** lives in `local/terraform/`. Uses the `kubernetes` provider against the k3s cluster. Creates the `garden` namespace, NFS PV, ArgoCD repo credential, and the ArgoCD `Application` resource. No homelab repo changes needed.
- **Container registry**: Docker Registry on the Synology NAS at `192.168.1.10:5050`. Runs as a container via Synology Container Manager. k3s nodes configured via `/etc/rancher/k3s/registries.yaml` to allow it as an HTTP registry. Analyzer images pushed here.
- **ArgoCD** syncs `local/manifests/` — deployments, services, PVCs, ExternalSecrets, ConfigMaps, IngressRoutes, NetworkPolicies. Automated sync with prune + self-heal, matching the existing cluster pattern.
- **Grafana**: Dedicated instance for the garden bot (not a datasource on the cluster Grafana). Keeps this project fully self-contained.
- **Storage**: MinIO backed by the **Synology NAS** (192.168.1.10) via NFS — ~11TB RAID 1 capacity, more than enough for the full image history. Terraform creates the NFS PersistentVolume (infrastructure concern); ArgoCD manages the PVC. Postgres stays on **Longhorn** (small dataset, benefits from SSD latency, 3× replication).
- **Secrets**: External Secrets Operator → 1Password `Homelab` vault, `ClusterSecretStore` named `onepassword`. Create 1Password items before deploying.
- **Namespace**: `garden` — created by Terraform.
- **Ingress**: Traefik IngressRoute at `garden.homelab.bertbullough.com` for Grafana. Pi-hole dnsmasq already resolves `*.homelab.bertbullough.com`.
- **Network policies**: Follow the homelab pattern — ingress restricted to Traefik (for Grafana) and intra-namespace (analyzer ↔ MinIO/Postgres); egress unrestricted for services that need external access (sync to GCP).

## Prerequisites (one-time)

- k3s cluster reachable; `kubectl` context set (kubeconfig for the kubernetes Terraform provider).
- ArgoCD running in the cluster (already deployed via the homelab repo).
- External Secrets Operator + `ClusterSecretStore` named `onepassword` (1Password `Homelab` vault) — already deployed.
- **Synology NAS NFS shares**: create two shared folders on the DS218+ (192.168.1.10):
  1. `/volume1/garden-minio` — MinIO data store. Enable NFS, grant read/write to NUC IPs (192.168.1.20–22). Set `squash` to `no_root_squash` or map to UID/GID 1000:1000 (MinIO container user).
  2. `/volume1/garden-landing` — Pi capture landing zone. Enable NFS, grant read/write to NUC IPs (for the ingest job) and to the Pi's IP (for capture writes). The Pi mounts this share (e.g. at `/mnt/garden-landing`).
- **Docker Registry on NAS**: run the `registry:2` container via Synology Container Manager on port 5000. Map a volume for image storage (e.g. `/volume1/docker-registry:/var/lib/registry`). Configure each k3s node's `/etc/rancher/k3s/registries.yaml`:
  ```yaml
  mirrors:
    "192.168.1.10:5050":
      endpoint:
        - "http://192.168.1.10:5050"
  ```
  Then restart k3s on each node (`sudo systemctl restart k3s` / `k3s-agent`).
- Create 1Password items in the `Homelab` vault (if not already present):
  - `minio` — fields: `root-user`, `root-password`
  - `garden-postgres` — fields: `postgres-password`
  - `garden-gcp-sa` — fields: `sa-key` (JSON key for the GCP service account from PLAN-cloud.md C1)
  - `garden-bot-repo` — fields: `type` (= `git`), `url` (= repo HTTPS URL), `username`, `password` (GitHub PAT) — for ArgoCD repo access

## Session L1 — Terraform bootstrap + ArgoCD wiring

Terraform creates the resources ArgoCD can't self-bootstrap: the namespace, NFS PV, ArgoCD repo credential (so ArgoCD can pull from this repo with the GitHub PAT), and the ArgoCD Application.

### Terraform (`local/terraform/`)

`providers.tf`:

```hcl
terraform {
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
  }
}

provider "kubernetes" {
  # Uses the current kubeconfig context by default.
  # Optionally set config_path / config_context for explicit targeting.
}
```

`main.tf`:

```hcl
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
          remoteRef = { key = "garden-bot-repo/type" }
        },
        {
          secretKey = "url"
          remoteRef = { key = "garden-bot-repo/url" }
        },
        {
          secretKey = "username"
          remoteRef = { key = "garden-bot-repo/username" }
        },
        {
          secretKey = "password"
          remoteRef = { key = "garden-bot-repo/password" }
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
```

`variables.tf`:

```hcl
variable "repo_url" {
  description = "Git repository URL for the garden-bot source"
  type        = string
  default     = "https://github.com/dirtmerchant/garden_bot.git"
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
```

State is local (a handful of bootstrap resources; no remote backend needed). Add `*.tfstate*` and `.terraform/` to `.gitignore`.

### Application manifests — ExternalSecrets

Once ArgoCD syncs, it picks up everything in `local/manifests/`. Start with `externalsecret.yaml` (secrets must resolve before workloads reference them):

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: minio-secret
  namespace: garden
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: onepassword
    kind: ClusterSecretStore
  target:
    name: minio-secret
    creationPolicy: Owner
  data:
    - secretKey: root-user
      remoteRef:
        key: minio/root-user
    - secretKey: root-password
      remoteRef:
        key: minio/root-password
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: postgres-secret
  namespace: garden
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: onepassword
    kind: ClusterSecretStore
  target:
    name: postgres-secret
    creationPolicy: Owner
  data:
    - secretKey: postgres-password
      remoteRef:
        key: garden-postgres/postgres-password
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: gcp-sa-secret
  namespace: garden
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: onepassword
    kind: ClusterSecretStore
  target:
    name: gcp-sa-secret
    creationPolicy: Owner
  data:
    - secretKey: sa-key
      remoteRef:
        key: garden-gcp-sa/sa-key
```

### Bootstrap sequence

```bash
cd local/terraform
terraform init
terraform plan
terraform apply    # creates namespace + registers ArgoCD app
```

ArgoCD then auto-syncs `local/manifests/` into the `garden` namespace. From this point, all workload changes go through Git → ArgoCD.

**Done when**: `terraform apply` is clean (namespace, NFS PV, and ArgoCD Application created), ArgoCD shows `garden-bot` app synced and healthy, ExternalSecrets resolve into k8s Secrets.

## Session L2 — MinIO + Postgres

All manifests under `local/manifests/`.

### MinIO

`minio-pvc.yaml` — binds to the NFS PV created by Terraform (NAS-backed):

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: minio-data
  namespace: garden
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ""
  volumeName: minio-nfs
  resources:
    requests:
      storage: 500Gi
```

`minio-deployment.yaml` — single-node MinIO server:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: minio
  namespace: garden
  labels:
    app: minio
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: minio
  template:
    metadata:
      labels:
        app: minio
    spec:
      automountServiceAccountToken: false
      securityContext:
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: minio
          image: minio/minio:latest
          args: ["server", "/data", "--console-address", ":9001"]
          ports:
            - containerPort: 9000
              name: api
            - containerPort: 9001
              name: console
          securityContext:
            runAsNonRoot: true
            runAsUser: 1000
            runAsGroup: 1000
            allowPrivilegeEscalation: false
            capabilities:
              drop: [ALL]
          env:
            - name: MINIO_ROOT_USER
              valueFrom:
                secretKeyRef:
                  name: minio-secret
                  key: root-user
            - name: MINIO_ROOT_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: minio-secret
                  key: root-password
          resources:
            requests:
              cpu: 200m
              memory: 256Mi
            limits:
              cpu: "1"
              memory: 1Gi
          readinessProbe:
            httpGet:
              path: /minio/health/ready
              port: 9000
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /minio/health/live
              port: 9000
            periodSeconds: 30
          volumeMounts:
            - name: data
              mountPath: /data
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: minio-data
```

`minio-service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: minio
  namespace: garden
spec:
  type: ClusterIP
  selector:
    app: minio
  ports:
    - port: 9000
      targetPort: api
      name: api
    - port: 9001
      targetPort: console
      name: console
```

### Postgres

`postgres-pvc.yaml` — Longhorn, 10Gi:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-data
  namespace: garden
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: longhorn
  resources:
    requests:
      storage: 10Gi
```

`postgres-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
  namespace: garden
  labels:
    app: postgres
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      automountServiceAccountToken: false
      securityContext:
        fsGroup: 999
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: postgres
          image: postgres:latest
          ports:
            - containerPort: 5432
              name: postgres
          securityContext:
            runAsNonRoot: true
            runAsUser: 999
            runAsGroup: 999
            allowPrivilegeEscalation: false
            capabilities:
              drop: [ALL]
          env:
            - name: POSTGRES_DB
              value: garden
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: postgres-secret
                  key: postgres-password
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi
          readinessProbe:
            exec:
              command: ["pg_isready", "-U", "postgres"]
            periodSeconds: 10
          livenessProbe:
            exec:
              command: ["pg_isready", "-U", "postgres"]
            periodSeconds: 30
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: postgres-data
```

`postgres-service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: garden
spec:
  type: ClusterIP
  selector:
    app: postgres
  ports:
    - port: 5432
      targetPort: postgres
```

### Init job

`init-db-job.yaml` — create the `plant_metrics` table (schema from CLAUDE.md) and the `garden-images` MinIO bucket. Run as a one-shot Job. Alternatively, handle in the analyzer's startup (idempotent `CREATE TABLE IF NOT EXISTS` + `mc mb --ignore-existing`).

### Network policies

`networkpolicy.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: minio
  namespace: garden
spec:
  podSelector:
    matchLabels:
      app: minio
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: analyzer
      ports:
        - protocol: TCP
          port: 9000
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: traefik
      ports:
        - protocol: TCP
          port: 9001
  egress:
    # NFS to Synology NAS
    - to:
        - ipBlock:
            cidr: 192.168.1.10/32
      ports:
        - protocol: TCP
          port: 2049
    # DNS
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: postgres
  namespace: garden
spec:
  podSelector:
    matchLabels:
      app: postgres
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: analyzer
        - podSelector:
            matchLabels:
              app: grafana
      ports:
        - protocol: TCP
          port: 5432
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: analyzer
  namespace: garden
spec:
  podSelector:
    matchLabels:
      app: analyzer
  policyTypes:
    - Ingress
    - Egress
  egress:
    - {}
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: grafana
  namespace: garden
spec:
  podSelector:
    matchLabels:
      app: grafana
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: traefik
      ports:
        - protocol: TCP
          port: 3000
  egress:
    - {}
```

**Done when**: MinIO is running with NAS-backed NFS storage and Postgres with a Longhorn PVC, both survive pod restarts with data intact and are reachable in-cluster. `plant_metrics` table exists. `garden-images` bucket exists.

## Session L2.5 — MinIO bucket notifications

Configure MinIO to emit bucket notifications on `s3:ObjectCreated:*` for the `garden-images` bucket. Options:

1. **Webhook** (simplest): MinIO POSTs to the analyzer's HTTP endpoint on object creation. Configure via `mc event add` or MinIO environment variables.
2. **Kafka/NATS/Redis**: Heavier; unnecessary for a single consumer.

Go with webhook. The analyzer exposes a `/webhook` endpoint that receives the notification payload, extracts the object key, and processes the image.

Configure the webhook target either:

- Via a MinIO init Job (`mc event add garden-images arn:minio:sqs::webhook:webhook --event put`)
- Or via MinIO environment variables (`MINIO_NOTIFY_WEBHOOK_*`).

**Done when**: uploading an object to `garden-images` triggers an HTTP POST to the analyzer.

## Session L3 — Pi capture script + NAS ingest

### Hardware constraints (resolved)

- **Board**: Raspberry Pi Model A+ v1 — single-core ARMv6, 512MB RAM, single USB port, no onboard networking. USB WiFi dongle required.
- **Camera**: Naturebytes Wildlife Camera Kit module (CSI ribbon cable, not an official Pi camera). Greenfield unit — no OS yet. Install Raspberry Pi OS Lite (Bookworm, 32-bit) for ARMv6 compatibility; use `rpicam-still` (the Bookworm-era replacement for `raspistill`).
- **PIR sensor**: wired but unused; captures are cron-scheduled.

### Capture script

`pi/capture.py`: capture a still, key it `YYYY/MM/DD/HHMMSS.jpg` (UTC), write to the NAS landing zone.

- Invoke the camera via subprocess (`rpicam-still -o <path>`).
- Write directly to a mounted NAS share (NFS or SMB from the Synology DS218+, e.g. mounted at `/mnt/garden-landing`).
- No MinIO or S3 client needed on the Pi — the Pi just writes a file to the NAS mount.
- `crontab.example` for capture interval; pinned `requirements.txt`.
- Keep the script minimal — this Pi has 512MB RAM and a single core.

### NAS landing zone → MinIO ingest

A k3s-side ingest process watches the NAS landing zone and moves images into MinIO `garden-images`:

- Option A: **CronJob** in k3s that periodically syncs the landing zone to MinIO (e.g. `mc mirror`), then deletes the source files.
- Option B: **Inotify/polling sidecar** that watches the NFS mount and uploads to MinIO on arrival.
- Option A is simpler and sufficient given capture intervals (every few minutes at most).

The NAS landing zone NFS share needs its own PV/PVC in the `garden` namespace (separate from MinIO's NFS share), or the ingest job can access the NAS share directly.

- **Done when**: running `capture.py` on the Pi writes a correctly-keyed image to the NAS landing zone, and the ingest process moves it into MinIO `garden-images`.

## Session L4 — Analyzer: analysis + persistence

### Pure analysis

`local/analyzer/analysis.py`: pure green-pixel function(s), no I/O — unit-testable offline.

- Input: image bytes (or numpy array).
- Output: `green_pixel_ratio` (float 0.0–1.0), image dimensions.
- No MinIO/Postgres/cloud imports in this file.

### Main service

`local/analyzer/main.py`: HTTP server (Flask or FastAPI) with a `/webhook` endpoint.

- Receives MinIO bucket notification (JSON payload).
- Extracts object key from the notification, fetches the image from MinIO.
- Parses `capture_time` from the key (`YYYY/MM/DD/HHMMSS.jpg`).
- Calls `analysis.py` for the green-pixel ratio.
- Inserts a `plant_metrics` row into Postgres.

### Deployment

`analyzer-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: analyzer
  namespace: garden
  labels:
    app: analyzer
spec:
  replicas: 1
  selector:
    matchLabels:
      app: analyzer
  template:
    metadata:
      labels:
        app: analyzer
    spec:
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: analyzer
          image: 192.168.1.10:5050/garden-analyzer:<tag>
          ports:
            - containerPort: 8080
              name: http
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: [ALL]
          env:
            - name: MINIO_ENDPOINT
              value: minio.garden.svc.cluster.local:9000
            - name: MINIO_BUCKET
              value: garden-images
            - name: MINIO_ACCESS_KEY
              valueFrom:
                secretKeyRef:
                  name: minio-secret
                  key: root-user
            - name: MINIO_SECRET_KEY
              valueFrom:
                secretKeyRef:
                  name: minio-secret
                  key: root-password
            - name: POSTGRES_HOST
              value: postgres.garden.svc.cluster.local
            - name: POSTGRES_DB
              value: garden
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: postgres-secret
                  key: postgres-password
            - name: GOOGLE_APPLICATION_CREDENTIALS
              value: /secrets/gcp/sa-key.json
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            periodSeconds: 10
          volumeMounts:
            - name: gcp-sa
              mountPath: /secrets/gcp
              readOnly: true
      volumes:
        - name: gcp-sa
          secret:
            secretName: gcp-sa-secret
```

`analyzer-service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: analyzer
  namespace: garden
spec:
  type: ClusterIP
  selector:
    app: analyzer
  ports:
    - port: 8080
      targetPort: http
```

### Container image

Build with a Dockerfile in `local/analyzer/`. Push to the NAS registry:

```bash
docker build -t 192.168.1.10:5050/garden-analyzer:latest local/analyzer/
docker push 192.168.1.10:5050/garden-analyzer:latest
```

Image should be minimal (`python:3.12-slim` base).

**Done when**: an upload to MinIO `garden-images` results in a correct Postgres row in `plant_metrics`, end to end in-cluster.

## Session L5 — Grafana dashboard

Deploy a dedicated Grafana instance in the `garden` namespace with a Postgres datasource.

`grafana-deployment.yaml` — standard Grafana with provisioned datasource:

- Mount a ConfigMap with the Postgres datasource provisioning YAML.
- Dashboard JSON provisioned via ConfigMap or added manually via the UI (provision if deterministic).
- Dashboard panels: `green_pixel_ratio` over time, latest reading, daily trend.

`grafana-service.yaml` — ClusterIP on port 3000.

`grafana-ingress.yaml`:

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: garden-grafana
  namespace: garden
spec:
  entryPoints:
    - websecure
  tls: {}
  routes:
    - match: Host(`garden.homelab.bertbullough.com`)
      kind: Rule
      middlewares:
        - name: security-headers
          namespace: traefik
      services:
        - name: grafana
          port: 3000
```

### Prometheus integration

The cluster already runs kube-prometheus-stack. Add `ServiceMonitor` resources so Prometheus scrapes garden bot services.

`servicemonitor.yaml`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: minio
  namespace: garden
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app: minio
  endpoints:
    - port: api
      path: /minio/v2/metrics/cluster
      interval: 30s
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: analyzer
  namespace: garden
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app: analyzer
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

The analyzer should expose a `/metrics` endpoint (Prometheus client library). MinIO exposes metrics natively. Postgres metrics can be added later via `postgres_exporter` sidecar if needed.

The `release: kube-prometheus-stack` label ensures the existing Prometheus instance discovers these ServiceMonitors (it's the label selector used by the Prometheus operator in the homelab).

**Done when**: dashboard at `https://garden.homelab.bertbullough.com` reflects new captures live; Prometheus is scraping MinIO and analyzer metrics.

## Session L6 — Sampling + sync (produces the cloud tier's input)

`local/analyzer/sync.py`: implement the sampling policy (CLAUDE.md) and the best-effort async push.

- **Metrics → BigQuery**: every `plant_metrics` row is pushed. Use the `google-cloud-bigquery` client, authenticated via the mounted GCP SA key.
- **Sampled images → GCS**: only images matching the sampling policy are copied. Use `google-cloud-storage`.
- Set `synced_to_gcs` accordingly in Postgres; retry unsynced rows/images on a periodic schedule.

Sampling policy (from CLAUDE.md):

- One image per day (solar-noon capture), **plus**
- Any image whose `green_pixel_ratio` changes by more than a configurable threshold vs. the prior reading.
- Policy is config-driven (environment variables or ConfigMap), not hard-coded.

The sync logic runs inside the analyzer process — either inline after each analysis, or on a separate background loop for retries.

GCP SA key comes from PLAN-cloud.md C1 (the service account must exist first — this is the one ordering dependency between tiers).

**Done when**: every capture's metrics appear in BigQuery; only policy-selected images appear in GCS; GCP downtime doesn't break the local tier (unsynced items retried on recovery).

## Session L7 — Tests

`local/analyzer/tests/test_analysis.py`:

- Pure analysis logic: known images → expected ratios; edge cases (all-green, no green, corrupt/empty image, tiny image).
- Sampling decision logic: mock threshold cases (ratio delta above/below threshold, solar-noon detection).
- No MinIO/Postgres/GCP imports — `analysis.py` is pure.

Run: `cd local/analyzer && python -m pytest tests/ -v`

**Done when**: `pytest` passes with meaningful coverage of analysis and sampling.

## File inventory

```text
local/
├── terraform/                     # Terraform bootstrap (run once)
│   ├── providers.tf               # kubernetes provider
│   ├── main.tf                    # namespace, NFS PV, ArgoCD repo credential + Application
│   └── variables.tf               # repo_url, NAS config
└── manifests/                     # ArgoCD syncs everything here
    ├── externalsecret.yaml        # MinIO, Postgres, GCP SA secrets
    ├── minio-pvc.yaml             # NFS PVC (binds to Terraform-created PV)
    ├── minio-deployment.yaml
    ├── minio-service.yaml
    ├── postgres-pvc.yaml          # Longhorn PVC
    ├── postgres-deployment.yaml
    ├── postgres-service.yaml
    ├── init-db-job.yaml           # table + bucket creation (optional if analyzer does it)
    ├── analyzer-deployment.yaml
    ├── analyzer-service.yaml
    ├── grafana-deployment.yaml
    ├── grafana-service.yaml
    ├── grafana-ingress.yaml       # Traefik IngressRoute
    ├── grafana-config.yaml        # ConfigMap: datasource + dashboard provisioning
    ├── servicemonitor.yaml        # Prometheus scraping for MinIO + analyzer
    └── networkpolicy.yaml         # all four services
```

No changes to the homelab repo are required. Terraform creates the namespace, NFS PV, repo credential, and ArgoCD Application directly.

## Out of scope here

- Anything cloud-side beyond the push target → PLAN-cloud.md.
- Vertex AI classification → stretch goal in PLAN-cloud.md.
