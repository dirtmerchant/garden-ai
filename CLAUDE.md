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
- Cluster: 3× Intel NUC, 32GB RAM each (96GB total), k3s.
- Object store: **MinIO** (S3-compatible), bucket `garden-images`.
- Metrics DB: **Postgres**, database `garden`, table `plant_metrics`.
- Dashboard: **Grafana** on the live Postgres data.
- Analyzer: small Python service, MinIO bucket-notification driven.
- IaC/GitOps: Terraform (kubernetes + helm providers) or Argo CD/Flux — see PLAN-local.md.

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
├── PLAN-local.md
├── PLAN-cloud.md
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
│   ├── manifests/              # k8s: MinIO, Postgres, Grafana, analyzer
│   └── terraform/              # k8s + helm providers (or argocd/ dir if GitOps)
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

### Local Terraform / GitOps
- Provision MinIO, Postgres, Grafana, and the analyzer via Helm/manifests.
- Prefer a GitOps tool (Argo CD or Flux) if you want that on the portfolio; otherwise Terraform kubernetes+helm providers. Pick in PLAN-local.md.

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

### Terraform — local tier

```bash
cd local/terraform
terraform init
terraform plan
terraform apply         # provision MinIO, Postgres, Grafana, analyzer on k3s
```

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
