

**Hardware: Naturebytes Wildlife Camera Kit assembly**

- Board: Raspberry Pi Model A+ v1 (single-core, 512MB RAM, single USB port, no onboard networking). USB WiFi dongle required (have plenty on hand).
- Role: capture node only — grab a still and ship it. No processing on the Pi.
- Camera: kit-included module (not an official Pi camera). Fine for green-pixel-ratio; note possible color-calibration inconsistency if/when Vertex AI classification comes online.
- PIR sensor: physically wired during assembly but unused in software. Captures are scheduled (cron/systemd timer), not PIR-triggered.

**Ingestion path**

- Pi → NAS (landing zone) → k3s cluster pulls and processes.
- Image key convention `YYYY/MM/DD/HHMMSS.jpg` (UTC) set at capture time on the Pi, so it survives the hop to NAS and into MinIO/GCS for clean cross-tier joins.
- Open decision (not yet resolved): NAS as transient staging buffer with MinIO authoritative, vs. NAS as authoritative store with MinIO dropped. Affects sync contract and join story.

**Physical assembly order** (authoritative source: Naturebytes V4.4 manual)

1. Connect camera ribbon to Pi CSI port first — watch contact orientation (most common mistake), do before mounting.
2. Mount Pi on the kit's universal electronics mount (included screws/inserts/nuts).
3. Seat camera in case front at lens opening; connect PIR jumper wires.
4. Mount assembly into enclosure; route power cable through rear cable access.
5. Close hinged clips; confirm camera is square to opening before fully tightening.

Power: external 5V 2–3A (2.5A+ ideal) via USB-to-Micro-USB (not included in kit).
