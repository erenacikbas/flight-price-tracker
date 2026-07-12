# Flight Price Tracker on Hetzner — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Log flight prices every 15 minutes into InfluxDB and serve a Grafana dashboard, self-hosted on the `hetzner-personal` Kubernetes cluster via Flux GitOps.

**Architecture:** A Python logger (packaged as a GHCR image) runs as a k8s CronJob every 15 minutes, scrapes Google Flights via `fast-flights`, and writes clean EUR prices to InfluxDB 2.x. Grafana (datasource + dashboard provisioned from ConfigMaps) reads InfluxDB and is exposed at `flights.<domain>` through the existing Cloudflare Tunnel. Manifests are authored/tested in this repo, then committed to `waitline-infra` for Flux to reconcile.

**Tech Stack:** Python 3.11, `fast-flights==3.0.2`, `influxdb-client`, InfluxDB 2.7, Grafana 11, Kubernetes, Kustomize, Flux, SOPS/age, Cloudflare Tunnel, GitHub Actions + GHCR.

## Global Constants (fill in at the task that first needs them)

These are user-supplied inputs, not placeholders to invent. Each task that first
needs one includes an explicit step to obtain it. Once known, use the exact value
everywhere it appears.

- `GHCR_OWNER` — GitHub org/user that owns the image (e.g. the owner used by other cluster images). Resolved in Task 7.
- `GRAFANA_HOST` — public hostname for Grafana, e.g. `flights.example.com`. Resolved in Task 12.
- `INFRA_REPO` — `git@github.com:waitline/waitline-infra.git`. App path: `clusters/hetzner-personal/apps/flight-tracker/`. Used in Task 13.
- `SOPS_RECIPIENT` — age public key from the infra repo's `.sops.yaml`. Resolved in Task 13.

## Global Constraints (verbatim from spec)

- Deploy method: **GitOps via Flux** — final manifests live in `waitline-infra` under `clusters/hetzner-personal/apps/flight-tracker/`, reconciled by the existing `waitline` Kustomization (`prune: true`, SOPS decryption).
- Storage engine: **InfluxDB 2.x OSS** (`influxdb:2.7`). Org `flights`, bucket `flight_prices`, infinite retention.
- Grafana exposure: **Cloudflare Tunnel + Cloudflare Access** at `GRAFANA_HOST`.
- Logger image: **public** GHCR image (no imagePullSecret).
- Fetch library: **`fast-flights==3.0.2`** pinned + parser guard patch. Currency **EUR** enforced in the query.
- Fetch mode: default HTTP (`primp`), **contingent on Task 1 cluster-IP verification**; switch to `fetch_mode="fallback"` (Playwright/chromium) only if that gate fails.
- Storage class: only `local-path` (default) is available.
- Cluster namespace: `flight-tracker`.
- Measurement `flight_price`; tags `route_id, origin, destination, trip, currency, price_level`; fields `price` (int), `num_options` (int), `cheapest_airline` (string), `days_to_departure` (int); timestamp = fetch time.
- All temporary/venv/scratch files stay ignored by git (`.gitignore` already covers `ffvenv/`, `v22/`, `__pycache__/`).

## File Structure

Application (this repo → GitHub repo for the image build):

- `logger.py` — MODIFY. Load config, build query, fetch cheapest per route (retry), map to records, hard-fail on parse-empty, write to InfluxDB. No more CSV writing.
- `flight_fetch.py` — CREATE. `fetch_cheapest(route, cfg) -> CheapestResult`. Isolates the `fast-flights` interaction so it's mockable.
- `influx_writer.py` — CREATE. `build_point(record)` and `write_records(records, cfg)` over `influxdb-client`. Reads connection from env.
- `records.py` — CREATE. `Record` dataclass + `route_to_record(route, cheapest, cfg, now)` pure mapping (testable without network).
- `backfill.py` — CREATE. Import existing `data/prices.csv` rows into InfluxDB (idempotent).
- `scripts/patch_fast_flights.py` — CREATE. Apply the parser guard to the installed `fast_flights` package (used by Dockerfile and local dev).
- `requirements.txt` — MODIFY. Pin versions, add `influxdb-client`, `typing_extensions`.
- `Dockerfile` — CREATE. Build the logger image; apply the patch at build time.
- `routes.json` — KEEP (becomes a ConfigMap in-cluster).
- `tests/test_records.py`, `tests/test_flight_fetch.py`, `tests/test_influx_writer.py` — CREATE. Unit tests.
- `.github/workflows/build-image.yml` — CREATE. Build + push image to GHCR.
- `.github/workflows/track.yml` — DELETE (cron moves into the cluster).
- `index.html` — DELETE (superseded by Grafana). (`data/prices.csv` kept as backfill source.)

Deployment manifests (this repo `deploy/`, later copied to `waitline-infra`):

- `deploy/kustomization.yaml`
- `deploy/namespace.yaml`
- `deploy/routes-configmap.yaml`
- `deploy/influxdb.yaml` (PVC + Deployment + Service)
- `deploy/grafana-provisioning.yaml` (datasource + dashboard-provider ConfigMaps)
- `deploy/grafana-dashboard.yaml` (dashboard JSON ConfigMap)
- `deploy/grafana.yaml` (PVC + Deployment + Service)
- `deploy/cronjob.yaml`
- `deploy/secret.example.yaml` (plaintext template; the real one is SOPS-encrypted in the infra repo)

---

### Task 1: Cluster-IP fetch verification (GATE — do this before anything else)

Proves the fetch returns clean **EUR** and is not bot-challenged **from the cluster's egress IP**. Everything downstream depends on the outcome.

**Files:** none committed. Uses a throwaway pod + a temporary local script.

**Interfaces:**
- Produces: a go/no-go decision. Go → default HTTP fetch mode for all later tasks. No-go → switch Dockerfile (Task 6) to the Playwright variant and add a proxy env.

- [ ] **Step 1: Write the verification script locally**

Create `/tmp/ff_verify.py` (scratch, not committed):

```python
import json, urllib.request
import fast_flights as ff

# Apply the parser guard in-process (same fix packaged later in scripts/patch_fast_flights.py)
import fast_flights.parser as P
_src = None
try:
    q = ff.create_query(
        flights=[ff.FlightQuery(date="2026-10-26", from_airport="IST", to_airport="DPS")],
        trip="one-way", seat="economy",
        passengers=ff.Passengers(adults=1), currency="EUR",
    )
    res = ff.get_flights(q)
except IndexError:
    res = None

egress = urllib.request.urlopen("https://api.ipify.org").read().decode()
print("EGRESS_IP", egress)
if res is None:
    print("PARSE_FAILED_UNPATCHED (expected if guard not applied)")
else:
    items = [f for f in res if isinstance(f.price, int) and f.price > 0]
    print("NUM_PRICED", len(items))
    if items:
        best = min(items, key=lambda f: f.price)
        print("CHEAPEST", best.price, "AIRLINES", best.airlines)
```

Note: the guard patch lands in Task 2/6. For this gate, run inside a pod that installs and patches the package inline (next step).

- [ ] **Step 2: Run the fetch from a throwaway pod on the cluster**

Run:

```bash
kubectl --context hetzner-personal -n default run ff-verify --rm -it --restart=Never \
  --image=python:3.11-slim --command -- bash -c '
set -e
pip install -q "fast-flights==3.0.2" typing_extensions >/dev/null
PKG=$(python -c "import fast_flights,os;print(os.path.dirname(fast_flights.__file__))")
python - <<PATCH
import re,io
p="'"$PKG"'/parser.py"
s=open(p).read()
s=s.replace("        flight = k[0]\n        price = k[1][0][1]",
            "        flight = k[0]\n        if not k[1] or not k[1][0]:\n            continue\n        price = k[1][0][1]")
open(p,"w").write(s)
print("patched" if "if not k[1] or not k[1][0]" in s else "PATCH FAILED")
PATCH
python - <<RUN
import urllib.request, fast_flights as ff
q = ff.create_query(flights=[ff.FlightQuery(date="2026-10-26", from_airport="IST", to_airport="DPS")],
    trip="one-way", seat="economy", passengers=ff.Passengers(adults=1), currency="EUR")
res = ff.get_flights(q)
items=[f for f in res if isinstance(f.price,int) and f.price>0]
print("EGRESS_IP", urllib.request.urlopen("https://api.ipify.org").read().decode())
print("NUM_PRICED", len(items))
best=min(items, key=lambda f: f.price) if items else None
print("CHEAPEST", best.price if best else None, "AIRLINES", best.airlines if best else None)
RUN
'
```

Expected (GO): `NUM_PRICED` ≥ 1 and `CHEAPEST` is a plausible EUR integer (roughly 400–800 for IST→DPS, matching `data/prices.csv`). Currency is implicitly EUR because `currency="EUR"` was set and prices land in the CSV's known EUR range.

- [ ] **Step 3: Record the decision**

- If GO: note it in the plan/PR description; proceed to Task 2 with default fetch mode.
- If prices look like a different currency's magnitude (e.g. ~20000 → TRY), or `NUM_PRICED` is 0 with a bot/consent page, or the pod hangs/gets a challenge: STOP and report. The contingency is Task 6's Playwright variant + optional `HTTP_PROXY`. Do not build the stack until this is green.

- [ ] **Step 4: Commit (decision note only)**

```bash
git add docs/superpowers/plans/2026-07-12-flight-tracker-hetzner.md
git commit -m "chore: record cluster-IP fetch verification result"
```

---

### Task 2: Records mapping (pure, TDD)

The pure data transformation from a route + fetched cheapest fare into an InfluxDB-bound record. No network, fully unit-tested.

**Files:**
- Create: `records.py`
- Test: `tests/test_records.py`

**Interfaces:**
- Produces:
  - `@dataclass CheapestResult: price: int|None; airline: str; num_options: int; price_level: str`
  - `@dataclass Record: measurement: str; tags: dict[str,str]; fields: dict[str,int|str]; time: datetime`
  - `route_to_record(route: dict, cfg: dict, cheapest: CheapestResult, now: datetime) -> Record`
- Consumes (later): `flight_fetch.fetch_cheapest` returns `CheapestResult`; `influx_writer.build_point` consumes `Record`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_records.py
from datetime import datetime, timezone
from records import CheapestResult, Record, route_to_record

CFG = {"currency": "EUR"}
ROUTE = {"id": "IST-DPS", "origin": "IST", "destination": "DPS",
         "depart_date": "2026-10-26", "trip": "one-way"}
NOW = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)

def test_maps_tags_and_fields():
    c = CheapestResult(price=468, airline="Qatar Airways", num_options=35, price_level="typical")
    r = route_to_record(ROUTE, CFG, c, NOW)
    assert r.measurement == "flight_price"
    assert r.tags == {"route_id": "IST-DPS", "origin": "IST", "destination": "DPS",
                      "trip": "one-way", "currency": "EUR", "price_level": "typical"}
    assert r.fields["price"] == 468
    assert r.fields["num_options"] == 35
    assert r.fields["cheapest_airline"] == "Qatar Airways"
    assert r.fields["days_to_departure"] == 106  # 2026-07-12 -> 2026-10-26
    assert r.time == NOW

def test_missing_price_level_defaults_unknown():
    c = CheapestResult(price=500, airline="X", num_options=1, price_level="")
    r = route_to_record(ROUTE, CFG, c, NOW)
    assert r.tags["price_level"] == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_records.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'records'`.

- [ ] **Step 3: Write minimal implementation**

```python
# records.py
from dataclasses import dataclass
from datetime import datetime, date


@dataclass
class CheapestResult:
    price: int | None
    airline: str
    num_options: int
    price_level: str


@dataclass
class Record:
    measurement: str
    tags: dict
    fields: dict
    time: datetime


def _days_to_departure(depart_date: str, now: datetime) -> int:
    dep = date.fromisoformat(depart_date)
    return (dep - now.date()).days


def route_to_record(route: dict, cfg: dict, cheapest: CheapestResult, now: datetime) -> Record:
    return Record(
        measurement="flight_price",
        tags={
            "route_id": route.get("id", f'{route["origin"]}-{route["destination"]}'),
            "origin": route["origin"],
            "destination": route["destination"],
            "trip": route.get("trip", "one-way"),
            "currency": cfg.get("currency", "EUR"),
            "price_level": cheapest.price_level or "unknown",
        },
        fields={
            "price": int(cheapest.price),
            "num_options": int(cheapest.num_options),
            "cheapest_airline": cheapest.airline or "",
            "days_to_departure": _days_to_departure(route["depart_date"], now),
        },
        time=now,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_records.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add records.py tests/test_records.py
git commit -m "feat: pure route->record mapping for InfluxDB"
```

---

### Task 3: Flight fetch wrapper + parser patch (TDD for selection logic)

Isolate the `fast-flights` call behind `fetch_cheapest`, with the cheapest-selection logic unit-tested via a fake result. Also ship the reusable parser-guard patch.

**Files:**
- Create: `flight_fetch.py`, `scripts/patch_fast_flights.py`
- Modify: `requirements.txt`
- Test: `tests/test_flight_fetch.py`

**Interfaces:**
- Produces: `fetch_cheapest(route: dict, cfg: dict, get_flights=<injected>) -> CheapestResult`. The `get_flights` param is injectable for testing; defaults to the real `fast_flights.get_flights` with a built query. `select_cheapest(result) -> CheapestResult` is the pure selector.
- Consumes: `records.CheapestResult`.

- [ ] **Step 1: Pin dependencies**

Overwrite `requirements.txt`:

```
fast-flights==3.0.2
influxdb-client==1.48.0
typing_extensions>=4.9
```

- [ ] **Step 2: Write the parser-guard patch script**

```python
# scripts/patch_fast_flights.py
"""Apply a guard to fast-flights 3.0.2's parser so itineraries with no price
in the expected slot are skipped instead of raising IndexError.

Temporary: remove once fixed upstream. Idempotent.
"""
import os
import fast_flights

TARGET = "        flight = k[0]\n        price = k[1][0][1]"
GUARDED = ("        flight = k[0]\n"
           "        if not k[1] or not k[1][0]:  # guard: no price in this slot\n"
           "            continue\n"
           "        price = k[1][0][1]")


def main() -> int:
    path = os.path.join(os.path.dirname(fast_flights.__file__), "parser.py")
    src = open(path, encoding="utf-8").read()
    if "no price in this slot" in src:
        print("already patched")
        return 0
    if TARGET not in src:
        raise SystemExit(f"patch anchor not found in {path} — fast-flights version changed?")
    open(path, "w", encoding="utf-8").write(src.replace(TARGET, GUARDED))
    print("patched", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Write the failing test for selection logic**

```python
# tests/test_flight_fetch.py
from flight_fetch import select_cheapest, fetch_cheapest

class FakeFlight:
    def __init__(self, price, airlines):
        self.price = price
        self.airlines = airlines

class FakeResult(list):
    current_price = "typical"

def test_select_cheapest_picks_min_valid():
    res = FakeResult([FakeFlight(600, ["A"]), FakeFlight(468, ["Qatar Airways"]), FakeFlight(None, ["B"])])
    c = select_cheapest(res)
    assert c.price == 468
    assert c.airline == "Qatar Airways"
    assert c.num_options == 3
    assert c.price_level == "typical"

def test_select_cheapest_no_valid_returns_none_price():
    res = FakeResult([FakeFlight(None, ["B"]), FakeFlight(0, ["C"])])
    c = select_cheapest(res)
    assert c.price is None
    assert c.num_options == 2

def test_fetch_cheapest_uses_injected_get_flights():
    res = FakeResult([FakeFlight(500, ["Emirates"])])
    route = {"id": "IST-DPS", "origin": "IST", "destination": "DPS",
             "depart_date": "2026-10-26", "trip": "one-way"}
    cfg = {"currency": "EUR", "seat": "economy", "adults": 1}
    c = fetch_cheapest(route, cfg, get_flights=lambda q: res)
    assert c.price == 500
    assert c.airline == "Emirates"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_flight_fetch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flight_fetch'`.

- [ ] **Step 5: Write minimal implementation**

```python
# flight_fetch.py
import time
import sys
import fast_flights as ff
from records import CheapestResult

MAX_ATTEMPTS = 3


def _build_query(route: dict, cfg: dict):
    legs = [ff.FlightQuery(date=route["depart_date"],
                           from_airport=route["origin"], to_airport=route["destination"])]
    trip = route.get("trip", "one-way")
    if trip == "round-trip":
        if not route.get("return_date"):
            raise ValueError(f'route {route.get("id")} is round-trip but has no return_date')
        legs.append(ff.FlightQuery(date=route["return_date"],
                                   from_airport=route["destination"], to_airport=route["origin"]))
    return ff.create_query(
        flights=legs, trip=trip, seat=cfg.get("seat", "economy"),
        passengers=ff.Passengers(adults=cfg.get("adults", 1)),
        currency=cfg.get("currency", "EUR"),
    )


def select_cheapest(result) -> CheapestResult:
    items = list(result)
    valid = [f for f in items if isinstance(f.price, int) and f.price > 0]
    level = getattr(result, "current_price", "") or ""
    if not valid:
        return CheapestResult(price=None, airline="", num_options=len(items), price_level=level)
    best = min(valid, key=lambda f: f.price)
    airline = ", ".join(best.airlines) if getattr(best, "airlines", None) else ""
    return CheapestResult(price=best.price, airline=airline, num_options=len(items), price_level=level)


def fetch_cheapest(route: dict, cfg: dict, get_flights=None) -> CheapestResult:
    get_flights = get_flights or ff.get_flights
    q = _build_query(route, cfg)
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return select_cheapest(get_flights(q))
        except Exception as e:  # transient scrape/network failure
            last_err = e
            print(f"  attempt {attempt}/{MAX_ATTEMPTS} failed: {e}", file=sys.stderr)
            time.sleep(4 * attempt)
    raise last_err
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_flight_fetch.py -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add flight_fetch.py scripts/patch_fast_flights.py requirements.txt tests/test_flight_fetch.py
git commit -m "feat: fetch_cheapest wrapper + fast-flights parser guard"
```

---

### Task 4: InfluxDB writer (TDD for point construction)

Convert `Record`s to InfluxDB `Point`s and write them. Point construction is unit-tested; the network write reads config from env.

**Files:**
- Create: `influx_writer.py`
- Test: `tests/test_influx_writer.py`

**Interfaces:**
- Produces:
  - `influx_config_from_env() -> dict` with keys `url, token, org, bucket`.
  - `build_point(record: Record) -> influxdb_client.Point`.
  - `write_records(records: list[Record], cfg: dict) -> int` (returns count written).
- Consumes: `records.Record`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_influx_writer.py
from datetime import datetime, timezone
from records import Record
from influx_writer import build_point, influx_config_from_env

def test_build_point_encodes_tags_fields_time():
    rec = Record(
        measurement="flight_price",
        tags={"route_id": "IST-DPS", "currency": "EUR", "price_level": "typical"},
        fields={"price": 468, "num_options": 35, "cheapest_airline": "Qatar Airways",
                "days_to_departure": 106},
        time=datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc),
    )
    line = build_point(rec).to_line_protocol()
    assert line.startswith("flight_price,")
    assert "route_id=IST-DPS" in line
    assert "price_level=typical" in line
    assert "price=468i" in line          # integer field
    assert 'cheapest_airline="Qatar Airways"' in line

def test_config_from_env(monkeypatch):
    monkeypatch.setenv("INFLUXDB_URL", "http://influxdb.flight-tracker:8086")
    monkeypatch.setenv("INFLUXDB_TOKEN", "tok")
    monkeypatch.setenv("INFLUXDB_ORG", "flights")
    monkeypatch.setenv("INFLUXDB_BUCKET", "flight_prices")
    cfg = influx_config_from_env()
    assert cfg == {"url": "http://influxdb.flight-tracker:8086", "token": "tok",
                   "org": "flights", "bucket": "flight_prices"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_influx_writer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'influx_writer'`.

- [ ] **Step 3: Write minimal implementation**

```python
# influx_writer.py
import os
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from records import Record


def influx_config_from_env() -> dict:
    return {
        "url": os.environ["INFLUXDB_URL"],
        "token": os.environ["INFLUXDB_TOKEN"],
        "org": os.environ["INFLUXDB_ORG"],
        "bucket": os.environ["INFLUXDB_BUCKET"],
    }


def build_point(record: Record) -> Point:
    p = Point(record.measurement)
    for k, v in record.tags.items():
        p = p.tag(k, v)
    for k, v in record.fields.items():
        p = p.field(k, v)
    return p.time(record.time, WritePrecision.S)


def write_records(records: list[Record], cfg: dict) -> int:
    if not records:
        return 0
    points = [build_point(r) for r in records]
    with InfluxDBClient(url=cfg["url"], token=cfg["token"], org=cfg["org"]) as client:
        client.write_api(write_options=SYNCHRONOUS).write(bucket=cfg["bucket"], record=points)
    return len(points)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_influx_writer.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add influx_writer.py tests/test_influx_writer.py
git commit -m "feat: InfluxDB point construction + writer"
```

---

### Task 5: Rewrite `logger.py` to orchestrate fetch → InfluxDB with hard-fail

Wire the pieces together. Replace CSV writing entirely. Enforce the failure semantics: if a route returns options but none are priced across all routes, exit non-zero so the CronJob run goes red.

**Files:**
- Modify: `logger.py` (full rewrite)
- Test: `tests/test_logger.py`

**Interfaces:**
- Produces: `collect(cfg, fetch=..., now=...) -> tuple[list[Record], int]` returning `(records, hard_failures)`; `main() -> int` (exit code).
- Consumes: `flight_fetch.fetch_cheapest`, `records.route_to_record`, `influx_writer.write_records`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_logger.py
from datetime import datetime, timezone
from records import CheapestResult
import logger

CFG = {"currency": "EUR", "seat": "economy", "adults": 1,
       "routes": [{"id": "IST-DPS", "origin": "IST", "destination": "DPS",
                   "depart_date": "2026-10-26", "trip": "one-way"}]}
NOW = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)

def test_collect_builds_record_for_priced_route():
    fetch = lambda route, cfg: CheapestResult(468, "Qatar Airways", 35, "typical")
    records, hard_failures = logger.collect(CFG, fetch=fetch, now=NOW)
    assert len(records) == 1
    assert records[0].fields["price"] == 468
    assert hard_failures == 0

def test_collect_counts_hard_failure_when_options_exist_but_unpriced():
    # options were returned (num_options>0) but none had a price -> data broke, not "sold out"
    fetch = lambda route, cfg: CheapestResult(None, "", 30, "typical")
    records, hard_failures = logger.collect(CFG, fetch=fetch, now=NOW)
    assert records == []
    assert hard_failures == 1

def test_collect_no_hard_failure_when_zero_options():
    # genuinely no itineraries (sold out / too far out) -> skip, not a failure
    fetch = lambda route, cfg: CheapestResult(None, "", 0, "")
    records, hard_failures = logger.collect(CFG, fetch=fetch, now=NOW)
    assert records == []
    assert hard_failures == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_logger.py -v`
Expected: FAIL (`AttributeError: module 'logger' has no attribute 'collect'` or import error from old logger).

- [ ] **Step 3: Rewrite `logger.py`**

```python
#!/usr/bin/env python3
"""Flight price logger: fetch cheapest fares per route and write them to InfluxDB.

Designed to run as a Kubernetes CronJob every 15 minutes.
Exit codes: 0 = ok (rows written or genuinely no itineraries),
            2 = hard failure (options existed but none were priced -> likely a
                parser/scrape breakage worth alerting on),
            1 = unexpected error.
"""
import json
import os
import sys
from datetime import datetime, timezone

from flight_fetch import fetch_cheapest
from records import route_to_record
from influx_writer import influx_config_from_env, write_records

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("ROUTES_PATH", os.path.join(HERE, "routes.json"))


def load_config(path=CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def collect(cfg: dict, fetch=fetch_cheapest, now=None):
    now = now or datetime.now(timezone.utc)
    records, hard_failures = [], 0
    for route in cfg.get("routes", []):
        rid = route.get("id", f'{route["origin"]}-{route["destination"]}')
        print(f"Querying {rid} ...")
        try:
            cheapest = fetch(route, cfg)
        except Exception as e:
            print(f"  ERROR for {rid}: {e}", file=sys.stderr)
            hard_failures += 1
            continue
        if cheapest.price is None:
            if cheapest.num_options > 0:
                # options existed but none were priced -> data path broke
                print(f"  HARD FAIL {rid}: {cheapest.num_options} options, none priced", file=sys.stderr)
                hard_failures += 1
            else:
                print(f"  no itineraries for {rid} (skipping)")
            continue
        print(f"  cheapest: {cheapest.price} {cfg.get('currency','EUR')} on {cheapest.airline}")
        records.append(route_to_record(route, cfg, cheapest, now))
    return records, hard_failures


def main() -> int:
    cfg = load_config()
    records, hard_failures = collect(cfg)
    written = write_records(records, influx_config_from_env())
    print(f"Wrote {written} point(s); {hard_failures} hard failure(s).")
    if hard_failures:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ -v`
Expected: PASS (all tests across the suite).

- [ ] **Step 5: Commit**

```bash
git add logger.py tests/test_logger.py
git commit -m "feat: logger orchestrates fetch->InfluxDB with hard-fail semantics"
```

---

### Task 6: Dockerfile + local end-to-end against a throwaway InfluxDB

Package the logger and prove the full write path against a real InfluxDB running locally in Docker.

**Files:**
- Create: `Dockerfile`, `.dockerignore`

**Interfaces:**
- Produces: image `flight-tracker-logger:local` whose entrypoint runs `logger.py`, reading `INFLUXDB_*` + `ROUTES_PATH` from env.

- [ ] **Step 1: Write `.dockerignore`**

```
ffvenv/
v22/
__pycache__/
tests/
docs/
data/
.git/
*.md
```

- [ ] **Step 2: Write the Dockerfile (default HTTP fetch mode)**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Apply the fast-flights parser guard (temporary; pinned to ==3.0.2).
COPY scripts/patch_fast_flights.py scripts/patch_fast_flights.py
RUN python scripts/patch_fast_flights.py
COPY records.py flight_fetch.py influx_writer.py logger.py routes.json ./
ENTRYPOINT ["python", "logger.py"]
```

> Contingency (only if Task 1 was NO-GO): switch base to a Playwright image
> (`mcr.microsoft.com/playwright/python:v1.47.0-jammy`), add `fetch_mode="fallback"`
> in `flight_fetch._build_query`/`get_flights` call, and pass `HTTP_PROXY` via env.
> Do not do this if Task 1 was GO.

- [ ] **Step 3: Build the image**

Run: `docker build -t flight-tracker-logger:local .`
Expected: build succeeds; the patch step prints `patched .../parser.py`.

- [ ] **Step 4: Start a throwaway InfluxDB**

Run:

```bash
docker run -d --name ftinflux -p 8086:8086 \
  -e DOCKER_INFLUXDB_INIT_MODE=setup \
  -e DOCKER_INFLUXDB_INIT_USERNAME=admin \
  -e DOCKER_INFLUXDB_INIT_PASSWORD=adminpw123 \
  -e DOCKER_INFLUXDB_INIT_ORG=flights \
  -e DOCKER_INFLUXDB_INIT_BUCKET=flight_prices \
  -e DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=localtoken123 \
  influxdb:2.7
sleep 8
```

- [ ] **Step 5: Run the logger container against it**

Run:

```bash
docker run --rm --network host \
  -e INFLUXDB_URL=http://localhost:8086 \
  -e INFLUXDB_TOKEN=localtoken123 \
  -e INFLUXDB_ORG=flights \
  -e INFLUXDB_BUCKET=flight_prices \
  flight-tracker-logger:local
```

Expected: prints `cheapest: <int> EUR on ...` and `Wrote 1 point(s); 0 hard failure(s).`

- [ ] **Step 6: Verify the point landed**

Run:

```bash
docker exec ftinflux influx query \
  'from(bucket:"flight_prices") |> range(start:-1h) |> filter(fn:(r)=>r._measurement=="flight_price")' \
  --org flights --token localtoken123 | head -30
```

Expected: at least one row with `_field=price` and a plausible EUR value.

- [ ] **Step 7: Tear down and commit**

```bash
docker rm -f ftinflux
git add Dockerfile .dockerignore
git commit -m "feat: containerize logger; verified end-to-end against local InfluxDB"
```

---

### Task 7: Backfill script for existing CSV history

Import the real `data/prices.csv` history so the dashboard opens with data. Idempotent.

**Files:**
- Create: `backfill.py`
- Test: `tests/test_backfill.py`

**Interfaces:**
- Produces: `csv_rows_to_records(path) -> list[Record]`; `main()` writes them via `influx_writer.write_records`.
- Consumes: `records.Record`, `influx_writer.write_records`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backfill.py
import textwrap
from backfill import csv_rows_to_records

def test_parses_csv_into_records(tmp_path):
    csv = tmp_path / "prices.csv"
    csv.write_text(textwrap.dedent("""\
        timestamp_utc,route_id,origin,destination,depart_date,return_date,trip,cheapest_price,currency,cheapest_airline,num_options
        2026-07-08T06:00:04Z,IST-DPS,IST,DPS,2026-10-26,,one-way,512,EUR,Qatar Airways,34
    """))
    recs = csv_rows_to_records(str(csv))
    assert len(recs) == 1
    r = recs[0]
    assert r.measurement == "flight_price"
    assert r.tags["route_id"] == "IST-DPS"
    assert r.tags["currency"] == "EUR"
    assert r.fields["price"] == 512
    assert r.fields["num_options"] == 34
    assert r.fields["cheapest_airline"] == "Qatar Airways"
    assert r.time.year == 2026 and r.time.month == 7 and r.time.day == 8

def test_skips_rows_without_price(tmp_path):
    csv = tmp_path / "prices.csv"
    csv.write_text(
        "timestamp_utc,route_id,origin,destination,depart_date,return_date,trip,cheapest_price,currency,cheapest_airline,num_options\n"
        "2026-07-08T06:00:04Z,IST-DPS,IST,DPS,2026-10-26,,one-way,,EUR,,0\n"
    )
    assert csv_rows_to_records(str(csv)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backfill.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backfill'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backfill.py
"""One-time import of data/prices.csv history into InfluxDB. Idempotent:
InfluxDB overwrites points with identical measurement+tags+timestamp."""
import csv
import os
import sys
from datetime import datetime

from records import Record
from influx_writer import influx_config_from_env, write_records

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(HERE, "data", "prices.csv")


def _dtd(depart_date: str, ts: datetime) -> int:
    from datetime import date
    return (date.fromisoformat(depart_date) - ts.date()).days


def csv_rows_to_records(path=DEFAULT_CSV) -> list[Record]:
    records = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row.get("cheapest_price"):
                continue
            ts = datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
            records.append(Record(
                measurement="flight_price",
                tags={
                    "route_id": row["route_id"],
                    "origin": row["origin"],
                    "destination": row["destination"],
                    "trip": row.get("trip", "one-way"),
                    "currency": row.get("currency", "EUR"),
                    "price_level": "unknown",
                },
                fields={
                    "price": int(row["cheapest_price"]),
                    "num_options": int(row.get("num_options") or 0),
                    "cheapest_airline": row.get("cheapest_airline", ""),
                    "days_to_departure": _dtd(row["depart_date"], ts),
                },
                time=ts,
            ))
    return records


def main() -> int:
    recs = csv_rows_to_records()
    n = write_records(recs, influx_config_from_env())
    print(f"Backfilled {n} historical point(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ -v`
Expected: PASS (whole suite).

- [ ] **Step 5: Commit**

```bash
git add backfill.py tests/test_backfill.py
git commit -m "feat: idempotent CSV->InfluxDB history backfill"
```

---

### Task 8: GitHub Actions image build → GHCR; remove old workflow

Move CI from "Actions runs the logger" to "Actions builds the image." The 15-minute cron moves into the cluster.

**Files:**
- Create: `.github/workflows/build-image.yml`
- Delete: `.github/workflows/track.yml`, `index.html`

**Interfaces:**
- Produces: `ghcr.io/GHCR_OWNER/flight-tracker-logger` tagged `latest` + commit SHA, public.

- [ ] **Step 1: Resolve `GHCR_OWNER`**

Ask the user which GitHub org/user should own the image (the spec allows a public image, matching cluster convention `ghcr.io/...`). Record the value and use it everywhere below.

- [ ] **Step 2: Write the workflow**

```yaml
# .github/workflows/build-image.yml
name: Build logger image
on:
  push:
    branches: [main]
    paths-ignore: ["docs/**", "deploy/**", "*.md"]
  workflow_dispatch: {}
permissions:
  contents: read
  packages: write
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/metadata-action@v5
        id: meta
        with:
          images: ghcr.io/GHCR_OWNER/flight-tracker-logger
          tags: |
            type=raw,value=latest
            type=sha,format=long
      - uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```

- [ ] **Step 3: Remove superseded files**

Run:

```bash
git rm .github/workflows/track.yml index.html
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/build-image.yml
git commit -m "ci: build logger image to GHCR; drop Actions-cron + Chart.js dashboard"
```

- [ ] **Step 5: Push and confirm the image builds**

After the repo has a GitHub remote (create it if needed, then `git push -u origin main`), open the Actions run and confirm the image appears at `ghcr.io/GHCR_OWNER/flight-tracker-logger`. Set the package visibility to **public** in the GHCR package settings.

Expected: a green build; package visible and public.

---

### Task 9: InfluxDB manifests — apply and verify

Stand up InfluxDB 2.7 in-cluster. Author manifests in `deploy/`, apply directly for fast iteration (Flux adoption happens in Task 14).

**Files:**
- Create: `deploy/namespace.yaml`, `deploy/influxdb.yaml`, `deploy/secret.example.yaml`

**Interfaces:**
- Produces: Service `influxdb.flight-tracker:8086`; bucket `flight_prices`, org `flights`; admin token in secret `flight-tracker-secrets` key `influxdb-token`.

- [ ] **Step 1: Namespace**

```yaml
# deploy/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: flight-tracker
```

- [ ] **Step 2: Secret template (plaintext; real one is SOPS-encrypted in Task 14)**

```yaml
# deploy/secret.example.yaml
apiVersion: v1
kind: Secret
metadata:
  name: flight-tracker-secrets
  namespace: flight-tracker
type: Opaque
stringData:
  influxdb-admin-user: admin
  influxdb-admin-password: CHANGE_ME_STRONG
  influxdb-token: CHANGE_ME_LONG_RANDOM_TOKEN
  grafana-admin-user: admin
  grafana-admin-password: CHANGE_ME_STRONG
```

- [ ] **Step 3: Generate real secret values and create the secret in-cluster**

Run:

```bash
INFLUX_TOKEN=$(openssl rand -hex 32)
INFLUX_PW=$(openssl rand -base64 18)
GRAFANA_PW=$(openssl rand -base64 18)
kubectl --context hetzner-personal apply -f deploy/namespace.yaml
kubectl --context hetzner-personal -n flight-tracker create secret generic flight-tracker-secrets \
  --from-literal=influxdb-admin-user=admin \
  --from-literal=influxdb-admin-password="$INFLUX_PW" \
  --from-literal=influxdb-token="$INFLUX_TOKEN" \
  --from-literal=grafana-admin-user=admin \
  --from-literal=grafana-admin-password="$GRAFANA_PW"
echo "SAVE THESE: influx-token=$INFLUX_TOKEN grafana-pw=$GRAFANA_PW"
```

Expected: secret created. Save the printed values for Task 11/12 and for SOPS in Task 14.

- [ ] **Step 4: InfluxDB PVC + Deployment + Service**

```yaml
# deploy/influxdb.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: influxdb-data
  namespace: flight-tracker
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: local-path
  resources:
    requests:
      storage: 5Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: influxdb
  namespace: flight-tracker
spec:
  replicas: 1
  strategy: { type: Recreate }
  selector: { matchLabels: { app: influxdb } }
  template:
    metadata:
      labels: { app: influxdb }
    spec:
      containers:
        - name: influxdb
          image: influxdb:2.7
          ports: [{ containerPort: 8086 }]
          env:
            - { name: DOCKER_INFLUXDB_INIT_MODE, value: setup }
            - { name: DOCKER_INFLUXDB_INIT_ORG, value: flights }
            - { name: DOCKER_INFLUXDB_INIT_BUCKET, value: flight_prices }
            - { name: DOCKER_INFLUXDB_INIT_RETENTION, value: "0s" }
            - name: DOCKER_INFLUXDB_INIT_USERNAME
              valueFrom: { secretKeyRef: { name: flight-tracker-secrets, key: influxdb-admin-user } }
            - name: DOCKER_INFLUXDB_INIT_PASSWORD
              valueFrom: { secretKeyRef: { name: flight-tracker-secrets, key: influxdb-admin-password } }
            - name: DOCKER_INFLUXDB_INIT_ADMIN_TOKEN
              valueFrom: { secretKeyRef: { name: flight-tracker-secrets, key: influxdb-token } }
          volumeMounts:
            - { name: data, mountPath: /var/lib/influxdb2 }
          readinessProbe:
            httpGet: { path: /health, port: 8086 }
            initialDelaySeconds: 5
            periodSeconds: 10
      volumes:
        - name: data
          persistentVolumeClaim: { claimName: influxdb-data }
---
apiVersion: v1
kind: Service
metadata:
  name: influxdb
  namespace: flight-tracker
spec:
  selector: { app: influxdb }
  ports: [{ port: 8086, targetPort: 8086 }]
```

- [ ] **Step 5: Apply and verify**

Run:

```bash
kubectl --context hetzner-personal apply -f deploy/influxdb.yaml
kubectl --context hetzner-personal -n flight-tracker rollout status deploy/influxdb --timeout=120s
kubectl --context hetzner-personal -n flight-tracker exec deploy/influxdb -- \
  influx bucket list --org flights --token "$INFLUX_TOKEN"
```

Expected: rollout completes; bucket list shows `flight_prices`.

- [ ] **Step 6: Commit**

```bash
git add deploy/namespace.yaml deploy/influxdb.yaml deploy/secret.example.yaml
git commit -m "feat: InfluxDB 2.7 manifests; verified bucket up in-cluster"
```

---

### Task 10: Routes ConfigMap + CronJob — apply and verify a real run

Deploy the logger as a CronJob reading routes from a ConfigMap, and trigger one run to confirm points land.

**Files:**
- Create: `deploy/routes-configmap.yaml`, `deploy/cronjob.yaml`

**Interfaces:**
- Consumes: image from Task 8, secret + Service from Task 9.
- Produces: `flight_price` points in InfluxDB every 15 min.

- [ ] **Step 1: Routes ConfigMap (mirrors routes.json so edits need no rebuild)**

```yaml
# deploy/routes-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: flight-tracker-routes
  namespace: flight-tracker
data:
  routes.json: |
    {
      "currency": "EUR",
      "seat": "economy",
      "adults": 1,
      "routes": [
        { "id": "IST-DPS", "origin": "IST", "destination": "DPS",
          "depart_date": "2026-10-26", "trip": "one-way" }
      ]
    }
```

- [ ] **Step 2: CronJob**

```yaml
# deploy/cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: flight-logger
  namespace: flight-tracker
spec:
  schedule: "*/15 * * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 2
      activeDeadlineSeconds: 300
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: logger
              image: ghcr.io/GHCR_OWNER/flight-tracker-logger:latest
              env:
                - { name: INFLUXDB_URL, value: "http://influxdb.flight-tracker:8086" }
                - { name: INFLUXDB_ORG, value: flights }
                - { name: INFLUXDB_BUCKET, value: flight_prices }
                - { name: ROUTES_PATH, value: /config/routes.json }
                - name: INFLUXDB_TOKEN
                  valueFrom: { secretKeyRef: { name: flight-tracker-secrets, key: influxdb-token } }
              volumeMounts:
                - { name: routes, mountPath: /config }
              resources:
                requests: { cpu: 50m, memory: 128Mi }
                limits: { cpu: 500m, memory: 512Mi }
          volumes:
            - name: routes
              configMap: { name: flight-tracker-routes }
```

- [ ] **Step 3: Apply**

Run:

```bash
kubectl --context hetzner-personal apply -f deploy/routes-configmap.yaml -f deploy/cronjob.yaml
```

Expected: configmap + cronjob created.

- [ ] **Step 4: Trigger a manual run and watch it**

Run:

```bash
kubectl --context hetzner-personal -n flight-tracker create job flight-logger-manual --from=cronjob/flight-logger
kubectl --context hetzner-personal -n flight-tracker wait --for=condition=complete job/flight-logger-manual --timeout=180s
kubectl --context hetzner-personal -n flight-tracker logs job/flight-logger-manual
```

Expected: logs show `cheapest: <int> EUR ...` and `Wrote 1 point(s); 0 hard failure(s).`; job completes.

- [ ] **Step 5: Verify the point in InfluxDB**

Run:

```bash
kubectl --context hetzner-personal -n flight-tracker exec deploy/influxdb -- \
  influx query 'from(bucket:"flight_prices")|>range(start:-1h)|>filter(fn:(r)=>r._field=="price")' \
  --org flights --token "$INFLUX_TOKEN" | head
```

Expected: at least one `price` row with a plausible EUR value.

- [ ] **Step 6: Clean up the manual job and commit**

```bash
kubectl --context hetzner-personal -n flight-tracker delete job flight-logger-manual
git add deploy/routes-configmap.yaml deploy/cronjob.yaml
git commit -m "feat: routes ConfigMap + 15-min CronJob; verified point written in-cluster"
```

---

### Task 11: Grafana — datasource + dashboard provisioning, apply and verify

Deploy Grafana with the InfluxDB datasource and a dashboard provisioned from ConfigMaps (no click-ops).

**Files:**
- Create: `deploy/grafana-provisioning.yaml`, `deploy/grafana-dashboard.yaml`, `deploy/grafana.yaml`

**Interfaces:**
- Consumes: InfluxDB Service + token secret (Task 9).
- Produces: Service `grafana.flight-tracker:3000` rendering the flight-price dashboard.

- [ ] **Step 1: Datasource + dashboard-provider ConfigMap**

```yaml
# deploy/grafana-provisioning.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-provisioning
  namespace: flight-tracker
data:
  datasource.yaml: |
    apiVersion: 1
    datasources:
      - name: InfluxDB
        uid: influxdb
        type: influxdb
        access: proxy
        url: http://influxdb.flight-tracker:8086
        jsonData:
          version: Flux
          organization: flights
          defaultBucket: flight_prices
        secureJsonData:
          token: ${INFLUXDB_TOKEN}
        isDefault: true
  dashboards.yaml: |
    apiVersion: 1
    providers:
      - name: flight-tracker
        type: file
        options:
          path: /var/lib/grafana/dashboards
```

- [ ] **Step 2: Dashboard JSON ConfigMap (v1: price-over-time, current price, latest table)**

```yaml
# deploy/grafana-dashboard.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboard-flights
  namespace: flight-tracker
data:
  flights.json: |
    {
      "title": "Flight Prices",
      "uid": "flight-prices",
      "schemaVersion": 39,
      "time": { "from": "now-30d", "to": "now" },
      "refresh": "15m",
      "panels": [
        {
          "type": "timeseries",
          "title": "Cheapest price over time (EUR)",
          "gridPos": { "h": 10, "w": 24, "x": 0, "y": 0 },
          "fieldConfig": { "defaults": { "unit": "currencyEUR" }, "overrides": [] },
          "targets": [
            {
              "datasource": { "type": "influxdb", "uid": "influxdb" },
              "query": "from(bucket: \"flight_prices\")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r._measurement == \"flight_price\" and r._field == \"price\")\n  |> group(columns: [\"route_id\"])\n  |> aggregateWindow(every: 15m, fn: min, createEmpty: false)"
            }
          ]
        },
        {
          "type": "stat",
          "title": "Current cheapest (EUR)",
          "gridPos": { "h": 6, "w": 8, "x": 0, "y": 10 },
          "fieldConfig": { "defaults": { "unit": "currencyEUR" }, "overrides": [] },
          "targets": [
            {
              "datasource": { "type": "influxdb", "uid": "influxdb" },
              "query": "from(bucket: \"flight_prices\")\n  |> range(start: -3h)\n  |> filter(fn: (r) => r._measurement == \"flight_price\" and r._field == \"price\")\n  |> group(columns: [\"route_id\"])\n  |> last()"
            }
          ]
        },
        {
          "type": "stat",
          "title": "Days to departure",
          "gridPos": { "h": 6, "w": 8, "x": 8, "y": 10 },
          "fieldConfig": { "defaults": { "unit": "short" }, "overrides": [] },
          "targets": [
            {
              "datasource": { "type": "influxdb", "uid": "influxdb" },
              "query": "from(bucket: \"flight_prices\")\n  |> range(start: -3h)\n  |> filter(fn: (r) => r._measurement == \"flight_price\" and r._field == \"days_to_departure\")\n  |> group(columns: [\"route_id\"])\n  |> last()"
            }
          ]
        },
        {
          "type": "table",
          "title": "Latest snapshot",
          "gridPos": { "h": 6, "w": 8, "x": 16, "y": 10 },
          "targets": [
            {
              "datasource": { "type": "influxdb", "uid": "influxdb" },
              "query": "from(bucket: \"flight_prices\")\n  |> range(start: -3h)\n  |> filter(fn: (r) => r._measurement == \"flight_price\" and (r._field == \"price\" or r._field == \"cheapest_airline\"))\n  |> last()\n  |> pivot(rowKey: [\"route_id\"], columnKey: [\"_field\"], valueColumn: \"_value\")"
            }
          ]
        }
      ]
    }
```

> The dashboard targets reference `"uid": "influxdb"`, which matches the `uid: influxdb` declared on the provisioned datasource in Step 1.

- [ ] **Step 3: Grafana PVC + Deployment + Service**

```yaml
# deploy/grafana.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: grafana-data
  namespace: flight-tracker
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: local-path
  resources: { requests: { storage: 1Gi } }
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
  namespace: flight-tracker
spec:
  replicas: 1
  strategy: { type: Recreate }
  selector: { matchLabels: { app: grafana } }
  template:
    metadata:
      labels: { app: grafana }
    spec:
      securityContext: { fsGroup: 472 }
      containers:
        - name: grafana
          image: grafana/grafana:11.1.0
          ports: [{ containerPort: 3000 }]
          env:
            - name: GF_SECURITY_ADMIN_USER
              valueFrom: { secretKeyRef: { name: flight-tracker-secrets, key: grafana-admin-user } }
            - name: GF_SECURITY_ADMIN_PASSWORD
              valueFrom: { secretKeyRef: { name: flight-tracker-secrets, key: grafana-admin-password } }
            - name: INFLUXDB_TOKEN
              valueFrom: { secretKeyRef: { name: flight-tracker-secrets, key: influxdb-token } }
            - { name: GF_SERVER_ROOT_URL, value: "https://GRAFANA_HOST" }
          volumeMounts:
            - { name: data, mountPath: /var/lib/grafana }
            - { name: provisioning-ds, mountPath: /etc/grafana/provisioning/datasources }
            - { name: provisioning-dash, mountPath: /etc/grafana/provisioning/dashboards }
            - { name: dashboards, mountPath: /var/lib/grafana/dashboards }
      volumes:
        - name: data
          persistentVolumeClaim: { claimName: grafana-data }
        - name: provisioning-ds
          configMap:
            name: grafana-provisioning
            items: [{ key: datasource.yaml, path: datasource.yaml }]
        - name: provisioning-dash
          configMap:
            name: grafana-provisioning
            items: [{ key: dashboards.yaml, path: dashboards.yaml }]
        - name: dashboards
          configMap:
            name: grafana-dashboard-flights
            items: [{ key: flights.json, path: flights.json }]
---
apiVersion: v1
kind: Service
metadata:
  name: grafana
  namespace: flight-tracker
spec:
  selector: { app: grafana }
  ports: [{ port: 3000, targetPort: 3000 }]
```

> `GRAFANA_HOST` is resolved in Task 12; if not yet known, set it to a placeholder like `grafana.local` and update in Task 12. The root URL only affects link generation, not datasource/dashboard rendering.

- [ ] **Step 4: Apply and verify via port-forward**

Run:

```bash
kubectl --context hetzner-personal apply \
  -f deploy/grafana-provisioning.yaml -f deploy/grafana-dashboard.yaml -f deploy/grafana.yaml
kubectl --context hetzner-personal -n flight-tracker rollout status deploy/grafana --timeout=120s
kubectl --context hetzner-personal -n flight-tracker port-forward deploy/grafana 3000:3000 &
sleep 4
curl -s -u admin:"$GRAFANA_PW" http://localhost:3000/api/datasources | head
curl -s -u admin:"$GRAFANA_PW" "http://localhost:3000/api/dashboards/uid/flight-prices" | head -c 300
```

Expected: datasources API returns the InfluxDB entry; dashboard API returns the `Flight Prices` dashboard. Open `http://localhost:3000` in a browser and confirm the time series renders the point(s) from Task 10.

- [ ] **Step 5: Stop the port-forward and commit**

```bash
kill %1 2>/dev/null || true
git add deploy/grafana-provisioning.yaml deploy/grafana-dashboard.yaml deploy/grafana.yaml
git commit -m "feat: Grafana with provisioned InfluxDB datasource + flight dashboard"
```

---

### Task 12: Backfill history into cluster InfluxDB

Load the real Jul 8–12 CSV history so the dashboard shows a trend immediately.

**Files:** none new (uses `backfill.py` + a one-off Job).

- [ ] **Step 1: Run backfill as a one-off Job using the logger image**

Run (overrides the image entrypoint to run `backfill.py`; mounts the CSV via a temporary ConfigMap):

```bash
kubectl --context hetzner-personal -n flight-tracker create configmap flight-history \
  --from-file=prices.csv=data/prices.csv
kubectl --context hetzner-personal -n flight-tracker apply -f - <<'EOF'
apiVersion: batch/v1
kind: Job
metadata:
  name: flight-backfill
  namespace: flight-tracker
spec:
  backoffLimit: 1
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: backfill
          image: ghcr.io/GHCR_OWNER/flight-tracker-logger:latest
          command: ["python", "backfill.py"]
          env:
            - { name: INFLUXDB_URL, value: "http://influxdb.flight-tracker:8086" }
            - { name: INFLUXDB_ORG, value: flights }
            - { name: INFLUXDB_BUCKET, value: flight_prices }
            - name: INFLUXDB_TOKEN
              valueFrom: { secretKeyRef: { name: flight-tracker-secrets, key: influxdb-token } }
          volumeMounts:
            - { name: hist, mountPath: /app/data }
      volumes:
        - name: hist
          configMap: { name: flight-history, items: [{ key: prices.csv, path: prices.csv }] }
EOF
kubectl --context hetzner-personal -n flight-tracker wait --for=condition=complete job/flight-backfill --timeout=120s
kubectl --context hetzner-personal -n flight-tracker logs job/flight-backfill
```

Expected: logs show `Backfilled N historical point(s).` (N = number of priced CSV rows, ~11).

> Note: `backfill.py` reads `/app/data/prices.csv` by default (its `DEFAULT_CSV`). The image's `.dockerignore` excludes `data/`, so the CSV is supplied at runtime via the ConfigMap mount at `/app/data` — matching the default path.

- [ ] **Step 2: Verify the history shows in Grafana**

Port-forward Grafana (as in Task 11) and confirm the time series now shows the Jul 8–12 downward trend plus the newer live point(s).

- [ ] **Step 3: Clean up the one-off resources**

```bash
kubectl --context hetzner-personal -n flight-tracker delete job flight-backfill
kubectl --context hetzner-personal -n flight-tracker delete configmap flight-history
```

No commit (no file changes).

---

### Task 13: Expose Grafana via Cloudflare Tunnel + Access

Make the dashboard reachable at `GRAFANA_HOST`, gated by Cloudflare Access.

**Files:** possibly `deploy/` tunnel config, depending on how the tunnel is managed (determined in Step 1).

- [ ] **Step 1: Determine how the Cloudflare Tunnel is configured**

Run:

```bash
kubectl --context hetzner-personal -n cloudflared get deploy cloudflared -o yaml | grep -A20 -iE 'args|command|configmap|secret|token'
kubectl --context hetzner-personal -n cloudflared get cm,secret
```

Two cases:
- **Remotely-managed tunnel** (token-based, config in Cloudflare dashboard): the ingress route is added in the **Cloudflare Zero Trust dashboard** → Networks → Tunnels → your tunnel → add public hostname `GRAFANA_HOST` → service `http://grafana.flight-tracker:3000`. Ask the user to do this (or provide access), and confirm `GRAFANA_HOST`.
- **Locally-managed** (`config.yaml` in a ConfigMap): add an ingress rule mapping `GRAFANA_HOST` → `http://grafana.flight-tracker.svc.cluster.local:3000` to that ConfigMap and roll out `cloudflared`. Author the change under `deploy/` if it belongs to this app, otherwise edit in place.

- [ ] **Step 2: Add the Cloudflare Access policy**

In the Cloudflare Zero Trust dashboard, add an Access application for `GRAFANA_HOST` with a policy limiting to the user's email (`eren@gowit.com`) or org. (User action — Access policy changes are outside kubectl.)

- [ ] **Step 3: Set Grafana's root URL to the real host**

If `GRAFANA_HOST` was a placeholder in Task 11, update `deploy/grafana.yaml` `GF_SERVER_ROOT_URL` to `https://GRAFANA_HOST`, re-apply, and roll out.

Run:

```bash
kubectl --context hetzner-personal apply -f deploy/grafana.yaml
kubectl --context hetzner-personal -n flight-tracker rollout status deploy/grafana --timeout=120s
```

- [ ] **Step 4: Verify external access**

Open `https://GRAFANA_HOST` in a browser: Cloudflare Access challenge → after auth, the Flight Prices dashboard loads.

Expected: dashboard reachable and gated.

- [ ] **Step 5: Commit any manifest changes**

```bash
git add deploy/grafana.yaml
git commit -m "feat: Grafana root URL set for Cloudflare Tunnel host"
```

---

### Task 14: Hand off to Flux GitOps (SOPS-encrypted secret) and adopt

Move the verified manifests into `waitline-infra` so Flux owns them, with the secret SOPS-encrypted. This is the final production state.

**Files (in the infra repo clone):** `clusters/hetzner-personal/apps/flight-tracker/*` + `kustomization.yaml`.

**Interfaces:**
- Consumes: verified manifests from `deploy/`.
- Produces: Flux Kustomization reconciling the app; secret encrypted at rest.

- [ ] **Step 1: Resolve infra-repo access and SOPS recipient**

Run:

```bash
git clone git@github.com:waitline/waitline-infra.git /tmp/waitline-infra
cat /tmp/waitline-infra/.sops.yaml
```

Expected: clone succeeds; `.sops.yaml` shows the age recipient(s) (`SOPS_RECIPIENT`) and the `creation_rules` path/regex that secrets must match.

- [ ] **Step 2: Copy manifests into the app path**

Run:

```bash
mkdir -p /tmp/waitline-infra/clusters/hetzner-personal/apps/flight-tracker
cp deploy/namespace.yaml deploy/influxdb.yaml deploy/routes-configmap.yaml \
   deploy/cronjob.yaml deploy/grafana-provisioning.yaml deploy/grafana-dashboard.yaml \
   deploy/grafana.yaml \
   /tmp/waitline-infra/clusters/hetzner-personal/apps/flight-tracker/
```

- [ ] **Step 3: Create the SOPS-encrypted secret from the live values**

Write the plaintext secret (reusing the exact token/passwords created in Task 9 so InfluxDB's existing data/token keep working), then encrypt in place:

```bash
cd /tmp/waitline-infra/clusters/hetzner-personal/apps/flight-tracker
cat > secret.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: flight-tracker-secrets
  namespace: flight-tracker
type: Opaque
stringData:
  influxdb-admin-user: admin
  influxdb-admin-password: "$INFLUX_PW"
  influxdb-token: "$INFLUX_TOKEN"
  grafana-admin-user: admin
  grafana-admin-password: "$GRAFANA_PW"
EOF
sops --encrypt --in-place secret.yaml
grep -q 'sops:' secret.yaml && echo "encrypted OK"
```

Expected: `encrypted OK`; the `stringData` values are now ciphertext. (Confirm the file path matches `.sops.yaml` `creation_rules`; if not, adjust the rule or path.)

- [ ] **Step 4: Kustomization tying the app together**

```yaml
# /tmp/waitline-infra/clusters/hetzner-personal/apps/flight-tracker/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - namespace.yaml
  - secret.yaml
  - influxdb.yaml
  - routes-configmap.yaml
  - cronjob.yaml
  - grafana-provisioning.yaml
  - grafana-dashboard.yaml
  - grafana.yaml
```

Replace every `GHCR_OWNER` / `GRAFANA_HOST` token in the copied files with the resolved real values before committing.

- [ ] **Step 5: Validate the kustomization builds**

Run:

```bash
kustomize build /tmp/waitline-infra/clusters/hetzner-personal/apps/flight-tracker >/dev/null && echo "build OK"
```

Expected: `build OK` (SOPS-encrypted secret is fine — Flux decrypts at apply time).

- [ ] **Step 6: Commit and push to the infra repo; let Flux reconcile**

```bash
cd /tmp/waitline-infra
git add clusters/hetzner-personal/apps/flight-tracker
git commit -m "feat: add flight-tracker app (InfluxDB + Grafana + 15m CronJob)"
git push origin main
flux --context hetzner-personal reconcile kustomization waitline --with-source
kubectl --context hetzner-personal -n flight-tracker get kustomization -A 2>/dev/null || \
  kubectl --context hetzner-personal -n flux-system get kustomization waitline
```

Expected: the `waitline` Kustomization reports `Applied revision: main@<newsha>` and `Ready=True`. Flux adopts the already-running resources (server-side apply reconciles labels/annotations without recreating pods).

- [ ] **Step 7: Final verification that Flux is the source of truth**

Run:

```bash
kubectl --context hetzner-personal -n flight-tracker get deploy,cronjob,pvc
kubectl --context hetzner-personal -n flight-tracker get secret flight-tracker-secrets -o jsonpath='{.metadata.managedFields[*].manager}{"\n"}'
```

Expected: all resources present; the secret is now managed by the Flux/`kustomize-controller`, confirming GitOps ownership. Dashboard still loads at `https://GRAFANA_HOST`.

---

## Self-Review

**Spec coverage** — every spec section maps to a task:
- Fetch fix + cluster-IP verification → Tasks 1, 3, 6.
- Logger → InfluxDB with hard-fail → Tasks 2–5.
- Data model (measurement/tags/fields) → Task 2 (records) + Task 4 (points).
- CSV backfill → Tasks 7, 12.
- InfluxDB 2.x → Task 9. Grafana provisioned → Task 11. CronJob */15 → Task 10.
- Image build to GHCR → Task 8. Cloudflare Tunnel + Access → Task 13.
- GitOps via Flux + SOPS → Task 14. Namespace `flight-tracker` → Task 9.
- Deferred (buy-recommendation, price-drop alert) → intentionally out of v1, not tasked.

**Type consistency** — `CheapestResult` (Task 2) is produced by `fetch_cheapest`/`select_cheapest` (Task 3) and consumed by `route_to_record` (Task 2) in `collect` (Task 5). `Record` (Task 2) → `build_point`/`write_records` (Task 4) → `logger.main` (Task 5) and `backfill.main` (Task 7). Env keys `INFLUXDB_URL/TOKEN/ORG/BUCKET` are identical across `influx_config_from_env` (Task 4), Dockerfile run (Task 6), CronJob (Task 10), and backfill Job (Task 12). Datasource `uid: influxdb` (Task 11 Step 3) matches dashboard target `uid` references.

**Placeholder scan** — `GHCR_OWNER`, `GRAFANA_HOST`, `INFLUX_TOKEN/PW/GRAFANA_PW`, `SOPS_RECIPIENT` are user-supplied inputs, each resolved in an explicit step (Tasks 7/12, 9, 12/13, 14), not invented values. No "TBD"/"add error handling"/"similar to above" placeholders remain.

## Known risks / contingencies

- **Fetch from datacenter IP** (Task 1 gate): if bot-challenged or wrong currency, switch to the Playwright Dockerfile variant + proxy. Everything else is unchanged.
- **Scraper drift**: the guard fixes today's break; a future Google layout change may move the patch anchor — `scripts/patch_fast_flights.py` fails loudly if the anchor is gone, and the logger exits non-zero on unpriced-options, so breakage is visible, not silent.
- **local-path storage**: InfluxDB data is pinned to one node and not backed up. Acceptable for a personal tracker; note for future (a periodic `influx backup` to object storage would harden it — deferred).
