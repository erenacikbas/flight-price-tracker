#!/usr/bin/env python3
"""Telegram alerter for the flight tracker.

Runs on its own schedule, queries InfluxDB, and pushes two kinds of alert:
  1. New all-time-low fare per route (the buy-signal).
  2. Stale data (the logger stopped writing) — a health alert.

De-duped via an `alert_state` measurement in InfluxDB (no extra storage):
  - per-route `alerted_low` field: the lowest price we've already notified about.
  - `last_stale_ts` field: when we last sent a staleness alert (suppress repeats).

Telegram creds are optional: with none set the run still evaluates and logs what
it *would* send, so the logic is verifiable before the bot token is provisioned.
Exit 0 always (alerting must never crash the schedule); errors go to stderr.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ALERT_MEASUREMENT = "alert_state"


def load_targets(path):
    """{route_id: alert_target} from routes.json; empty if unreadable/none set."""
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return {}
    return {r.get("id"): int(r["alert_target"])
            for r in cfg.get("routes", []) if r.get("alert_target")}


# ---- pure, unit-tested decision logic --------------------------------------

def decide_low_alert(cur_price, state_price, min_drop_pct):
    """Return (should_alert, new_state_or_None) for one route's cheapest fare.

    - No prior state: establish the baseline silently (no alert).
    - New low with drop >= min_drop_pct: alert and lower the baseline.
    - New low below threshold: lower the baseline quietly (no alert).
    - No new low: leave state untouched (None => don't rewrite).
    """
    if cur_price is None:
        return (False, None)
    if state_price is None:
        return (False, cur_price)
    if cur_price < state_price:
        drop_pct = (state_price - cur_price) / state_price * 100.0
        return (drop_pct >= min_drop_pct, cur_price)
    return (False, None)


def decide_target_alert(cur_price, target, already_below):
    """One route's target check. `already_below` = did we alert for the current
    below-target episode. Returns (should_alert, new_state) where new_state is
    True (below+notified), False (reset, back above), or None (no state change).

    Fires once when the price crosses at/below target; re-arms when it goes back above.
    """
    if target is None or cur_price is None:
        return (False, None)
    if cur_price <= target:
        return (not already_below, True)
    return (False, False) if already_below else (False, None)


def format_target(route_id, cur_price, target, depart_date, airline, currency):
    return (f"\U0001f3af <b>{route_id} hit your target!</b>\n"
            f"{int(cur_price):,} {currency} (target {int(target):,})\n"
            f"{depart_date} · {airline}")


def is_stale(last_ts, now, stale_minutes):
    """True if the newest data point is older than stale_minutes (or absent)."""
    if last_ts is None:
        return True
    return (now - last_ts).total_seconds() > stale_minutes * 60


def should_alert_stale(last_alert_ts, now, suppress_hours):
    """Rate-limit staleness alerts: fire only if we haven't within suppress_hours."""
    if last_alert_ts is None:
        return True
    return (now - last_alert_ts).total_seconds() > suppress_hours * 3600


def format_low(route_id, cur_price, prev_price, depart_date, airline, currency):
    saved = prev_price - cur_price
    pct = saved / prev_price * 100.0 if prev_price else 0.0
    return (f"\U0001f4c9 <b>New low: {route_id}</b>\n"
            f"{int(cur_price):,} {currency} (was {int(prev_price):,}, "
            f"-{int(saved):,} / -{pct:.0f}%)\n"
            f"{depart_date} · {airline}")


def format_stale(last_ts, now):
    if last_ts is None:
        age = "no data at all"
    else:
        mins = int((now - last_ts).total_seconds() // 60)
        age = f"last point {mins} min ago"
    return (f"⚠️ <b>Flight tracker data is stale</b>\n{age}. "
            f"The logger CronJob may be failing.")


# ---- IO --------------------------------------------------------------------

def send_telegram(text, token, chat_id):
    """Send an HTML message; no-op (log) when creds are missing."""
    if not token or not chat_id:
        print(f"[telegram not configured] would send:\n{text}\n")
        return False
    data = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=20) as resp:
        resp.read()
    print(f"[telegram sent] {text.splitlines()[0]}")
    return True


def _cfg():
    return {
        "url": os.environ["INFLUXDB_URL"],
        "token": os.environ["INFLUXDB_TOKEN"],
        "org": os.environ["INFLUXDB_ORG"],
        "bucket": os.environ["INFLUXDB_BUCKET"],
    }


def current_cheapest(qapi, bucket):
    """{route_id: (price, depart_date, airline, currency)} over the last 60 min."""
    flux = f'''from(bucket: "{bucket}")
  |> range(start: -60m)
  |> filter(fn: (r) => r._measurement == "flight_price" and r._field == "price")
  |> group(columns: ["route_id", "depart_date", "airline"]) |> last()
  |> group(columns: ["route_id"]) |> min()'''
    out = {}
    for tbl in qapi.query(flux):
        for rec in tbl.records:
            out[rec.values.get("route_id")] = (
                rec.get_value(), rec.values.get("depart_date"),
                rec.values.get("airline"), rec.values.get("currency", "TRY"))
    return out


def last_data_time(qapi, bucket):
    flux = f'''from(bucket: "{bucket}")
  |> range(start: -12h)
  |> filter(fn: (r) => r._measurement == "flight_price" and r._field == "price")
  |> keep(columns: ["_time"]) |> group() |> max(column: "_time")'''
    for tbl in qapi.query(flux):
        for rec in tbl.records:
            return rec.values.get("_time")
    return None


def alert_state(qapi, bucket):
    """Return ({route_id: alerted_low}, last_stale_ts, {route_id: target_state})
    from the alert_state measurement."""
    flux = f'''from(bucket: "{bucket}")
  |> range(start: -60d)
  |> filter(fn: (r) => r._measurement == "{ALERT_MEASUREMENT}")
  |> group(columns: ["route_id", "_field"]) |> last()'''
    lows, stale_ts, targets = {}, None, {}
    for tbl in qapi.query(flux):
        for rec in tbl.records:
            field = rec.values.get("_field")
            if field == "alerted_low":
                lows[rec.values.get("route_id")] = rec.get_value()
            elif field == "last_stale_ts":
                stale_ts = rec.get_value()
            elif field == "target_state":
                targets[rec.values.get("route_id")] = rec.get_value()
    return lows, stale_ts, targets


def main():
    from influxdb_client import InfluxDBClient, Point, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS

    cfg = _cfg()
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    min_drop = float(os.environ.get("MIN_DROP_PCT", "1.0"))
    stale_min = int(os.environ.get("STALE_MINUTES", "60"))
    suppress_h = float(os.environ.get("STALE_SUPPRESS_HOURS", "3"))
    routes_path = os.environ.get("ROUTES_PATH", "routes.json")
    now = datetime.now(timezone.utc)

    client = InfluxDBClient(url=cfg["url"], token=cfg["token"], org=cfg["org"])
    qapi = client.query_api()
    writes = []

    current = current_cheapest(qapi, cfg["bucket"])
    lows, stale_ts, target_states = alert_state(qapi, cfg["bucket"])
    targets = load_targets(routes_path)

    for route_id, (price, depart_date, airline, currency) in sorted(current.items()):
        should, new_state = decide_low_alert(price, lows.get(route_id), min_drop)
        if should:
            send_telegram(format_low(route_id, price, lows[route_id],
                                     depart_date, airline, currency), tg_token, tg_chat)
        if new_state is not None:
            writes.append(Point(ALERT_MEASUREMENT).tag("route_id", route_id)
                          .field("alerted_low", int(new_state)).time(now, WritePrecision.S))

        already_below = target_states.get(route_id) == 1
        t_should, t_state = decide_target_alert(price, targets.get(route_id), already_below)
        if t_should:
            send_telegram(format_target(route_id, price, targets[route_id],
                                        depart_date, airline, currency), tg_token, tg_chat)
        if t_state is not None:
            writes.append(Point(ALERT_MEASUREMENT).tag("route_id", route_id)
                          .field("target_state", 1 if t_state else 0).time(now, WritePrecision.S))

    last_ts = last_data_time(qapi, cfg["bucket"])
    if is_stale(last_ts, now, stale_min) and should_alert_stale(stale_ts, now, suppress_h):
        send_telegram(format_stale(last_ts, now), tg_token, tg_chat)
        writes.append(Point(ALERT_MEASUREMENT)
                      .field("last_stale_ts", int(now.timestamp())).time(now, WritePrecision.S))

    if writes:
        client.write_api(write_options=SYNCHRONOUS).write(bucket=cfg["bucket"], record=writes)
    client.close()
    print(f"Checked {len(current)} route(s); {len(writes)} state write(s).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # alerting must never crash the schedule
        print(f"alerter error: {e}", file=sys.stderr)
        sys.exit(0)
