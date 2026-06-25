# PLAN-cloud.md — GCP Analytics / ML Tier

Additive analytics and heavy-ML tier. Receives a metrics stream and a sampled image subset from the local tier (never writes back). Read `CLAUDE.md` first — especially the sync contract, which this tier consumes.

Build **after** the local tier is working — except Session C1, which must exist before local Session L6 (the analyzer needs the service account and targets to push to).

## Prerequisites (one-time, before Session C1)

- `gcloud` authenticated against project `<GCP_PROJECT>`.
- APIs enabled: Cloud Storage, BigQuery, and (for the stretch goal) Vertex AI.
- Terraform state bucket created:
  ```bash
  gcloud storage buckets create gs://<GCP_PROJECT>-tfstate \
    --project=<GCP_PROJECT> \
    --location=us-central1 \
    --uniform-bucket-level-access
  ```

## Session C1 — Provision the push targets (do this before local L5)
- Terraform in `cloud/terraform/`: GCS bucket `garden-monitor-images`; BigQuery dataset `garden_monitor` + table `plant_metrics` (schema in CLAUDE.md, partitioned by `DATE(capture_time)`); a least-privilege service account the local analyzer authenticates as (object create on the bucket, insert on the table — nothing more).
- GCS state backend in `backend.tf`.
- **Done when**: `terraform apply` is clean, `terraform plan` is then empty, and the service-account key/identity is available to the local analyzer.

## Session C2 — Verify the ingest path
- With local L5 pushing, confirm rows land in BigQuery and sampled images land in GCS with matching `image_key`.
- Sanity query: row counts, ratio over time, % of rows with `synced_to_gcs = true`.
- **Done when**: a join of BigQuery rows to GCS objects by key is consistent for synced captures.

## Session C3 — Looker Studio dashboard (manual UI)
- Connect Looker Studio to BigQuery `plant_metrics`. Long-horizon views: trend over weeks/months, seasonal comparison — the analytics the local Grafana isn't meant for.
- **Done when**: the dashboard renders the historical trend from BigQuery.

## Session C4 — README (whole system)
- Top-level `README.md`: the hybrid architecture diagram, the edge-compute-with-cloud-burst rationale, the sync contract summary, setup/deploy for both tiers, and the heuristic-vs-ML framing.
- **Done when**: a reader understands why the boundary sits where it does and can reproduce both tiers.

## Stretch — Vertex AI classification
- Use the accumulated sampled images (transition-biased by the sampling policy) as training data; build the dataset CSV from GCS keys + labels.
- Prefer Vertex AI Pipelines for a reproducible train→evaluate→deploy flow.
- Feed predictions back as an additional metric column (extend the contract deliberately if so).
- See CLAUDE.md Vertex notes re: platform reorg, few-shot, and the KServe-on-k3s alternative.
