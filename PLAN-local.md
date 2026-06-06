# PLAN-local.md — k3s Core Tier

The operational core: capture → MinIO → analyzer (green-pixel + sampling + sync) → Postgres → Grafana. Runs free, works offline, is the source of truth. Read `CLAUDE.md` first — especially the sync contract, which this tier produces.

Build this tier **first**. It is a complete, useful system on its own; the cloud tier is additive.

## Prerequisites (one-time)
- k3s cluster reachable; `kubectl` context set.
- A namespace, e.g. `garden`.
- Decide IaC style: Terraform (kubernetes + helm providers) vs. GitOps (Argo CD / Flux). Note the choice here once made.

## Session L1 — Cluster services (MinIO, Postgres, Grafana)
- Deploy MinIO (bucket `garden-images`), Postgres (db `garden`), Grafana via Helm/manifests under `local/manifests/` or `local/terraform/`.
- Create `plant_metrics` in Postgres (schema in CLAUDE.md), indexed on `capture_time`.
- Persistent volumes for MinIO and Postgres.
- **Done when**: all three are running, reachable in-cluster, and survive a pod restart with data intact.

## Session L2 — Pi capture script
- `pi/capture.py`: capture image, key it `YYYY/MM/DD/HHMMSS.jpg` (UTC), upload to MinIO via the S3 API.
- `crontab.example` for capture interval; pinned `requirements.txt`.
- **Done when**: running locally puts a correctly-keyed object in MinIO `garden-images`.

## Session L3 — Analyzer: analysis + persistence
- `local/analyzer/analysis.py`: pure green-pixel function(s), no I/O — unit-testable offline.
- `local/analyzer/main.py`: triggered by MinIO bucket notifications; parse `capture_time` from key, compute ratio, write a `plant_metrics` row to Postgres.
- **Done when**: an upload to MinIO results in a correct Postgres row, end to end in-cluster.

## Session L4 — Grafana dashboard
- Dashboard on Postgres: green_pixel_ratio over time, latest reading, daily trend.
- **Done when**: the dashboard reflects new captures live.

## Session L5 — Sampling + sync (produces the cloud tier's input)
- `local/analyzer/sync.py`: implement the sampling policy (CLAUDE.md) and the best-effort async push — metrics→BigQuery for every row, sampled images→GCS. Set `synced_to_gcs` accordingly; retry unsynced.
- Authenticate as the GCP service account from PLAN-cloud.md (must exist first; this is the one ordering dependency between tiers).
- **Done when**: every capture's metrics appear in BigQuery; only policy-selected images appear in GCS; GCP downtime doesn't break the local tier (unsynced items retried on recovery).

## Session L6 — Tests
- `local/analyzer/tests/test_analysis.py`: pure analysis logic (known images→ratios; edge cases: all-green, none, corrupt/empty) and the sampling decision logic (mock the threshold cases).
- Mock MinIO/Postgres/GCP so tests run offline.
- **Done when**: `pytest` passes with meaningful coverage of analysis and sampling.

## Out of scope here
- Anything cloud-side beyond the push target → PLAN-cloud.md.
