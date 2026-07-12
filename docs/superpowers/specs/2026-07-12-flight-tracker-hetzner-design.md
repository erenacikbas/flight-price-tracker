# Flight Price Tracker on Hetzner — Design

**Date:** 2026-07-12
**Status:** Approved (design), pending implementation plan
**Target cluster:** `hetzner-personal` (kubectl context)

## Goal

Log flight prices for configured routes every 15 minutes and serve a live Grafana
dashboard, self-hosted on the `hetzner-personal` Kubernetes cluster. Replaces the
prior GitHub-Actions + CSV + GitHub-Pages/Chart.js implementation.

## Context (existing state)

- Working assets to reuse/adapt: `logger.py` (written for the fast-flights 3.x API),
  `routes.json` (currently one route: IST→DPS one-way, 2026-10-26, EUR economy),
  `data/prices.csv` (real history, 2026-07-08 → 2026-07-12).
- To be replaced: `.github/workflows/track.yml` (Actions ran the logger + committed CSV),
  `index.html` (Chart.js dashboard), CSV-as-store.
- Cluster conventions discovered:
  - **GitOps via Flux** — single `GitRepository` `flux-system` →
    `ssh://git@github.com/waitline/waitline-infra.git` (branch `main`).
    Apps live under `./clusters/hetzner-personal/apps/`, reconciled by the `waitline`
    Kustomization with `prune: true` and **SOPS/age decryption** (`sops-age` secret).
  - **Ingress** via **Cloudflare Tunnel** (`cloudflared` deployment, 2 replicas).
  - **Storage**: only `local-path` (default) StorageClass — PVCs pin to a node's
    local disk, `WaitForFirstConsumer`, not replicated. Acceptable for a single-writer
    personal tracker.
  - **Images** from **GHCR** (`ghcr.io/...`); off-the-shelf images pulled directly.
  - `sops` + `age` installed locally; age key at `~/.config/sops/age/keys.txt`.

## Key decisions

| Decision | Choice |
|---|---|
| Deploy method | **GitOps via Flux** — manifests in `waitline-infra` under `clusters/hetzner-personal/apps/flight-tracker/` |
| Storage engine | **InfluxDB 2.x OSS** |
| Grafana exposure | **Cloudflare Tunnel + Cloudflare Access** at `flights.<domain>` |
| Logger image | Built to **GHCR** (recommend **public** image → no pull secret) |
| Fetch library | **`fast-flights==3.0.2`** (pinned) + parser guard patch |
| Fetch mode | Default HTTP (`primp`) — pending cluster-IP verification |

## Architecture

```
Flux (waitline-infra repo)  ──reconciles──►  clusters/hetzner-personal/apps/flight-tracker/
                                                   │
   CronJob */15  ──►  logger (GHCR image)  ──writes──►  InfluxDB 2.x  ──datasource──►  Grafana
   fast-flights → Google Flights (EUR)                  (PVC, local-path)              │
                                                                          Cloudflare Tunnel + Access
                                                                                       │
                                                                              flights.<domain>
```

## Component 1 — The fetch (highest-risk, de-risk first)

**Problem found:** `requirements.txt` pins `fast-flights>=2.2`, which now resolves to
**3.0.2**. Its HTTP fetch works (returns ~2 MB of valid Google Flights HTML), but its
parser crashes on an unguarded index — `price = k[1][0][1]` in `parser.py` `parse_js()` —
because Google's embedded JSON layout shifted so some itinerary entries have no price in
that slot. Result: `logger.py` currently produces **zero rows**. (2.2 parses fine but uses
a different API and returns geolocated string prices, e.g. `TRY 24518`, not clean EUR ints.)

**Fix:** pin `fast-flights==3.0.2` and apply a one-line guard in the parse loop:

```python
for k in payload[3][0]:
    flight = k[0]
    if not k[1] or not k[1][0]:   # guard: skip itineraries with no price in this slot
        continue
    price = k[1][0][1]
```

Applied as a commented, reproducible patch step in the Docker build (deterministic because
the version is pinned). Verified locally: returns clean **EUR integer** prices
(e.g. 478 / 593 / 638 EUR, matching the seeded CSV range) using default HTTP mode — **no
headless browser / chromium needed**. Documented as temporary; unpin if fixed upstream.

**Cluster-IP verification (Step 1, gates everything):** Google Flights geolocates by
egress IP — an unconfigured query from a Turkey IP returned `TRY`, not `EUR`. So local
success does not prove cluster success. Before building any InfluxDB/Grafana, run a
throwaway pod on `hetzner-personal` that executes the exact fetch and prints
**price + currency + egress IP**:

- ✅ returns EUR and is not bot-challenged → proceed with the small HTTP-only image.
- ⚠️ wrong currency or bot-blocked → switch the image to a `fetch_mode="fallback"`
  (Playwright + chromium) variant and/or route through a proxy. The Dockerfile is
  structured so this is a one-line switch.

**Failure semantics:** the logger treats **0 parsed rows for a route that returned HTML as
a hard failure** (non-zero exit) so a future Google layout change surfaces as a red CronJob
run instead of silently writing nothing. Transient network errors keep the existing retry
(3 attempts, backoff).

## Component 2 — Logger (`logger.py`)

Adapt the existing 3.x logger:

- Keep `routes.json` config and retry logic.
- Enforce `currency=EUR` (from config) in the query.
- **Write to InfluxDB** (via `influxdb-client`) instead of appending CSV.
- Read InfluxDB connection (URL, token, org, bucket) from env vars, injected from the
  SOPS-managed secret.
- **One-time backfill script** imports the existing `data/prices.csv` rows into InfluxDB so
  the dashboard opens with real history rather than a blank chart. Idempotent (safe to
  re-run — InfluxDB dedupes on identical timestamp+tags).

## Component 3 — InfluxDB data model

- Measurement: **`flight_price`**
- **Tags** (low cardinality, used for filtering/grouping): `route_id`, `origin`,
  `destination`, `trip`, `currency`, `price_level` (Google's low/typical/high indicator,
  free from the library).
- **Fields**: `price` (int, EUR), `num_options` (int), `cheapest_airline` (string),
  `days_to_departure` (int).
- Timestamp = fetch time. Bucket retention: long/infinite (data volume is tiny — a handful
  of points per 15 min).

## Component 4 — Kubernetes resources

All under `clusters/hetzner-personal/apps/flight-tracker/`:

- **InfluxDB 2.x**: Deployment + PVC (`local-path`) + Service. Bootstrap org/bucket/admin
  token + operator token via env from a **SOPS secret**. Single replica (single writer).
- **Grafana**: Deployment + PVC + Service. **Datasource and dashboard provisioned via
  ConfigMaps** (reproducible, no click-ops). Admin credentials via **SOPS secret**.
  Dashboard v1 panels: price-over-time per route; current vs min / median / max; days to
  departure; latest-snapshot table.
- **CronJob** `*/15 * * * *`: `concurrencyPolicy: Forbid`, small `backoffLimit`,
  `restartPolicy: Never`, resource requests/limits, image
  `ghcr.io/<owner>/flight-tracker-logger:<tag>`. Reads InfluxDB creds from the SOPS secret.
- **Namespace**: dedicated `flight-tracker` namespace.
- **Exposure**: add a `flights.<domain>` route to the Cloudflare Tunnel → Grafana Service,
  gated by Cloudflare Access.

## Component 5 — Image build (CI)

Replace `.github/workflows/track.yml` with a workflow that **builds and pushes the logger
image to GHCR** on push (tagged by commit SHA and/or timestamp, matching cluster
convention). The 15-minute schedule now lives in the cluster CronJob, not in GitHub Actions.
This project directory becomes its own git repo / GitHub repo to host the image build.

## Scope (YAGNI)

**In v1:** fetch → InfluxDB → Grafana dashboard; GitOps deploy via Flux; Cloudflare Tunnel
exposure; CSV history backfill.

**Deferred (fast-follows):**

- **Buy / Good / Hold / Wait recommendation** — the prior dashboard's timing logic. Harder
  to express in Grafana; revisit once data flows.
- **Grafana price-drop alert** — high-value and native to Grafana (e.g. new all-time low, or
  price ≤ threshold). Easy to add once the pipeline is live.

## Dependencies / open items (resolved during implementation)

1. **Clone access** to `github.com/waitline/waitline-infra` (SSH) and confirmation of the
   app path `clusters/hetzner-personal/apps/flight-tracker/`.
2. The **`.sops.yaml`** recipient(s) in that repo (age public key) for encrypting the
   InfluxDB/Grafana secrets.
3. The **Grafana hostname** (`flights.<domain>`) and how the Cloudflare Tunnel is managed —
   CF dashboard (user adds the route) vs a config file/secret in the cluster.
4. The **GHCR owner/org** for the image and confirmation a **public** image is acceptable.

## Verification strategy

- **Gate 1 (fetch):** throwaway pod on `hetzner-personal` returns clean EUR price — before
  building the stack.
- **Gate 2 (write path):** one CronJob run (manually triggered) writes points visible in
  InfluxDB.
- **Gate 3 (dashboard):** Grafana renders the backfilled history + new points.
- **Gate 4 (exposure):** `flights.<domain>` loads behind Cloudflare Access.
