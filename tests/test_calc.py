"""Gold arithmetic, checked against the worked examples agreed with the owner."""
from datetime import date
from types import SimpleNamespace as NS

import pytest

from app import calc

approx = lambda v, tol=1e-3: pytest.approx(v, abs=tol)  # noqa: E731


def order(**kw):
    base = dict(id=1, order_no="T1", date="2026-10-01", karigar="K", weight=0, rate24=0, c_mode="touch", c_rate=0,
                c_touch=0, c_wastage=0, c_labour=0, k_touch=0, k_wastage=0, k_labour=0, labour_to_gold=False,
                status="open", settled_date=None, payments=[], bookings=[], gold_receipts=[])
    base.update(kw)
    return NS(**base)


# ---------------------------------------------------------------- making margin

def test_20k_order_from_first_example():
    c = calc.order_calc(order(weight=40, c_touch=83.3, c_wastage=10, k_touch=84, k_wastage=2))
    assert c.cust_fine == approx(36.652)
    assert c.k_fine == approx(34.4)
    assert c.planned_gain == approx(2.252)


def test_22k_order_from_first_example():
    c = calc.order_calc(order(weight=50, c_touch=91.6, c_wastage=8, k_touch=92, k_wastage=2))
    assert c.cust_fine == approx(49.464)
    assert c.k_fine == approx(47.0)
    assert c.planned_gain == approx(2.464)


def test_price_by_purity_rate_derives_touch():
    c = calc.order_calc(order(weight=50, rate24=15000, c_mode="rate", c_rate=14250, c_wastage=15, k_touch=92, k_wastage=5))
    assert c.c_touch == approx(95.0)
    assert c.charge_wt == approx(57.5)
    assert c.gold_value == approx(57.5 * 14250)
    assert c.k_fine == approx(48.5)


def test_labour_margin_and_labour_to_gold():
    c = calc.order_calc(order(weight=40, rate24=10000, c_touch=83.3, c_wastage=10, k_touch=84, k_wastage=2,
                              c_labour=500, k_labour=300, labour_to_gold=True))
    assert c.labour_margin == approx(8000)
    assert c.labour_gold == approx(0.8)
    assert c.target_g == approx(36.652 + 0.8)


# ---------------------------------------------------------------- rate risk (the 50 g 22K table)

def _rate_case(settle_rate):
    adv = 247320
    return order(weight=50, rate24=10000, c_touch=91.6, c_wastage=8, k_touch=92, k_wastage=2, status="settled",
                 payments=[NS(amount=adv, date="2026-09-25"), NS(amount=adv, date="2026-10-01")],
                 bookings=[NS(amount=adv, rate=10000), NS(amount=adv, rate=settle_rate)])


@pytest.mark.parametrize("rate,back,gain", [(9500, 50.766, 3.766), (10000, 49.464, 2.464), (10500, 48.286, 1.286)])
def test_settlement_rate_changes_gold_gain(rate, back, gain):
    c = calc.order_calc(_rate_case(rate))
    assert c.uncovered == approx(0, 1)
    assert c.proj_back_g == approx(back)
    assert c.gain == approx(gain)
    assert c.rate_diff_g == approx(gain - 2.464)


def test_break_even_rate_for_half_booked_order():
    o = order(weight=50, rate24=10000, c_touch=91.6, c_wastage=8, k_touch=92, k_wastage=2,
              payments=[NS(amount=247320, date="2026-09-25")], bookings=[NS(amount=247320, rate=10000)])
    c = calc.order_calc(o)
    assert c.uncovered == approx(247320, 1)
    assert c.break_even == pytest.approx(11106.5, abs=1)


def test_open_order_marks_to_todays_rate():
    o = order(weight=50, rate24=10000, c_touch=91.6, c_wastage=8, k_touch=92, k_wastage=2,
              bookings=[NS(amount=247320, rate=10000)])
    c = calc.order_calc(o, today_rate=10500)
    assert c.proj_back_g == approx(48.286)
    assert c.move_pct == approx(5.0)


# ---------------------------------------------------------------- gold received as advance

@pytest.mark.parametrize("gross,less,purity,melt,fine", [
    (30, 0, 70, 0, 21.0),       # owner's case: 70 %
    (30, 0, 700, 0, 21.0),      # same, typed as per-mille
    (32, 2, 70, 0, 21.0),       # stones deducted first
    (30, 0, 70, 2, 20.58),      # melting loss
    (10, 0, 91.6, 0, 9.16),
])
def test_gold_fine(gross, less, purity, melt, fine):
    assert calc.gold_fine(gross, less, purity, melt).fine == approx(fine)


def test_gold_item_net_times_purity_times_rate():
    item = calc.gold_item("Bangle", 30, 70, 15000)
    assert item.fine == approx(21.0)
    assert item.value == approx(315000)
    assert calc.gold_item("Coin", 10, 916, 14500).fine == approx(9.16)  # per-mille accepted


def test_owner_order_01_with_old_gold_and_cash():
    o = order(order_no="01", weight=50, rate24=15000, c_mode="rate", c_rate=14250, c_wastage=15, k_touch=92, k_wastage=5,
              labour_to_gold=True, payments=[NS(amount=150000, date="2026-10-01")],
              bookings=[NS(amount=150000, rate=15000)], gold_receipts=[NS(fine=21.0, credit_rate=15000)])
    c = calc.order_calc(o, today_rate=15000)
    assert c.bill == approx(819375, 0.5)
    assert c.received == approx(465000, 0.5)
    assert c.uncovered == approx(354375, 0.5)
    assert c.gold_in_fine == approx(21)
    assert c.booked_g == approx(10)
    assert c.advance_g == approx(31)
    assert c.reserve_in == 0
    t = calc.totals([NS(type="in", fine=499.5)], [c])
    assert t.k_out == approx(48.5)
    assert t.available == approx(451.0)
    assert t.advance_g == approx(31.0)
    assert t.total_in_hand == approx(482.0)


def test_old_gold_credited_below_order_rate_gives_exchange_margin():
    g = calc.gold_fine(30, 0, 70, 2)
    o = order(weight=50, rate24=15000, c_touch=91.6, k_touch=92, gold_receipts=[NS(fine=g.fine, credit_rate=14000)])
    c = calc.order_calc(o)
    assert c.gold_in_value == approx(288120, 0.5)
    assert c.exchange_g == approx(1.372)


def test_settlement_moves_advances_into_own_reserve():
    o = order(weight=50, rate24=15000, c_touch=91.6, k_touch=92, status="settled",
              bookings=[NS(amount=150000, rate=15000)], gold_receipts=[NS(fine=21, credit_rate=0)])
    c = calc.order_calc(o)
    assert c.advance_g == 0
    assert c.reserve_in == approx(31)


def test_profit_breakdown_adds_up():
    # 50 g 22K: making margin, old gold bought below the order rate, rest booked above it, labour kept as cash
    o = order(weight=50, rate24=10000, c_touch=91.6, c_wastage=8, k_touch=92, k_wastage=2, c_labour=500, k_labour=300,
              status="settled", gold_receipts=[NS(fine=10.0, credit_rate=9800)],
              bookings=[NS(amount=494640 - 98000, rate=10200)])
    c = calc.order_calc(o, today_rate=10300)
    assert c.making_g == approx(2.464)
    assert c.exchange_g == approx(0.2)
    assert c.making_g + c.labour_gold + c.exchange_g + c.market_g == approx(c.gain)
    assert c.labour_cash == approx(10000)
    assert c.profit_inr == approx(c.gain * 10300 + 10000, 0.5)


def test_labour_converted_to_gold_is_not_counted_twice():
    o = order(weight=40, rate24=10000, c_touch=83.3, c_wastage=10, k_touch=84, k_wastage=2, c_labour=500, k_labour=300,
              labour_to_gold=True)
    c = calc.order_calc(o)
    assert c.labour_cash == 0
    assert c.profit_inr == approx((2.252 + 0.8) * 10000, 1)


def test_book_share_excludes_labour():
    o = order(weight=10, rate24=10000, c_touch=91.6, c_labour=500, k_labour=300)
    c = calc.order_calc(o)
    assert c.bill == approx(96600)
    assert calc.book_share(c, 50000) == 47412


def test_untracked_order_returns_billed_fine_on_settlement():
    c = calc.order_calc(order(weight=40, c_touch=83.3, c_wastage=10, k_touch=84, k_wastage=2, status="settled"))
    assert not c.tracked
    assert c.reserve_in == approx(36.652)


def test_normalize_purity():
    assert calc.normalize_purity(70) == 70
    assert calc.normalize_purity(916) == pytest.approx(91.6)
    assert calc.normalize_purity("abc") == 0


# ---------------------------------------------------------------- alerts

def _alerts(o, rate, today="2026-10-05", **settings):
    s = {"today_rate": rate, "today_date": today, **settings}
    return calc.alerts([(o, calc.order_calc(o, rate))], s, date.fromisoformat(today))


def _half_booked(**kw):
    return order(weight=50, rate24=10000, c_touch=91.6, c_wastage=8, k_touch=92, k_wastage=2, date="2026-10-04",
                 payments=[NS(amount=262320, date="2026-10-04")], bookings=[NS(amount=247320, rate=10000)], **kw)


def test_alert_rate_up_tells_owner_to_book():
    a = _alerts(_half_booked(), 10200)
    assert [x.severity for x in a] == ["warn"] and "above the order rate" in a[0].message


def test_alert_rate_down_is_opportunity():
    a = _alerts(_half_booked(), 9800, max_open_g=100)
    assert [x.severity for x in a] == ["good"] and "earns" in a[0].message


def test_alert_near_break_even_is_critical():
    a = _alerts(_half_booked(), 10900)
    assert a[0].severity == "crit" and "break-even" in a[0].message


def test_alert_cash_left_unbooked_too_long():
    o = order(weight=50, rate24=10000, c_touch=91.6, c_wastage=10, k_touch=92, date="2026-10-01",
              payments=[NS(amount=200000, date="2026-10-01")])
    a = _alerts(o, 10000, max_open_g=100)
    assert any("not booked into gold for 4 days" in x.message for x in a)


def test_alert_missing_todays_rate():
    a = _alerts(_half_booked(), 10000, today="2026-10-05")
    a2 = calc.alerts([(o := _half_booked(), calc.order_calc(o, 10000))], {"today_rate": 10000, "today_date": "2026-10-01"},
                     date(2026, 10, 5))
    assert not any(x.action == "rate" for x in a)
    assert a2[0].action == "rate"


def test_alert_settled_but_not_booked():
    o = order(weight=50, rate24=10000, c_touch=91.6, k_touch=92, status="settled")
    a = _alerts(o, 10000)
    assert a[0].severity == "crit" and "settled" in a[0].message


def test_alert_open_position_limit():
    a = _alerts(_half_booked(), 10000, max_open_g=5)
    assert any("above your limit" in x.message for x in a)


# ---------------------------------------------------------------- statement

def test_statement_running_balance():
    ledger = [NS(id=1, type="in", date="2026-10-01", fine=499.5, note="Opening")]
    o = order(weight=50, rate24=15000, c_touch=91.6, k_touch=92, k_wastage=5, status="settled", settled_date="2026-10-03",
              bookings=[NS(amount=150000, rate=15000)], gold_receipts=[NS(fine=21, credit_rate=0)])
    lines = calc.statement(ledger, [(o, calc.order_calc(o))])
    assert [round(l.balance, 3) for l in reversed(lines)] == [499.5, 451.0, 482.0]
