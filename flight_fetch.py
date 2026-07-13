"""Fetch cheapest fare per airline for a route+date from Google Flights via a real
headless browser (Playwright). Unlike the lightweight scraper, a rendered+scrolled
page shows the FULL carrier list (incl. browser-only carriers like Sichuan) and the
true cheapest fares — verified from the cluster's datacenter IP.

The page URL is built with fast-flights' TFS encoder; we inject the SOCS consent
cookie + curr=TRY&gl=TR, wait for the results, expand "more flights", scroll to load
everything, then parse each flight row's text.
"""
import os
import re
import urllib.parse
from contextlib import contextmanager

from fast_flights import create_filter, FlightData, Passengers

DEFAULT_SOCS_VALUE = "CAISHAgBEhJnd3NfMjAyNDA5MTAtMF9SQzEaAmVuIAEaBgiAo7C3Bg"
_PRICE_RE = re.compile(r"TRY\s*([\d,]+)", re.I)
_STOP_RE = re.compile(r"(\d+)\s*stop", re.I)
_TIME_LINE = re.compile(r"^\d{1,2}:\d{2}\s*(AM|PM)", re.I)


def socs_value(cfg: dict) -> str:
    v = cfg.get("google_socs_cookie") or os.environ.get("GOOGLE_SOCS_COOKIE") or DEFAULT_SOCS_VALUE
    return v.split("=", 1)[1] if v.startswith("SOCS=") else v


def flights_url(origin: str, destination: str, date: str, cfg: dict) -> str:
    flt = create_filter(
        flight_data=[FlightData(date=date, from_airport=origin, to_airport=destination)],
        trip="one-way", seat=cfg.get("cabin", "economy"),
        passengers=Passengers(adults=cfg.get("adults", 1)),
    )
    tfs = flt.as_b64().decode("utf-8")
    curr = cfg.get("currency", "TRY").upper()
    gl, hl = cfg.get("gl", "TR"), cfg.get("hl", "en")
    return (f"https://www.google.com/travel/flights?tfs={urllib.parse.quote(tfs)}"
            f"&curr={curr}&hl={hl}&gl={gl}")


def parse_flight_row(text: str):
    """A flight row's inner_text -> (airline, price:int|None, stops:int).

    Row shape: dep_time / arr_time / AIRLINE / duration / route / stops / ... / 'TRY 24,518'.
    """
    lines = [l.strip() for l in text.replace("\xa0", " ").split("\n")]
    lines = [l for l in lines if l and l != "-" and l != "–"]
    price = None
    for l in lines:
        m = _PRICE_RE.search(l)
        if m:
            price = int(m.group(1).replace(",", "")); break
    stops = 0
    for l in lines:
        if "nonstop" in l.lower():
            stops = 0; break
        m = _STOP_RE.search(l)
        if m:
            stops = int(m.group(1)); break
    # airline = first non-time line (skips the two departure/arrival time lines)
    airline = "Unknown"
    non_time = [l for l in lines if not _TIME_LINE.match(l)]
    if non_time:
        airline = non_time[0]
    return airline, price, stops


def rows_to_cheapest(texts) -> dict:
    """{airline: {price, stops}} keeping each airline's cheapest row."""
    out = {}
    for t in texts:
        if "TRY" not in t or ("stop" not in t.lower() and "nonstop" not in t.lower()):
            continue
        airline, price, stops = parse_flight_row(t)
        if price is None or price <= 0 or airline == "Unknown":
            continue
        if airline not in out or price < out[airline]["price"]:
            out[airline] = {"price": price, "stops": stops}
    return out


@contextmanager
def browser(cfg: dict):
    """Yield a Playwright browser context with the consent cookie set."""
    from playwright.sync_api import sync_playwright  # lazy: not needed for unit tests
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(locale="en-US")
        ctx.add_cookies([{"name": "SOCS", "value": socs_value(cfg),
                          "domain": ".google.com", "path": "/"}])
        try:
            yield ctx
        finally:
            b.close()


def fetch_date(ctx, origin: str, destination: str, date: str, cfg: dict) -> dict:
    """Render the results page for one date and return {airline: {price, stops}}."""
    page = ctx.new_page()
    try:
        page.goto(flights_url(origin, destination, date, cfg),
                  wait_until="networkidle", timeout=int(cfg.get("nav_timeout_ms", 70000)))
        page.wait_for_timeout(int(cfg.get("render_wait_ms", 5000)))
        for label in ("View more flights", "more flights"):
            try:
                page.get_by_text(re.compile(label, re.I)).first.click(timeout=3000)
                page.wait_for_timeout(3000)
            except Exception:
                pass
        for _ in range(int(cfg.get("scrolls", 6))):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1000)
        texts = []
        for li in page.query_selector_all("li"):
            try:
                texts.append(li.inner_text())
            except Exception:
                continue
        return rows_to_cheapest(texts)
    finally:
        page.close()


def fetch_date_with_retry(ctx, origin: str, destination: str, date: str, cfg: dict) -> dict:
    """Retry a date if the page came back thin (< min_airlines) — likely under-rendered."""
    min_airlines = int(cfg.get("min_airlines", 3))
    attempts = int(cfg.get("max_attempts", 2))
    best = {}
    for _ in range(attempts):
        res = fetch_date(ctx, origin, destination, date, cfg)
        if len(res) > len(best):
            best = res
        if len(best) >= min_airlines:
            break
    return best
