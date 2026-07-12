from duffel_fetch import _duration_minutes, _offer_info, cheapest_per_airline, fetch_date


def _offer(airline_name, amount, segments=1, duration="PT16H35M", oid="off_1"):
    return {
        "id": oid,
        "owner": {"name": airline_name, "iata_code": "XX"},
        "total_amount": amount,
        "total_currency": "EUR",
        "slices": [{"duration": duration, "segments": [{} for _ in range(segments)]}],
    }


def test_duration_minutes():
    assert _duration_minutes("PT16H35M") == 995
    assert _duration_minutes("PT2H") == 120
    assert _duration_minutes("PT45M") == 45
    assert _duration_minutes("") == 0


def test_offer_info_extracts_fields():
    info = _offer_info(_offer("Qatar Airways", "512.30", segments=2))
    assert info["airline"] == "Qatar Airways"
    assert info["price"] == 512.30
    assert info["currency"] == "EUR"
    assert info["stops"] == 1          # 2 segments -> 1 stop
    assert info["duration_min"] == 995


def test_cheapest_per_airline_keeps_min():
    offers = [
        _offer("Qatar Airways", "600.00", oid="a"),
        _offer("Qatar Airways", "512.30", oid="b"),
        _offer("Emirates", "640.00", oid="c"),
    ]
    out = cheapest_per_airline(offers)
    assert set(out) == {"Qatar Airways", "Emirates"}
    assert out["Qatar Airways"]["price"] == 512.30
    assert out["Qatar Airways"]["offer_id"] == "b"


def test_fetch_date_uses_injected_post_and_reads_offers():
    captured = {}
    def fake_post(body):
        captured["body"] = body
        return {"data": {"offers": [_offer("THAI", "480.00")]}}
    route_cfg = {"cabin": "economy"}
    out = fetch_date("IST", "DPS", "2026-10-26", route_cfg, post=fake_post)
    assert out["THAI"]["price"] == 480.0
    assert captured["body"]["data"]["slices"][0]["departure_date"] == "2026-10-26"
    assert captured["body"]["data"]["cabin_class"] == "economy"
