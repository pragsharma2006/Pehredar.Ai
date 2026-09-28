# Pehredar.ai — test report

Generated 2026-09-23 08:58 by `python test_report.py --live`. Every number below was measured by this script on this machine.

## ANPR — your anpr_best.pt + plate reader on the Anpr_system test photos

| Photo | Truth | Read | Valid | State | OCR conf | Body type (your model) | Plate ms | Body ms |
|---|---|---|---|---|---|---|---|---|
| _2026-03-25_at_1.40.15_AM_ | DL12CN1165 | DL12CN1165 | True | Delhi | 0.99 | SUV 0.88 | 408 | 1728 |
| _2026-03-25_at_1.40.15_AM. | KA09MF0986 | KA09MF0986 | True | Karnataka | 0.98 | sedan 0.88 | 398 | 1914 |
| _2026-03-25_at_1.40.16_AM_ | MH01DK1999 | MH01DK1999 | True | Maharashtra | 0.96 | sedan 0.72 | 1443 | 1906 |
| _2026-03-25_at_1.40.16_AM_ | GJ03MR9209 | GJ03MR9209 | True | Gujarat | 0.99 | compact 0.68 | 253 | 1468 |
| _2026-03-25_at_1.40.16_AM. | UP16BN2277 | UP16BN2277 | True | Uttar Pradesh | 0.99 | sedan 0.92 | 272 | 2010 |
| _2026-03-25_at_1.40.17_AM. | DL2CAT5494 | DL2CAT5494 | True | Delhi | 1.00 | sedan 0.94 | 238 | 1548 |
| _2026-03-27_at_11.03.00_PM | no plate | — | — | — | — | SUV 0.63 | 476 | 1005 |

**Exact plate reads: 7/7** (includes correctly reporting no plate on the toy car). Small hand-labelled set — not a general accuracy figure.

## ANPR — rendered Indian plates (generate_assets.py)

- plate image: **8/12** exact · misses: PB10XX4521→PB10XX452, PB08DK4410→PB08DK4416, RJ19GA2071→RJ19GA2077, WB24AK9121→WB24AK9122
- plate on vehicle sprite: **9/12** exact · misses: JK02CD1122→None, PB08DK4410→None, 22BH4567AA→None

## Recorded clips — real detections precomputed by generate_assets.py

| Clip | Model | Frames | Boxes | Tracks | Avg conf | ms/frame (offline) |
|---|---|---|---|---|---|---|
| car-detection | YOLOv8m (COCO) + ByteTrack | 377 | 93 | 6 | 0.719 | 202.0 |
| checkpost_anpr | YOLOv8m (COCO) + ByteTrack | 1080 | 1184 | 42 | 0.71 | 221.5 |
| face-demographics-walking | YOLOv8m (COCO) + ByteTrack | 732 | 534 | 7 | 0.908 | 193.3 |
| person-bicycle-car-detection | YOLOv8m (COCO) + ByteTrack | 647 | 425 | 8 | 0.778 | 201.0 |

Model choice: on the overhead road clip YOLOv8m found ~2x the vehicles YOLOv8n did (measured during build: 18 vs 8 cars on every 6th frame, higher confidence, no false 'bus'), so recorded clips are precomputed offline with YOLOv8m; live CAM-01 uses YOLOv8n to stay real-time on CPU.

## Live model speed (YOLOv8n, this machine, no other load)

- imgsz 640: 111 ms/frame (~9.0 fps), 41 person boxes on 60 frames, avg conf 0.85
- imgsz 480: 80 ms/frame (~12.5 fps), 35 person boxes on 60 frames, avg conf 0.82

## Night enhancement — real clip darkened to night levels

- 60 frames, mean brightness 16/255 (night threshold 55)
- person detections: raw **43** (avg conf 0.90) → after CLAHE+gamma **43** (avg conf 0.91)

## Face detection — YuNet on the recorded corridor clip

- 70 sampled frames: faces found in 28, 45 faces, avg score 0.90, avg quality 0.57, 60.2 ms/frame
- Watchlist matching uses real SFace embeddings of faces enrolled live (webcam or photo upload); the illustrated registry samples have no template and cannot match — so no match-accuracy number is claimed here.

## Live system (server running)

- device: CPU · Intel64 Family 6 Model 186 Stepping 2, GenuineIntel (2 threads) · cameras online 8/8

| Camera | Kind | Display fps | AI fps | AI ms | Analysis fps | People | Vehicles |
|---|---|---|---|---|---|---|---|
| CAM-01 | live | 29.4 | 8.3 | 61.0 | 8.3 | 0 | 0 |
| CAM-02 | recorded | 12.0 | — | — | 4.1 | 0 | 2 |
| CAM-03 | recorded | 12.5 | — | — | 4.4 | 0 | 0 |
| CAM-04 | synthetic | 11.8 | — | — | 4.1 | 3 | 0 |
| CAM-05 | synthetic | 12.1 | — | — | 4.3 | 1 | 0 |
| CAM-06 | recorded | 12.3 | — | — | 3.9 | 0 | 0 |
| CAM-07 | recorded | 11.9 | — | — | 4.0 | 1 | 0 |
| CAM-08 | synthetic | 11.8 | — | — | 4.0 | 2 | 1 |

(Measured with no browser attached; with the dashboard open in Chrome on the same laptop the build measured CAM-01 at ~21 fps capture and ~5 AI updates/s, every tile ~6 fps.)

**1374 events logged this session** — by type:

| Module | Event | Count |
|---|---|---|
| activity | Abandoned Object | 45 |
| activity | Crawling Near Fence | 50 |
| activity | Group Gathering | 27 |
| activity | Loitering | 300 |
| activity | Repeated Fence Passes | 54 |
| activity | Running | 56 |
| activity | Wrong-way Movement | 49 |
| anpr | Plate Read — Manual Review | 19 |
| anpr | Vehicle Plate Read | 63 |
| anpr | Watchlisted Vehicle Detected | 29 |
| face | Unregistered Person at Restricted Post | 196 |
| fence | Buffer Zone Entry | 100 |
| fence | Fence Breach | 98 |
| fence | Fence Breach (Night) | 92 |
| network | Bandwidth Adaptation | 82 |
| network | Camera Link Offline | 10 |
| network | Camera Link Restored | 9 |
| network | Metadata-only Mode | 14 |
| night | Night Movement Near Border | 39 |
| night | Unclassified Night Motion | 40 |
| vehicle | Vehicle Stopped Too Long | 2 |

- events with a real snapshot: 1374/1374
- ANPR (recent window): 40 vehicle jobs, 22 plates read, 16 valid, 6 watchlist hits, 0 manual review

## Integrity & tamper detection

- verify: ok=True · 1374/1374 events · 3 operator actions
- tamper 'record' on EVT-20260923-001354 → verify ok=False, failed at EVT-20260923-001354 (event record modified)
  - restore → verify ok=True
- tamper 'snapshot' on EVT-20260923-001355 → verify ok=False, failed at EVT-20260923-001355 (snapshot file altered or swapped)
  - restore → verify ok=True

- network: tiers now Counter({'HIGH': 5, 'MEDIUM': 2, 'METADATA': 1}); 115 network events (adaptation / metadata-only / offline / restored)
