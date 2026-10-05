"""Pure gold-accounting rules for Bullion Register.

Everything here is plain arithmetic on simple objects, so it can be unit-tested
without a database. All gold figures are fine (24K-equivalent) grams; all money
is in rupees.

Order life cycle
----------------
* Creating an order issues fine gold to the karigar out of the OWN RESERVE:
      karigar fine = weight x (karigar touch % + karigar wastage %)
* The customer is billed at the order's purity:
      customer fine = weight x (1 + wastage %) x purity %
  The 24K order rate fixes the rupee bill.
* While the order is open, the customer's side is covered three ways:
      cash payments, gold received (old gold / bars) and gold booked with their cash.
  Gold received + gold booked is held as CUSTOMER ADVANCE gold.
* On settlement the whole advance moves into the own reserve. Any part of the
  bill not yet converted into gold is booked at the settlement-day rate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

KARAT_PURITY = {"24": 99.9, "22": 91.6, "20": 83.3, "18": 75.0, "14": 58.5}

DEFAULT_SETTINGS: dict[str, Any] = {
    "today_rate": 0.0,
    "today_date": "",
    "alert_pct": 1.5,      # book the rest if the rate moves this much from the order rate
    "lock_days": 2,        # cash advance must be booked into gold within this many days
    "max_open_g": 25.0,    # limit on unbooked gold across all orders
    "adv_pct": 50.0,       # minimum advance as % of bill
    "c_wastage": 0.0,
    "c_labour": 0.0,
    "k_wastage": 0.0,
    "k_labour": 0.0,
    "labour_to_gold": False,
    "touch": {k: {"c": v, "k": {"24": 100.0, "22": 92.0, "20": 84.0, "18": 76.0, "14": 60.0}[k]}
              for k, v in KARAT_PURITY.items()},
}


def num(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f and f not in (float("inf"), float("-inf")) else 0.0


def merged_settings(stored: dict | None) -> dict:
    s = dict(DEFAULT_SETTINGS)
    stored = stored or {}
    s.update({k: v for k, v in stored.items() if k != "touch"})
    touch = {k: dict(v) for k, v in DEFAULT_SETTINGS["touch"].items()}
    for k, v in (stored.get("touch") or {}).items():
        touch[k] = {"c": num(v.get("c")), "k": num(v.get("k"))}
    s["touch"] = touch
    return s


# ---------------------------------------------------------------- gold received

def normalize_purity(p: Any) -> float:
    """Purity as a percentage. 70 and 700 both mean 70 % (values above 100 are read as per-mille)."""
    p = num(p)
    return p / 10 if p > 100 else p


@dataclass
class GoldFine:
    purity_pct: float
    net: float
    fine: float


def gold_fine(gross: Any, less: Any = 0, purity: Any = 0, melt: Any = 0) -> GoldFine:
    """Fine gold = (gross - stones) x purity % x (1 - melting loss %)."""
    pur = normalize_purity(purity)
    net = max(num(gross) - num(less), 0.0)
    fine = net * pur / 100 * (1 - num(melt) / 100)
    return GoldFine(purity_pct=pur, net=net, fine=round(fine, 3))


@dataclass
class GoldItem:
    """One piece of old gold: net weight (stones and impurities already removed) × purity × buying rate."""
    desc: str
    net: float
    purity_pct: float
    rate: float

    @property
    def fine(self) -> float:
        return round(self.net * self.purity_pct / 100, 3)

    @property
    def value(self) -> float:
        return self.fine * self.rate


def gold_item(desc: str, net: Any, purity: Any, rate: Any) -> GoldItem:
    return GoldItem(desc=(desc or "").strip(), net=num(net), purity_pct=normalize_purity(purity), rate=num(rate))


def fine_from_permille(gross: Any, purity_permille: Any) -> float:
    return round(num(gross) * num(purity_permille) / 1000, 3)


# ---------------------------------------------------------------- order maths

@dataclass
class OrderCalc:
    tracked: bool
    settled: bool
    weight: float
    rate24: float
    by_rate: bool
    c_touch: float
    charge_wt: float
    cust_fine: float
    k_pct: float
    k_fine: float
    cust_labour: float
    kar_labour: float
    labour_margin: float
    gold_value: float
    labour_gold: float
    to_convert: float
    target_g: float
    bill: float
    cash_received: float
    gold_in_fine: float
    gold_in_value: float
    exchange_g: float
    received: float
    due: float
    cash_booked: float
    booked_g: float
    cash_unbooked: float
    locked_amt: float
    locked_g: float
    uncovered: float
    mark_rate: float
    advance_g: float
    reserve_in: float
    proj_back_g: float
    gain: float
    planned_gain: float
    rate_diff_g: float
    break_even: float | None
    move_pct: float | None
    covered_pct: float | None
    first_payment_date: str | None = None


def _get(o: Any, name: str, default: Any = None) -> Any:
    if isinstance(o, dict):
        return o.get(name, default)
    return getattr(o, name, default)


def order_calc(o: Any, today_rate: float = 0.0) -> OrderCalc:
    """Work out every figure for one order.

    ``o`` needs: weight, rate24, c_mode, c_rate, c_touch, c_wastage, c_labour,
    k_touch, k_wastage, k_labour, labour_to_gold, status, and lists
    payments (amount, date), bookings (amount, rate) and gold_receipts (fine, credit_rate).
    """
    tr = num(today_rate)
    W = num(_get(o, "weight"))
    rate24 = num(_get(o, "rate24"))
    c_rate = num(_get(o, "c_rate"))
    by_rate = _get(o, "c_mode") == "rate" and rate24 > 0 and c_rate > 0
    c_touch = c_rate / rate24 * 100 if by_rate else num(_get(o, "c_touch"))
    charge_wt = W * (1 + num(_get(o, "c_wastage")) / 100)
    cust_fine = charge_wt * c_touch / 100
    k_pct = num(_get(o, "k_touch")) + num(_get(o, "k_wastage"))
    k_fine = W * k_pct / 100
    cust_labour = W * num(_get(o, "c_labour"))
    kar_labour = W * num(_get(o, "k_labour"))
    labour_margin = cust_labour - kar_labour
    tracked = rate24 > 0
    labour_to_gold = bool(_get(o, "labour_to_gold"))
    gold_value = charge_wt * c_rate if by_rate else (cust_fine * rate24 if tracked else 0.0)
    labour_gold = labour_margin / rate24 if labour_to_gold and tracked else 0.0
    to_convert = gold_value + (labour_margin if labour_to_gold else 0.0)
    target_g = cust_fine + labour_gold
    bill = gold_value + cust_labour
    settled = _get(o, "status") == "settled"

    pays = list(_get(o, "payments") or [])
    books = list(_get(o, "bookings") or [])
    golds = list(_get(o, "gold_receipts") or [])

    gold_in_fine = sum(num(_get(g, "fine")) for g in golds)
    gold_in_value = sum(num(_get(g, "fine")) * (num(_get(g, "credit_rate")) or rate24) for g in golds) if tracked else 0.0
    exchange_g = gold_in_fine - gold_in_value / rate24 if tracked else 0.0
    cash_received = sum(num(_get(p, "amount")) for p in pays)
    received = cash_received + gold_in_value
    due = bill - received
    cash_booked = sum(num(_get(b, "amount")) for b in books)
    booked_g = sum(num(_get(b, "amount")) / num(_get(b, "rate")) for b in books if num(_get(b, "rate")) > 0)
    cash_unbooked = max(cash_received - cash_booked, 0.0)
    locked_amt = cash_booked + gold_in_value
    locked_g = booked_g + gold_in_fine
    uncovered = max(to_convert - locked_amt, 0.0) if tracked else 0.0
    mark_rate = tr if tr > 0 else rate24
    advance_g = locked_g if (not settled and tracked) else 0.0
    reserve_in = (locked_g if tracked else target_g) if settled else 0.0
    if tracked:
        proj_back_g = locked_g + (uncovered / mark_rate if uncovered > 0 and mark_rate > 0 else 0.0)
    else:
        proj_back_g = target_g
    gain = proj_back_g - k_fine
    planned_gain = target_g - k_fine
    rate_diff_g = proj_back_g - target_g if tracked else 0.0
    gap = k_fine - locked_g
    break_even = uncovered / gap if tracked and uncovered > 0 and gap > 0 else None
    move_pct = (tr - rate24) / rate24 * 100 if tracked and tr > 0 else None
    covered_pct = min(locked_amt / to_convert, 1.0) * 100 if tracked and to_convert > 0 else None
    pay_dates = sorted(str(_get(p, "date")) for p in pays if _get(p, "date"))

    return OrderCalc(
        tracked=tracked, settled=settled, weight=W, rate24=rate24, by_rate=by_rate, c_touch=c_touch,
        charge_wt=charge_wt, cust_fine=cust_fine, k_pct=k_pct, k_fine=k_fine, cust_labour=cust_labour,
        kar_labour=kar_labour, labour_margin=labour_margin, gold_value=gold_value, labour_gold=labour_gold,
        to_convert=to_convert, target_g=target_g, bill=bill, cash_received=cash_received,
        gold_in_fine=gold_in_fine, gold_in_value=gold_in_value, exchange_g=exchange_g, received=received,
        due=due, cash_booked=cash_booked, booked_g=booked_g, cash_unbooked=cash_unbooked,
        locked_amt=locked_amt, locked_g=locked_g, uncovered=uncovered, mark_rate=mark_rate,
        advance_g=advance_g, reserve_in=reserve_in, proj_back_g=proj_back_g, gain=gain,
        planned_gain=planned_gain, rate_diff_g=rate_diff_g, break_even=break_even, move_pct=move_pct,
        covered_pct=covered_pct, first_payment_date=pay_dates[0] if pay_dates else None,
    )


def book_share(c: OrderCalc, amount: float) -> float:
    """Gold share of a cash amount (labour part stays cash), capped at what is still to book."""
    amount = num(amount)
    share = amount * c.to_convert / c.bill if c.bill else amount
    return float(round(max(min(share, c.uncovered), 0.0)))


# ---------------------------------------------------------------- totals

@dataclass
class Totals:
    bullion: float = 0.0
    bullion_in: float = 0.0
    bullion_out: float = 0.0
    k_out: float = 0.0
    reserve_in: float = 0.0
    deployed: float = 0.0
    advance_g: float = 0.0
    gold_in: float = 0.0
    booked: float = 0.0
    cash_unbooked: float = 0.0
    earned: float = 0.0
    pending: float = 0.0
    open_n: int = 0
    settled_n: int = 0
    exposure_amt: float = 0.0
    exposure_g: float = 0.0
    rate_diff: float = 0.0
    labour: float = 0.0

    @property
    def available(self) -> float:
        """Own reserve = bullion lodged - gold issued to karigars + gold back from settled orders."""
        return self.bullion - self.k_out + self.reserve_in

    @property
    def total_in_hand(self) -> float:
        return self.available + self.advance_g

    @property
    def expected_after_settlement(self) -> float:
        return self.available + self.deployed + self.pending


def totals(ledger: Iterable[Any], calcs: Iterable[OrderCalc]) -> Totals:
    t = Totals()
    for e in ledger:
        f = num(_get(e, "fine"))
        if _get(e, "type") == "out":
            t.bullion -= f
            t.bullion_out += f
        else:
            t.bullion += f
            t.bullion_in += f
    for c in calcs:
        t.k_out += c.k_fine
        t.reserve_in += c.reserve_in
        t.exposure_amt += c.uncovered
        if c.mark_rate > 0:
            t.exposure_g += c.uncovered / c.mark_rate
        if c.settled:
            t.earned += c.gain
            t.rate_diff += c.rate_diff_g
            t.labour += c.labour_margin
            t.settled_n += 1
        else:
            t.deployed += c.k_fine
            t.pending += c.gain
            t.open_n += 1
            t.advance_g += c.advance_g
            if c.tracked:
                t.gold_in += c.gold_in_fine
                t.booked += c.booked_g
                t.cash_unbooked += c.cash_unbooked
    return t


# ---------------------------------------------------------------- alerts (the SOP)

@dataclass
class Alert:
    severity: str          # crit | warn | good | info
    message: str
    order_id: int | None = None
    action: str = ""       # book | open | edit | rate


SEVERITY_RANK = {"crit": 0, "warn": 1, "good": 2, "info": 3}


def _days_between(a: str | None, b: date) -> int:
    if not a:
        return 0
    try:
        return (b - date.fromisoformat(str(a)[:10])).days
    except ValueError:
        return 0


def alerts(orders: Iterable[tuple[Any, OrderCalc]], settings: dict, today: date) -> list[Alert]:
    s = merged_settings(settings)
    tr = num(s["today_rate"])
    out: list[Alert] = []
    orders = list(orders)
    if orders and (not tr or s.get("today_date") != today.isoformat()):
        last = s.get("today_date") or ""
        try:
            last = date.fromisoformat(last).strftime("%d %b %Y")
        except ValueError:
            pass
        msg = (f"Today's rate is not entered yet. The last rate (₹{tr:,.0f}) is from {last}."
               if tr else "Enter today's 24K rate to see rate risk on open orders.")
        out.append(Alert("warn", msg, action="rate"))
    exp_g = 0.0
    for o, c in orders:
        oid, label = _get(o, "id"), f"Order {_get(o, 'order_no')}"
        if not c.tracked:
            if not c.settled:
                out.append(Alert("info", f"{label} has no order rate, so advances and rate risk aren't tracked. "
                                         "Edit it and add the 24K rate you fixed.", oid, "edit"))
            continue
        if c.uncovered < 1:
            continue
        if c.mark_rate > 0:
            exp_g += c.uncovered / c.mark_rate
        loss_g = c.uncovered / c.rate24 - c.uncovered / tr if tr > 0 else 0.0
        if c.settled:
            out.append(Alert("crit", f"{label} is settled but ₹{c.uncovered:,.0f} is still not booked into gold. "
                                     "Book it today.", oid, "open"))
            continue
        if c.break_even and tr > 0 and tr >= c.break_even * 0.97:
            out.append(Alert("crit", f"{label}: today's rate is within 3% of break-even (₹{c.break_even:,.0f}). "
                                     f"Book the remaining ₹{c.uncovered:,.0f} now.", oid, "book"))
            continue
        if c.move_pct is not None and c.move_pct >= s["alert_pct"]:
            out.append(Alert("warn", f"{label}: rate is {c.move_pct:+.2f}% above the order rate. The unbooked "
                                     f"₹{c.uncovered:,.0f} has already lost {loss_g:.3f} g. SOP: book the rest now.",
                             oid, "book"))
            continue
        if c.move_pct is not None and c.move_pct <= -s["alert_pct"]:
            out.append(Alert("good", f"{label}: rate is {c.move_pct:+.2f}% below the order rate. Booking the "
                                     f"remaining ₹{c.uncovered:,.0f} now earns {-loss_g:.3f} g extra.", oid, "book"))
            continue
        if c.cash_unbooked >= 1:
            days = _days_between(c.first_payment_date, today)
            if days >= num(s["lock_days"]):
                out.append(Alert("warn", f"{label}: ₹{c.cash_unbooked:,.0f} cash advance not booked into gold for "
                                         f"{days} days. SOP: book within {int(num(s['lock_days']))} days.", oid, "book"))
    if exp_g > num(s["max_open_g"]):
        out.append(Alert("warn", f"Money still to be booked across orders is about {exp_g:.3f} g, above your limit "
                                 f"of {num(s['max_open_g']):g} g. Book the oldest orders first."))
    return sorted(out, key=lambda a: SEVERITY_RANK[a.severity])


# ---------------------------------------------------------------- reserve statement

@dataclass
class StatementLine:
    date: str
    label: str
    gold_in: float
    gold_out: float
    balance: float = 0.0
    ledger_id: int | None = None
    order_id: int | None = None
    sort_key: tuple = field(default_factory=tuple)


def statement(ledger: Iterable[Any], orders: Iterable[tuple[Any, OrderCalc]]) -> list[StatementLine]:
    """Own-reserve statement, newest first, with a running balance."""
    lines: list[StatementLine] = []
    for e in ledger:
        f = num(_get(e, "fine"))
        out = _get(e, "type") == "out"
        lines.append(StatementLine(str(_get(e, "date")), _get(e, "note") or ("Withdrawal" if out else "Bullion added"),
                                   0.0 if out else f, f if out else 0.0, ledger_id=_get(e, "id"),
                                   sort_key=(str(_get(e, "date")), 0, _get(e, "id") or 0)))
    for o, c in orders:
        lines.append(StatementLine(str(_get(o, "date")), f"Issued to {_get(o, 'karigar') or 'karigar'} · order {_get(o, 'order_no')}",
                                   0.0, c.k_fine, order_id=_get(o, "id"),
                                   sort_key=(str(_get(o, "date")), 1, _get(o, "id") or 0)))
        if c.settled:
            d = str(_get(o, "settled_date") or _get(o, "date"))
            lines.append(StatementLine(d, f"Settled · order {_get(o, 'order_no')} · advances moved in · gain {c.gain:+.3f} g",
                                       c.reserve_in, 0.0, order_id=_get(o, "id"),
                                       sort_key=(d, 2, _get(o, "id") or 0)))
    lines.sort(key=lambda l: l.sort_key)
    bal = 0.0
    for l in lines:
        bal += l.gold_in - l.gold_out
        l.balance = bal
    return list(reversed(lines))
