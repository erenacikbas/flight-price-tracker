# ✈️ Flight Price Tracker

Logs flight prices for your routes **every 15 minutes** and serves a live **web dashboard** — all free, running entirely in GitHub's cloud. Nothing needs to stay open on your computer.

## How it works

```
GitHub Actions (cron */15)  ->  logger.py  ->  Google Flights (fast-flights)
        |                                              |
        v                                              v
   git commit  <-------------------------------  data/prices.csv
        |
        v
   GitHub Pages serves index.html  ->  your public dashboard URL
```

- **logger.py** — reads `routes.json`, fetches the cheapest fare per route, appends a row to `data/prices.csv`.
- **.github/workflows/track.yml** — runs the logger every 15 minutes and commits the new data.
- **index.html** — a static dashboard (Chart.js) that reads `data/prices.csv` and shows price-over-time charts, per-route cards, and a latest-snapshot table.

No API keys, no server, no cost (public repo).

---

## Setup (about 5 minutes)

### 1. Create the repo
Create a new **public** GitHub repo (public = free Actions minutes + free Pages), then upload every file in this folder, preserving the structure:

```
routes.json
requirements.txt
logger.py
index.html
data/prices.csv
.github/workflows/track.yml
```

Easiest via the terminal:
```bash
cd flight-price-tracker
git init && git add . && git commit -m "flight price tracker"
git branch -M main
git remote add origin https://github.com/<you>/flight-price-tracker.git
git push -u origin main
```

### 2. Allow the workflow to commit data
Repo **Settings → Actions → General → Workflow permissions** → select **Read and write permissions** → Save.

### 3. Turn on the dashboard (GitHub Pages)
Repo **Settings → Pages** → Source: **Deploy from a branch** → Branch: **main**, folder **/ (root)** → Save.
After a minute your dashboard is live at:
```
https://<you>.github.io/flight-price-tracker/
```

### 4. Kick off the first run
Repo **Actions** tab → **Track flight prices** → **Run workflow**. After that it runs automatically every 15 minutes and the dashboard fills in over time.

---

## Editing your routes

Open `routes.json` and change the `routes` list. Use IATA airport codes.

```json
{
  "currency": "EUR",
  "seat": "economy",
  "adults": 1,
  "routes": [
    { "id": "IST-LHR", "origin": "IST", "destination": "LHR",
      "depart_date": "2026-09-15", "trip": "one-way" },

    { "id": "IST-JFK", "origin": "IST", "destination": "JFK",
      "depart_date": "2026-10-01", "return_date": "2026-10-10", "trip": "round-trip" }
  ]
}
```

- `trip` is `"one-way"` or `"round-trip"` (round-trip needs `return_date`).
- `seat`: `economy`, `premium-economy`, `business`, or `first`.
- `currency`: e.g. `EUR`, `USD`, `GBP`, `TRY`.
- `id` is just the label shown on the dashboard — keep it stable so history lines up.

Commit the change and the next run picks it up. **Note:** the seeded `data/prices.csv` contains a few example rows so the dashboard renders before your first real run — delete those rows (keep the header) once real data starts flowing if you want a clean chart.

---

## Buy-timing analysis (when to pull the trigger)

The dashboard turns the raw log into a **Buy / Good / Hold / Wait** recommendation so you buy near the bottom instead of guessing. It's computed from your own collected history plus the departure date:

- **Buy now** — current fare is at/within 2% of the lowest we've ever logged, *or* you're ≤ 21 days out and at/below the median (close-in fares usually climb).
- **Good price** — cheaper than 75%+ of all readings.
- **Hold** — sitting around the typical level.
- **Wait** — pricier than 75%+ of readings; it has room to fall.

It also shows lowest/median/highest seen, a price gauge (where today sits between cheapest and priciest), potential savings vs. the highest reading, and **days to departure**.

**Booking-window context for this route (IST → Bali/DPS):** for Asia/Oceania, the cheapest fares typically land **~2–6 months before departure** (some sources say 5–7). Your Oct 26, 2026 date is ~3.5 months out — you're **inside that window now**, so the smart play is to let the tracker run and jump on a clear dip rather than waiting for a big drop that historically gets less likely as departure approaches.

> The recommendation gets sharper as more data accumulates — a day or two of 15-min logging gives it a real price range to reason about.

## Run it locally (optional)

```bash
pip install -r requirements.txt
python logger.py      # appends one row per route to data/prices.csv
# open index.html through a local server so it can fetch the CSV:
python -m http.server 8000   # then visit http://localhost:8000
```

---

## Good to know / limitations

- **Cadence:** GitHub's scheduled workflows target every 15 min but can be **delayed or occasionally skipped** during peak load — normal for the free tier. Expect roughly-15-min spacing, not to-the-second.
- **Keep-alive:** GitHub disables scheduled workflows after **60 days of no repo activity**. The tracker commits data on every run, so it keeps itself alive as long as it's running.
- **Data source:** `fast-flights` reads Google Flights. If Google changes their page, the library may need a `pip` update (`fast-flights>=2.2` in requirements) — bump the version if runs start failing.
- **"No priced options"** can happen for sold-out/date-too-far routes; the logger skips those rather than writing a bad row.
- **Currency:** all routes in one config share one currency (the dashboard assumes this).

---

## Files

| File | Purpose |
|------|---------|
| `logger.py` | Fetches prices, writes `data/prices.csv` |
| `routes.json` | Your routes + currency/seat config |
| `requirements.txt` | Python deps (`fast-flights`) |
| `.github/workflows/track.yml` | 15-min schedule + auto-commit |
| `index.html` | The web dashboard |
| `data/prices.csv` | The append-only price log |
