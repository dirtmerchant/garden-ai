# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Garden Plant Health Monitor — a hybrid plant-health monitoring system. Operating instructions, durable context, and conventions. The two tiers have their own build plans: `PLAN-local.md` (k3s core) and `PLAN-cloud.md` (GCP analytics/ML). The boundary between them is defined in "Sync contract" below — both tiers depend on it, neither tier owns it.

## What this is

A hybrid plant-health monitoring system. The **k3s home lab** is the operational core: capture, real-time heuristic analysis, full image history, live dashboard — runs free and works offline. **GCP** is the analytics and heavy-ML tier: long-horizon analysis in BigQuery and image classification via Vertex AI, fed by a deliberate sampled stream from the local tier.

This is also a portfolio piece. The story is the architecture itself: edge compute with cloud burst for ML and analytics — local does the constant/cheap/latency-sensitive work, cloud does the occasional/expensive/bursty work. Keep code and docs concise and technically precise.

## Why hybrid (design rationale — don't relitigate while building)

- Green-pixel heuristic is fast, cheap, and must work offline → lives local.
- ML training/classification is occasional and tooling-heavy → lives in GCP (Vertex).
- Full image history is large and rarely needs the cloud → stays in local MinIO.
- Metrics + a sampled image subset are small and valuable for analytics → pushed to GCP.
- The boundary is the design, not a hedge. Don't duplicate the same workload across tiers.

## Tiers at a glance

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

## Project facts

### k3s home lab

#### Hardware
- 3× Intel NUC7i7BNH, 32GB RAM / 256GB SSD each (96GB / 768GB total), Ubuntu 24.04.4 LTS.
- k3s v1.34.3+k3s1. nuc1 (192.168.1.20) is server (control-plane + etcd); nuc2 (.21) and nuc3 (.22) are agents.
- Synology DS218+ NAS (192.168.1.10): 6GB RAM, ~11TB RAID 1 + 15TB USB backup. Provides NFS-backed storage for MinIO (garden image history) and runs the **Docker Registry** (`192.168.1.10:5000`) for container images.

#### Network
- Flat LAN 192.168.1.0/24. Gateway/DHCP: Google Fiber router at .1.
- **MetalLB** L2 load balancer, IP pool 192.168.1.200–250.
- **Traefik** ingress (192.168.1.202) with wildcard TLS cert for `*.homelab.bertbullough.com` (self-signed CA via cert-manager).
- **Pi-hole** DNS at 192.168.1.200 with custom dnsmasq records for `*.homelab.bertbullough.com`.
- **Tailscale** subnet router advertises 192.168.1.0/24 for remote access.
- UFW on all nodes; SSH key-only auth.

#### Storage
- **Longhorn** is the default StorageClass (3× replica distributed block storage). Used for Postgres PVC.
- **local-path** also available (node-pinned, no replication) — used by some existing services.
- **Synology NAS** (192.168.1.10) via NFS for MinIO image storage — ~11TB RAID 1 capacity. NFS PV created by Terraform; PVC binds to it. See PLAN-local.md for NFS share setup.

#### GitOps & secrets
- **ArgoCD** with app-of-apps pattern, auto-syncs from `main` branch. Pruning + self-heal enabled, sync waves for ordering.
- **External Secrets Operator (ESO)** with 1Password SDK provider — no secrets in the repo. Garden bot secrets (MinIO creds, Postgres password, GCP SA key) should follow this pattern.

#### Existing workloads (coexist with garden bot)
| Service | Node affinity | Resources (request → limit) | PVC |
|---------|---------------|----------------------------|-----|
| ArgoCD | none | 200m/448Mi → 1/1.5Gi | — |
| Prometheus | nuc1 (local-path) | 200m/512Mi → 1/2Gi | 20Gi |
| Grafana | none | 100m/128Mi → 300m/256Mi | — |
| Ollama | nuc2 (local-path) | 1/3Gi → 4/6Gi | 20Gi |
| Home Assistant | nuc3 (local-path) | 200m/256Mi → 1/1Gi | 10Gi |
| Pi-hole | nuc3 (local-path) | 100m/128Mi → 300m/256Mi | 1.5Gi |
| Traefik | none | 100m/128Mi → 300m/256Mi | — |
| Tailscale | none | 50m/64Mi → 200m/128Mi | — |

Substantial headroom remains for garden bot services (MinIO, Postgres, analyzer, Grafana).

#### Garden bot services (to deploy)

- Object store: **MinIO** (S3-compatible), bucket `garden-images`.
- Metrics DB: **Postgres**, database `garden`, table `plant_metrics`.
- Dashboard: **Grafana** (dedicated instance in `garden` namespace).
- Analyzer: small Python service, MinIO bucket-notification driven.
- IaC: Terraform bootstraps namespace + ArgoCD Application; ArgoCD syncs workload manifests. See PLAN-local.md.

### GCP
- Project ID: `garden-ai-467116`
- Project number: `563978501450`
- Region: `us-central1`
- GCS bucket (sampled images): `garden-monitor-images`
- BigQuery dataset: `garden_monitor`, table: `plant_metrics`
- Looker Studio on BigQuery (manual UI step).
- Vertex AI classification — planned stretch goal (notes at bottom).
- Cost target: a few dollars/month; the local tier carries the bulk of storage/compute.

## Sync contract (the boundary — single source of truth)

The local tier is authoritative. It pushes to GCP; GCP never writes back. Two streams cross the boundary:

1. **Metrics (every capture).** Small JSON rows, pushed to BigQuery `garden_monitor.plant_metrics`. This is cheap and complete — every capture's metrics go up.
2. **Sampled images (subset only).** Only images selected by the sampling policy are copied to GCS `garden-monitor-images`. Full-resolution history stays in local MinIO.

### Sampling policy (initial)
- One image per day (the local solar-noon capture), **plus**
- Any image whose `green_pixel_ratio` changes by more than a configurable threshold vs. the prior reading (captures interesting transitions for future ML training).
- Policy lives in the local analyzer; tune via config, not code.

### Shared object key convention
`YYYY/MM/DD/HHMMSS.jpg` (UTC) in **both** MinIO and GCS. A synced image has the same key in both stores, so the metrics row's `image_key` joins across tiers unambiguously.

### Metric row schema (identical in Postgres and BigQuery)
| Column            | Type      | Notes                                            |
|-------------------|-----------|--------------------------------------------------|
| capture_time      | TIMESTAMP | Parsed from the object key (UTC).                |
| ingest_time       | TIMESTAMP | When the analyzer processed the image.           |
| image_key         | STRING    | `YYYY/MM/DD/HHMMSS.jpg`; joins MinIO↔GCS.        |
| green_pixel_ratio | FLOAT     | Heuristic health metric, 0.0–1.0.                |
| image_width       | INTEGER   |                                                  |
| image_height      | INTEGER   |                                                  |
| synced_to_gcs     | BOOLEAN   | Whether the image (not just the row) was pushed. |
| device_id         | STRING    | Future multi-camera support.                     |

In BigQuery, partition by `DATE(capture_time)`. In Postgres, index on `capture_time`.

### Failure behavior
- The push to GCP is **best-effort and asynchronous**. If GCP is unreachable, the local tier keeps working; unsynced rows/images are retried. Local correctness never depends on the cloud being up.

## Conventions

### Repository layout
```
.
├── CLAUDE.md
├── PLAN-local.md              # k3s tier build plan
├── PLAN-cloud.md              # GCP tier build plan
├── README.md
├── pi/
│   ├── capture.py
│   ├── requirements.txt
│   └── crontab.example
├── local/                      # k3s tier
│   ├── analyzer/               # green-pixel service + sampling + sync
│   │   ├── main.py
│   │   ├── analysis.py         # pure functions, no I/O
│   │   ├── sync.py             # metrics→BQ, sampled images→GCS
│   │   ├── requirements.txt
│   │   └── tests/test_analysis.py
│   ├── terraform/              # bootstrap: namespace + ArgoCD Application (run once)
│   └── manifests/              # k8s workloads: ArgoCD syncs from here
└── cloud/                      # GCP tier
    └── terraform/
        ├── main.tf             # GCS bucket, BQ dataset+table, IAM/SA for push
        ├── variables.tf
        ├── outputs.tf
        ├── backend.tf          # GCS backend
        └── terraform.tfvars.example
```

### Runtimes & versions
- Pi capture: Python 3.11+.
- Analyzer: Python 3.12. Keep `analysis.py` pure (no MinIO/Postgres/cloud imports) so tests run offline.
- Pin all dependencies.

### GCP Terraform
- State backend: GCS, bucket `garden-ai-467116-tfstate`, prefix `garden-monitor`. Create the state bucket once before `terraform init`.
- Provisions only the cloud tier: GCS bucket, BigQuery dataset+table, and a least-privilege service account the local analyzer authenticates as to push.

### Local deployment (Terraform + ArgoCD)

- **Container registry**: Docker Registry on the Synology NAS at `192.168.1.10:5000`. k3s nodes configured via `/etc/rancher/k3s/registries.yaml` to allow this as an HTTP (non-TLS) registry. Push analyzer images here.
- **Terraform** (`local/terraform/`) bootstraps the platform: creates the `garden` namespace, an NFS PersistentVolume for MinIO (backed by the Synology NAS), an ArgoCD repo credential for this repo, and an ArgoCD `Application` resource pointing to `local/manifests/`. Run once with `terraform apply`. State is local.
- **ArgoCD** syncs `local/manifests/` — all application workloads (deployments, services, PVCs, ExternalSecrets, IngressRoutes, NetworkPolicies). Automated sync with prune + self-heal.
- Secrets via External Secrets Operator (1Password `Homelab` vault, `ClusterSecretStore` named `onepassword`).
- MinIO storage: NFS PV backed by Synology NAS. Postgres: Longhorn PVC (replicated SSD). Traefik IngressRoutes for dashboard access.
- No changes to the homelab repo required.

## Common commands

### Tests (analyzer)

```bash
cd local/analyzer && python -m pytest tests/              # all tests
cd local/analyzer && python -m pytest tests/test_analysis.py  # single file
cd local/analyzer && python -m pytest tests/test_analysis.py::test_name -v  # single test
```

`analysis.py` is pure (no I/O imports), so tests run offline without MinIO/Postgres/GCP.

### Terraform — GCP tier

```bash
cd cloud/terraform
terraform init          # first time, or after backend changes
terraform plan          # preview
terraform apply         # provision GCS, BigQuery, service account
```

State backend: GCS bucket `garden-ai-467116-tfstate`, prefix `garden-monitor`.

### Terraform — local tier (bootstrap)

```bash
cd local/terraform
terraform init
terraform plan
terraform apply         # creates namespace + ArgoCD Application (run once)
```

State is local. ArgoCD then syncs `local/manifests/` automatically.

### Pi capture (manual run)

```bash
cd pi && python capture.py
```

### Dependency management

All `requirements.txt` files pin exact versions. Install into a venv:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Vertex AI notes (field update, June 2026) — planned stretch goal, not initial build

- Platform reorg: Vertex AI is now under the Gemini Enterprise Agent Platform; verify current console/API layout before this phase (docs last updated May 2026).
- Core AutoML flow unchanged: dataset → import → train → evaluate → deploy endpoint → predict; training CSV points to GCS images with TRAINING/TEST/VALIDATION splits + labels. The sampled-image stream + shared key convention feed this directly.
- Prefer Vertex AI Pipelines + Pipeline Components over console clicks (fits IaC approach).
- Small, self-labeled dataset: few-shot (Siamese + triplet loss) can cut labeling ~90%; spatio-temporal modeling exploits the time-series. The sampling policy already biases toward capturing transitions, which helps here.
- Alternative considered: KServe/Seldon on k3s for fully-local serving. Vertex chosen for the cloud-ML portfolio signal; revisit if targeting platform/SRE roles specifically.
