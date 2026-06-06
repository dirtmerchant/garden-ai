# PLAN.md — Build Sequence

Six Claude Code sessions. Each is independently runnable and ends in a working, committed increment. Read `CLAUDE.md` first for project facts and conventions.

## Prerequisites (one-time, before Session 1)
- `gcloud` authenticated against project `garden-ai-467116`.
- Required APIs enabled: Cloud Storage, Cloud Functions, Eventarc, Cloud Run, BigQuery, Cloud Build.
- Terraform state bucket created: `garden-ai-467116-tfstate`.

## Session 1 — Scaffold + Terraform provisioning
- Create the repo layout from `CLAUDE.md`.
- Write Terraform for: image bucket (`garden-monitor-images`), function-source bucket, BigQuery dataset `garden_monitor` + table `plant_metrics` (schema in `CLAUDE.md`, partitioned by `DATE(capture_time)`), and a service account with least-privilege IAM.
- Configure the GCS state backend in `backend.tf`.
- **Done when**: `terraform init && terraform apply` provisions everything cleanly and `terraform plan` is then empty.

## Session 2 — Pi capture script
- `pi/capture.py`: capture an image, name it by the `YYYY/MM/DD/HHMMSS.jpg` UTC convention, upload to the image bucket.
- Auth via service-account key or workload identity; document which in the script header.
- `crontab.example` for the capture interval; `requirements.txt` pinned.
- **Done when**: running the script locally uploads a correctly-keyed object to the bucket.

## Session 3 — Cloud Function (analysis)
- `function/main.py`: Gen 2 function, GCS-finalize entry point.
- Isolate pure green-pixel logic from GCS/BigQuery I/O (testability).
- Parse `capture_time` from the object key; compute `green_pixel_ratio` with Pillow; insert a row into `plant_metrics`.
- **Done when**: invoking the function against a sample image inserts a correct BigQuery row.

## Session 4 — Terraform trigger wiring
- Add the Gen 2 Cloud Function resource + its Eventarc GCS-finalize trigger to Terraform, sourced from the function-source bucket.
- **Done when**: uploading an image to the bucket end-to-end produces a new BigQuery row, all via `terraform apply` (no console steps).

## Session 5 — pytest unit tests
- `function/tests/test_analysis.py`: cover the pure analysis logic (known images → expected ratios, edge cases: all-green, no-green, empty/corrupt).
- Mock GCS/BigQuery so tests run offline.
- **Done when**: `pytest` passes and analysis logic has meaningful coverage.

## Session 6 — README
- Concise, portfolio-oriented `README.md`: architecture diagram, component responsibilities, setup/deploy steps, cost note, and the heuristic-vs-ML framing.
- **Done when**: a reader can understand and reproduce the system from the README alone.

## Out of scope (future)
- Looker Studio dashboard (manual UI step).
- Vertex AI classification (see `CLAUDE.md` notes).
- Automated irrigation decisions.
