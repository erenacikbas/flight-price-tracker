from datetime import datetime, timezone, timedelta
from alerter import decide_low_alert, is_stale, should_alert_stale, format_low

NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def test_decide_low_alert_establishes_baseline_without_alerting():
    assert decide_low_alert(34000, None, 1.0) == (False, 34000)


def test_decide_low_alert_fires_on_meaningful_drop():
    # 34000 -> 33000 is ~2.9% < baseline, above 1% threshold
    should, new_state = decide_low_alert(33000, 34000, 1.0)
    assert should is True and new_state == 33000


def test_decide_low_alert_suppresses_tiny_drop_but_lowers_baseline():
    # 34000 -> 33900 is ~0.29% < 1% threshold: no alert, but track the new min
    should, new_state = decide_low_alert(33900, 34000, 1.0)
    assert should is False and new_state == 33900


def test_decide_low_alert_no_change_when_not_lower():
    assert decide_low_alert(34500, 34000, 1.0) == (False, None)


def test_is_stale():
    assert is_stale(NOW - timedelta(minutes=90), NOW, 60) is True
    assert is_stale(NOW - timedelta(minutes=20), NOW, 60) is False
    assert is_stale(None, NOW, 60) is True


def test_should_alert_stale_rate_limits():
    assert should_alert_stale(None, NOW, 3) is True
    assert should_alert_stale(NOW - timedelta(hours=4), NOW, 3) is True
    assert should_alert_stale(NOW - timedelta(hours=1), NOW, 3) is False


def test_format_low_contains_key_facts():
    msg = format_low("IST-DPS", 33000, 34000, "2026-10-26", "AirAsia X", "TRY")
    assert "IST-DPS" in msg and "33,000" in msg and "34,000" in msg
    assert "2026-10-26" in msg and "AirAsia X" in msg
