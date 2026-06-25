# Camera Module Selection

## Why the Naturebytes Wildlife Cam Kit

The capture node for this project is a [Naturebytes Wildlife Cam Kit](https://shop.naturebytes.org/products/wildlife-cam-kit) — a Raspberry Pi-based wildlife camera designed by UK conservationists, technologists, and educators. It's the only IP-certified Raspberry Pi camera enclosure I'm aware of, which matters for a plant-monitoring system that lives outdoors indefinitely.

The kit was chosen over a bare Pi + camera + generic enclosure for three reasons:

1. **IP55-rated weatherproof enclosure.** Triangulated acrylic construction, tested against sustained rain without leakage. A bare Pi in a food container is a weekend project; this is a deployment.
2. **Integrated PIR + Fresnel lens.** Not used in this project (captures are cron-scheduled, not motion-triggered), but the hardware is wired and available if the capture strategy changes.
3. **Purpose-built camera mount.** The camera module seats at the lens opening with a clear protective cover, aligned to the enclosure's viewing window. No 3D-printed brackets or hot glue.

The trade-off is the Pi Model A+ v1 bundled with the kit — a single-core ARMv6 with 512MB RAM, which constrains the capture node to a write-and-ship role. That constraint is fine here: all analysis runs on the k3s cluster, not the Pi.

### Raspberry Pi Foundation endorsement

> "Naturebytes have made the best Pi camera we've come across"
> — Raspberry Pi Foundation

The kit received a 4/5 in the [Raspberry Pi Official Magazine review](https://magazine.raspberrypi.com/articles/wildlife-cam-kit-review).

## Camera module: OmniVision OV5647

The kit includes a 5MP camera module based on the OmniVision OV5647 CMOS sensor, connected via the Pi's CSI (Camera Serial Interface) ribbon cable. This is the same sensor used in the original Raspberry Pi Camera Module v1 — well-documented, widely supported, and compatible with `rpicam-still` on Raspberry Pi OS Bookworm.

### Sensor specifications

| Parameter | Value |
|-----------|-------|
| Sensor | OmniVision OV5647 Color CMOS |
| Format | 1/4" (3.67 x 2.74 mm) |
| Resolution | 2592 x 1944 (5 megapixels) |
| Pixel size | 1.4 x 1.4 µm |
| Focal length | 3.6 mm (35mm equivalent: ~35mm) |
| Aperture | f/2.9 |
| Field of view | 54° x 41° (diagonal ~65°) |
| Focus | Fixed, 1m to infinity |
| Video | 1080p30, 720p60, VGA 90fps (H.264) |
| Interface | 15-pin CSI ribbon cable (15cm included) |
| Board size | 25 x 24 mm |
| Weight | 6g |

### Adequacy for this project

The OV5647 is more than sufficient for the green-pixel-ratio heuristic, which operates on color channel ratios rather than fine spatial detail. At 5MP, the images provide enough resolution for both the heuristic and future Vertex AI classification.

**Color calibration caveat.** The OV5647's auto white balance and the enclosure's clear protective lens cover may introduce color shifts compared to a lab-calibrated camera. For the green-pixel heuristic (which uses relative channel dominance, not absolute color values), this is acceptable. If Vertex AI classification comes online, the training data will come from this same sensor, so the model learns the sensor's characteristics implicitly. Cross-camera generalization would require calibration — but that's a multi-camera problem for later.

## Kit contents

| Component | Notes |
|-----------|-------|
| Raspberry Pi Model A+ v1 | Single-core ARMv6, 512MB RAM, 1x USB |
| Pre-loaded SD card | Custom Raspbian with camera/PIR test tools |
| OV5647 5MP camera module | CSI ribbon cable, clear protective cover |
| PIR motion sensor | Fresnel IR lens, wired to GPIO (unused in this project) |
| IP55 weatherproof enclosure | Green acrylic, hinged clips, padlock loop |
| Universal electronics mount | Compatible with Pi A+, B+, Zero, 2, 3, 4 |
| USB flash drive | For photo storage (not used — writing to NAS instead) |
| Nylon camera strap | Tree/post mounting |
| Hardware | Screws, inserts, nuts, jumper wires |

**Not included:** Power supply (5V 2.5A+ micro-USB), USB WiFi dongle (needed for Model A+ which has no onboard networking).

## Physical assembly

Assembly follows the [Naturebytes v4.5 guide](https://naturebytes.org/wildlife-cam-kit-resources/) (no soldering required):

1. **Camera ribbon to Pi CSI port** — connect first, before mounting. Watch contact orientation (most common assembly mistake).
2. **Mount Pi on electronics mount** — included screws, inserts, and nuts. The universal mount accepts multiple Pi form factors.
3. **Seat camera at lens opening** — the module clicks into a purpose-cut slot aligned with the enclosure's viewing window. Clear protective cover sits in front.
4. **Connect PIR jumper wires** — three wires to GPIO. Physically wired even though this project uses cron-scheduled captures, not motion triggers.
5. **Mount assembly into enclosure** — route power cable through rear cable access port.
6. **Close hinged clips** — confirm camera is square to the opening before fully tightening. The clips are tight and durable.

## Power

- Input: 5V at 2–2.5A via micro-USB
- The kit is designed for portable use with a LiPo battery pack (the Raspberry Pi Magazine review measured ~3 days runtime on an Anker PowerCore 10000)
- For this project: wall-powered via a weatherproof outdoor micro-USB cable — the plant isn't going anywhere, and neither is the camera

## Software

The kit ships with a custom Raspbian image that includes PIR and camera test scripts. This project replaces all of that with a minimal `capture.py` script running on Raspberry Pi OS Lite (Bookworm, 32-bit for ARMv6 compatibility):

- `rpicam-still` for image capture (Bookworm-era replacement for `raspistill`)
- Cron-scheduled captures, not PIR-triggered
- Images written directly to a NAS landing zone over NFS
- No processing on the Pi — the 512MB RAM and single-core CPU make this a capture-and-ship node

## Ingestion path

```
Pi (capture + key) ──▶ NAS landing zone (NFS) ──▶ k3s CronJob ──▶ MinIO
```

- Image key convention `YYYY/MM/DD/HHMMSS.jpg` (UTC) is set at capture time on the Pi
- Key survives the hop through the NAS into MinIO and GCS for clean cross-tier joins
- NAS is a transient staging buffer; MinIO is authoritative
- Landing zone is cleared after ingest
