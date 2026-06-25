# Garden Plant Health Monitor

Hybrid plant-health monitoring system — edge compute for real-time analysis, cloud burst for ML and analytics.

```
        ┌─────────────────────── k3s home lab (core) ───────────────────────┐
Pi ──▶  │ capture ▶ MinIO (images) ▶ analyzer (green-pixel) ▶ Postgres ▶ Grafana │
        └───────────────────────────────┬───────────────────────────────────┘
                                         │  sync contract (metrics + sampled images)
                                         ▼
        ┌──────────────────────── GCP (analytics/ML) ───────────────────────┐
        │ GCS (sampled images) ▶ BigQuery (metrics) ▶ Looker Studio          │
        │                         └▶ Vertex AI (classification — planned)     │
        └────────────────────────────────────────────────────────────────────┘
```

## Why hybrid

- **Green-pixel heuristic** is fast, cheap, and must work offline — lives on the local k3s cluster.
- **ML training/classification** is occasional and tooling-heavy — lives in GCP (Vertex AI).
- **Full image history** is large and rarely needs the cloud — stays in local MinIO.
- **Metrics + a sampled image subset** are small and valuable for long-horizon analytics — pushed to GCP.

The boundary is the design, not a hedge. Each tier does the work it's best suited for.

## How it works

1. **Capture**: A Raspberry Pi takes a photo on a cron schedule, writes it to a NAS landing zone over NFS.
2. **Ingest**: A k3s CronJob mirrors the landing zone into MinIO (`garden-images` bucket), preserving the `YYYY/MM/DD/HHMMSS.jpg` key.
3. **Analyze**: MinIO bucket notifications trigger the analyzer service, which computes a green-pixel health ratio and writes the result to Postgres.
4. **Sync**: Every metric row is pushed to BigQuery. Images matching the sampling policy (daily solar-noon capture + significant ratio changes) are copied to GCS.
5. **Dashboard**: Grafana on the local cluster shows real-time health trends. Looker Studio on BigQuery provides long-horizon analytics.

## Sync contract

The local tier is authoritative. It pushes to GCP; GCP never writes back.

| Stream | Scope | Target |
|--------|-------|--------|
| Metrics | Every capture | BigQuery `plant_metrics` |
| Images | Sampled subset only | GCS (same `YYYY/MM/DD/HHMMSS.jpg` key) |

The push is best-effort and async — if GCP is unreachable, the local tier keeps working and retries later.

## Infrastructure

### Local (k3s home lab)

- 3x Intel NUC7i7BNH (32GB RAM each), running k3s
- Synology DS218+ NAS for NFS-backed MinIO storage and Docker registry
- ArgoCD (GitOps), External Secrets Operator (1Password), Longhorn (block storage)
- MetalLB + Traefik ingress with wildcard TLS

### Cloud (GCP)

- GCS bucket for sampled images
- BigQuery dataset for metrics (partitioned by capture date)
- Looker Studio dashboard
- Least-privilege service account for the local-to-cloud push
- Vertex AI classification (planned)

### Capture node (Raspberry Pi)

- Raspberry Pi Model A+ v1, Naturebytes Wildlife Camera Kit
- Capture-only role — takes a photo and writes it to the NAS

## Project structure

```
.
├── pi/                         # Capture node
│   ├── capture.py
│   ├── requirements.txt
│   └── crontab.example
├── local/                      # k3s tier
│   ├── analyzer/               # Green-pixel analysis service
│   │   ├── main.py             # HTTP server (webhook + health)
│   │   ├── analysis.py         # Pure functions, no I/O
│   │   ├── sync.py             # Metrics → BQ, sampled images → GCS
│   │   ├── requirements.txt
│   │   └── tests/
│   ├── terraform/              # Bootstrap: namespace + ArgoCD Application
│   └── manifests/              # K8s workloads (ArgoCD syncs from here)
├── cloud/                      # GCP tier
│   └── terraform/              # GCS, BigQuery, IAM
├── .env.example                # All deployment-specific values
├── CLAUDE.md                   # AI assistant context
├── PLAN-local.md               # k3s build plan
└── PLAN-cloud.md               # GCP build plan
```

## Getting started

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env with your values (IPs, GCP project, domain, etc.)
```

### 2. Provision GCP resources

```bash
# Create the Terraform state bucket first
gcloud storage buckets create gs://$TFSTATE_BUCKET \
  --project=$GCP_PROJECT --location=$GCP_REGION --uniform-bucket-level-access

cd cloud/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars
terraform init -backend-config="bucket=$TFSTATE_BUCKET" -backend-config="prefix=$TFSTATE_PREFIX"
terraform apply
```

### 3. Bootstrap the local cluster

```bash
cd local/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars
terraform init
terraform apply    # Creates namespace + ArgoCD Application
```

ArgoCD auto-syncs `local/manifests/` from there. Update `CHANGE_ME_*` placeholders in the manifests before the first sync.

### 4. Build and push the analyzer image

```bash
docker build -t $DOCKER_REGISTRY/garden-analyzer:latest local/analyzer/
docker push $DOCKER_REGISTRY/garden-analyzer:latest
```

### 5. Set up the Pi

```bash
# On the Pi, mount the NAS landing zone and install the capture script
cd pi && python capture.py    # manual test
```

## Stack

| Component | Technology |
|-----------|-----------|
| Capture | Raspberry Pi, Python, `rpicam-still` |
| Object storage | MinIO (S3-compatible) on NAS via NFS |
| Analysis | Python (NumPy/Pillow), green-pixel heuristic |
| Metrics DB | PostgreSQL (Longhorn PVC) |
| Dashboard (local) | Grafana |
| Dashboard (cloud) | Looker Studio |
| Analytics DB | BigQuery |
| Image store (cloud) | Google Cloud Storage |
| ML (planned) | Vertex AI AutoML |
| Orchestration | k3s, ArgoCD, Terraform |
| Secrets | External Secrets Operator + 1Password |
| Networking | MetalLB, Traefik, cert-manager |
