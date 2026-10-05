"""Database-facing operations: loading, recording advances, settling, backup import/export."""
from __future__ import annotations

import csv
import io
from datetime import date

from sqlalchemy import select

from . import calc
from .models import AppSettings, GoldBooking, GoldReceipt, LedgerEntry, Order, Payment, db


class ValidationError(ValueError):
    """A user-correctable input problem; the message is shown to the user."""


def today() -> date:
    return date.today()


# ---------------------------------------------------------------- settings

def get_settings() -> dict:
    row = db.session.get(AppSettings, 1)
    return calc.merged_settings(row.data if row else None)


def save_settings(values: dict) -> dict:
    row = db.session.get(AppSettings, 1)
    if row is None:
        row = AppSettings(id=1, data={})
        db.session.add(row)
    data = dict(row.data or {})
    data.update(values)
    row.data = data
    db.session.commit()
    return calc.merged_settings(data)


def set_today_rate(rate: float) -> None:
    if calc.num(rate) <= 0:
        raise ValidationError("Enter today's 24K rate.")
    save_settings({"today_rate": calc.num(rate), "today_date": today().isoformat()})


# ---------------------------------------------------------------- loading

def all_orders() -> list[Order]:
    return list(db.session.scalars(select(Order).order_by(Order.date.desc(), Order.id.desc())))


def all_ledger() -> list[LedgerEntry]:
    return list(db.session.scalars(select(LedgerEntry).order_by(LedgerEntry.date, LedgerEntry.id)))


def order_calcs(orders: list[Order] | None = None, settings: dict | None = None):
    settings = settings or get_settings()
    orders = all_orders() if orders is None else orders
    return [(o, calc.order_calc(o, settings["today_rate"])) for o in orders]


def dashboard_state() -> dict:
    s = get_settings()
    pairs = order_calcs(settings=s)
    t = calc.totals(all_ledger(), [c for _, c in pairs])
    return {"settings": s, "pairs": pairs, "totals": t, "alerts": calc.alerts(pairs, s, today())}


def get_order(order_id: int) -> Order:
    o = db.session.get(Order, order_id)
    if o is None:
        raise LookupError("Order not found")
    return o


# ---------------------------------------------------------------- bullion ledger

def add_ledger(entry_type: str, d: str, gross: float, purity: float, note: str = "") -> LedgerEntry:
    gross, purity = calc.num(gross), calc.num(purity)
    if gross <= 0 or purity <= 0:
        raise ValidationError("Enter a weight and purity.")
    if purity <= 100:          # accept % as well as per-mille
        purity *= 10
    e = LedgerEntry(type="out" if entry_type == "out" else "in", date=d or today().isoformat(),
                    gross=gross, purity=purity, fine=calc.fine_from_permille(gross, purity), note=note.strip())
    db.session.add(e)
    db.session.commit()
    return e


def delete_ledger(entry_id: int) -> None:
    e = db.session.get(LedgerEntry, entry_id)
    if e:
        db.session.delete(e)
        db.session.commit()


# ---------------------------------------------------------------- orders

ORDER_FIELDS_FLOAT = ["weight", "rate24", "k_touch", "k_wastage", "k_labour", "c_touch", "c_rate", "c_wastage", "c_labour"]
ORDER_FIELDS_TEXT = ["order_no", "date", "customer", "item", "karigar", "karat", "notes"]


def order_values(form) -> dict:
    v = {k: calc.num(form.get(k)) for k in ORDER_FIELDS_FLOAT}
    v.update({k: (form.get(k) or "").strip() for k in ORDER_FIELDS_TEXT})
    v["c_mode"] = "rate" if form.get("c_mode") == "rate" else "touch"
    v["labour_to_gold"] = form.get("labour_to_gold") in ("on", "true", "1", True)
    v["date"] = v["date"] or today().isoformat()
    return v


def _check_order(v: dict, exclude_id: int | None = None) -> None:
    if not v["order_no"]:
        raise ValidationError("Order number is required.")
    if v["weight"] <= 0:
        raise ValidationError("Net gold weight must be more than 0.")
    if v["rate24"] <= 0:
        raise ValidationError("Enter the 24K order rate you fixed with the customer.")
    q = select(Order).where(db.func.lower(Order.order_no) == v["order_no"].lower())
    if exclude_id:
        q = q.where(Order.id != exclude_id)
    if db.session.scalars(q).first():
        raise ValidationError(f"Order {v['order_no']} already exists.")


def _getlist(form, key: str) -> list:
    return form.getlist(key) if hasattr(form, "getlist") else ([form[key]] if key in form else [])


def gold_items_from_form(form, prefix: str = "", default_rate: float = 0.0) -> list[calc.GoldItem]:
    """Old-gold items from the form's item rows: net weight × purity % = fine, × buying rate = value.

    Blank rows are skipped. A row with a weight but no purity (or the reverse) is an error.
    """
    descs, nets = _getlist(form, prefix + "item_desc"), _getlist(form, prefix + "item_net")
    purities, rates = _getlist(form, prefix + "item_purity"), _getlist(form, prefix + "item_rate")
    items = []
    for i in range(len(nets)):
        net = calc.num(nets[i])
        pur = calc.normalize_purity(purities[i] if i < len(purities) else 0)
        desc = (descs[i] if i < len(descs) else "").strip()
        if net <= 0 and pur <= 0 and not desc:
            continue
        label = desc or f"item {i + 1}"
        if net <= 0:
            raise ValidationError(f"Enter the net weight for {label}.")
        if pur <= 0:
            raise ValidationError(f"Enter the purity for {label}, as % (70) or ‰ (700).")
        rate = calc.num(rates[i] if i < len(rates) else 0) or default_rate
        items.append(calc.gold_item(desc, net, pur, rate))
    return items


def _receipt(item: calc.GoldItem, d: str) -> GoldReceipt:
    return GoldReceipt(date=d, type="Old gold", gross=item.net, less=0, purity_pct=item.purity_pct, melt=0,
                       fine=item.fine, credit_rate=item.rate, note=item.desc)


def create_order(form) -> Order:
    v = order_values(form)
    _check_order(v)
    o = Order(**v, status="open")
    d = v["date"]
    for item in gold_items_from_form(form, "gin_", v["rate24"]):
        o.gold_receipts.append(_receipt(item, d))
    adv = calc.num(form.get("adv_cash"))
    if adv > 0:
        o.payments.append(Payment(date=d, amount=adv, note="Cash advance"))
    if form.get("book_adv") in ("on", "true", "1") and adv > 0:
        rate = calc.num(form.get("book_rate")) or v["rate24"]
        amt = calc.num(form.get("book_amt")) or calc.book_share(calc.order_calc(o), adv)
        if amt > 0 and rate > 0:
            o.bookings.append(GoldBooking(date=d, amount=amt, rate=rate))
    db.session.add(o)
    db.session.commit()
    return o


def update_order(o: Order, form) -> Order:
    v = order_values(form)
    _check_order(v, exclude_id=o.id)
    for k, val in v.items():
        setattr(o, k, val)
    db.session.commit()
    return o


def delete_order(o: Order) -> None:
    db.session.delete(o)
    db.session.commit()


# ---------------------------------------------------------------- advances

def record_cash(o: Order, d: str, amount: float, book_now: bool = False, rate: float = 0) -> tuple[Payment, GoldBooking | None]:
    amount = calc.num(amount)
    if amount <= 0:
        raise ValidationError("Enter the cash amount.")
    if book_now and calc.num(rate) <= 0:
        raise ValidationError("Enter the rate you paid, or untick “Also book gold”.")
    c = calc.order_calc(o)
    p = Payment(date=d or today().isoformat(), amount=amount, note="Cash advance")
    o.payments.append(p)
    b = None
    if book_now:
        share = calc.book_share(c, amount)
        if share > 0:
            b = GoldBooking(date=p.date, amount=share, rate=calc.num(rate))
            o.bookings.append(b)
    db.session.commit()
    return p, b


def record_gold(o: Order, d: str, form, prefix: str = "") -> list[GoldReceipt]:
    items = gold_items_from_form(form, prefix, o.rate24 or 0)
    if not items:
        raise ValidationError("Add at least one old-gold item with its net weight and purity.")
    d = d or today().isoformat()
    rows = [_receipt(item, d) for item in items]
    o.gold_receipts.extend(rows)
    db.session.commit()
    return rows


def record_booking(o: Order, d: str, amount: float, rate: float) -> GoldBooking:
    amount, rate = calc.num(amount), calc.num(rate)
    if amount <= 0 or rate <= 0:
        raise ValidationError("Enter the cash to book and the rate you paid.")
    b = GoldBooking(date=d or today().isoformat(), amount=amount, rate=rate)
    o.bookings.append(b)
    db.session.commit()
    return b


def delete_child(o: Order, kind: str, child_id: int) -> None:
    model = {"payment": Payment, "booking": GoldBooking, "gold": GoldReceipt}.get(kind)
    if model is None:
        raise ValidationError("Unknown entry type.")
    row = db.session.get(model, child_id)
    if row is not None and row.order_id == o.id:
        db.session.delete(row)
        db.session.commit()


def settle(o: Order, d: str, balance_cash: float, rate: float) -> calc.OrderCalc:
    if o.status == "settled":
        raise ValidationError("This order is already settled.")
    c = calc.order_calc(o)
    d = d or today().isoformat()
    if c.tracked and c.uncovered >= 1 and calc.num(rate) <= 0:
        raise ValidationError("Enter the rate you paid for the remaining gold.")
    if calc.num(balance_cash) > 0:
        o.payments.append(Payment(date=d, amount=calc.num(balance_cash), note="Balance at settlement"))
    if c.tracked and c.uncovered >= 1:
        o.bookings.append(GoldBooking(date=d, amount=round(c.uncovered), rate=calc.num(rate)))
    o.status, o.settled_date = "settled", d
    db.session.commit()
    return calc.order_calc(o)


def reopen(o: Order) -> None:
    o.status, o.settled_date = "open", None
    db.session.commit()


# ---------------------------------------------------------------- backup

def export_json() -> dict:
    """Backup in the same shape the browser version of Bullion Book used."""
    orders = {}
    for o in all_orders():
        orders[str(o.id)] = {
            "orderNo": o.order_no, "date": o.date, "customer": o.customer, "item": o.item, "karigar": o.karigar,
            "weight": o.weight, "karat": o.karat, "rate24": o.rate24, "kTouch": o.k_touch, "kWastage": o.k_wastage,
            "kLabour": o.k_labour, "cMode": o.c_mode, "cTouch": o.c_touch, "cRate": o.c_rate, "cWastage": o.c_wastage,
            "cLabour": o.c_labour, "labourToGold": o.labour_to_gold, "notes": o.notes, "status": o.status,
            "settledDate": o.settled_date,
            "payments": [{"date": p.date, "amount": p.amount, "note": p.note} for p in o.payments],
            "locks": [{"date": b.date, "amount": b.amount, "rate": b.rate} for b in o.bookings],
            "goldIn": [{"date": g.date, "type": g.type, "gross": g.gross, "less": g.less, "purityPct": g.purity_pct,
                        "melt": g.melt, "fine": g.fine, "creditRate": g.credit_rate, "note": g.note}
                       for g in o.gold_receipts],
        }
    ledger = {str(e.id): {"type": e.type, "date": e.date, "gross": e.gross, "purity": e.purity, "fine": e.fine,
                          "note": e.note} for e in all_ledger()}
    s = get_settings()
    settings = {"todayRate": s["today_rate"], "todayDate": s["today_date"], "alertPct": s["alert_pct"],
                "lockDays": s["lock_days"], "maxOpenG": s["max_open_g"], "advPct": s["adv_pct"],
                "cWastage": s["c_wastage"], "cLabour": s["c_labour"], "kWastage": s["k_wastage"],
                "kLabour": s["k_labour"], "labourToGold": s["labour_to_gold"], "touch": s["touch"]}
    return {"app": "bullion-register", "version": 1, "orders": orders, "ledger": ledger, "settings": settings}


SETTING_KEYS = {"todayRate": "today_rate", "todayDate": "today_date", "alertPct": "alert_pct", "lockDays": "lock_days",
                "maxOpenG": "max_open_g", "advPct": "adv_pct", "cWastage": "c_wastage", "cLabour": "c_labour",
                "kWastage": "k_wastage", "kLabour": "k_labour", "labourToGold": "labour_to_gold", "touch": "touch"}


def _rows(section) -> list[dict]:
    if isinstance(section, dict):
        return [dict(v, id=k) if isinstance(v, dict) else {} for k, v in section.items()]
    if isinstance(section, list):
        return [r for r in section if isinstance(r, dict)]
    return []


def import_json(data: dict, replace: bool = False) -> dict:
    """Import a backup (from this app or the browser version). Returns counts."""
    if not isinstance(data, dict) or not ({"orders", "ledger", "settings"} & set(data)):
        raise ValidationError("This file is not a Bullion Book backup.")
    if replace:
        for model in (Payment, GoldBooking, GoldReceipt, Order, LedgerEntry):
            db.session.query(model).delete()
    elif db.session.scalars(select(Order)).first() or db.session.scalars(select(LedgerEntry)).first():
        raise ValidationError("You already have records. Tick “Replace all existing records” to import over them.")

    n_ledger = n_orders = 0
    for e in _rows(data.get("ledger")):
        purity = calc.num(e.get("purity")) or 999
        gross = calc.num(e.get("gross"))
        db.session.add(LedgerEntry(type="out" if e.get("type") == "out" else "in", date=str(e.get("date") or today()),
                                   gross=gross, purity=purity,
                                   fine=calc.num(e.get("fine")) or calc.fine_from_permille(gross, purity),
                                   note=str(e.get("note") or "")))
        n_ledger += 1

    for r in _rows(data.get("orders")):
        o = Order(order_no=str(r.get("orderNo") or r.get("id")), date=str(r.get("date") or today()),
                  customer=r.get("customer") or "", item=r.get("item") or "", karigar=r.get("karigar") or "",
                  weight=calc.num(r.get("weight")), karat=str(r.get("karat") or "22"), rate24=calc.num(r.get("rate24")),
                  k_touch=calc.num(r.get("kTouch")), k_wastage=calc.num(r.get("kWastage")), k_labour=calc.num(r.get("kLabour")),
                  c_mode="rate" if r.get("cMode") == "rate" else "touch", c_touch=calc.num(r.get("cTouch")),
                  c_rate=calc.num(r.get("cRate")), c_wastage=calc.num(r.get("cWastage")), c_labour=calc.num(r.get("cLabour")),
                  labour_to_gold=bool(r.get("labourToGold")), notes=r.get("notes") or "",
                  status="settled" if r.get("status") == "settled" else "open", settled_date=r.get("settledDate"))
        for p in r.get("payments") or []:
            o.payments.append(Payment(date=str(p.get("date") or o.date), amount=calc.num(p.get("amount")), note=p.get("note") or "Cash"))
        for b in r.get("locks") or []:
            if calc.num(b.get("rate")) > 0:
                o.bookings.append(GoldBooking(date=str(b.get("date") or o.date), amount=calc.num(b.get("amount")), rate=calc.num(b.get("rate"))))
        for g in r.get("goldIn") or []:
            pct = calc.num(g.get("purityPct")) if g.get("purityPct") is not None else calc.num(g.get("purity")) / 10
            o.gold_receipts.append(GoldReceipt(date=str(g.get("date") or o.date), type=g.get("type") or "Old jewellery",
                                               gross=calc.num(g.get("gross")), less=calc.num(g.get("less")), purity_pct=pct,
                                               melt=calc.num(g.get("melt")), fine=calc.num(g.get("fine")),
                                               credit_rate=calc.num(g.get("creditRate")), note=g.get("note") or ""))
        # Orders settled in the browser version before bookings existed: converted at the order rate.
        if o.status == "settled" and o.rate24 > 0 and r.get("locks") is None:
            c = calc.order_calc(o)
            o.bookings.append(GoldBooking(date=o.settled_date or o.date, amount=round(c.to_convert), rate=o.rate24))
            if r.get("payments") is None:
                o.payments.append(Payment(date=o.settled_date or o.date, amount=round(c.bill), note="Settled (full amount)"))
        db.session.add(o)
        n_orders += 1

    s = data.get("settings") or {}
    if s:
        save_settings({SETTING_KEYS[k]: v for k, v in s.items() if k in SETTING_KEYS})
    db.session.commit()
    return {"orders": n_orders, "ledger": n_ledger}


def orders_csv() -> str:
    s = get_settings()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Order", "Date", "Customer", "Item", "Karigar", "Net wt g", "Purity", "Order rate 24K", "Karigar fine g",
                "Customer fine g", "Planned gain g", "Bill Rs", "Cash received Rs", "Gold received fine g",
                "Gold booked g", "Cash not booked Rs", "Still to book Rs", "Advance gold g", "Gold gain g",
                "Rate diff g", "Labour margin Rs", "Status", "Settled on"])
    for o in sorted(all_orders(), key=lambda x: (x.date, x.id)):
        c = calc.order_calc(o, s["today_rate"])
        w.writerow([o.order_no, o.date, o.customer, o.item, o.karigar, f"{c.weight:.3f}", o.karat_label, f"{c.rate24:.2f}",
                    f"{c.k_fine:.3f}", f"{c.cust_fine:.3f}", f"{c.planned_gain:.3f}", round(c.bill), round(c.cash_received),
                    f"{c.gold_in_fine:.3f}", f"{c.booked_g:.3f}", round(c.cash_unbooked), round(c.uncovered),
                    f"{c.locked_g:.3f}", f"{c.gain:.3f}", f"{c.rate_diff_g:.3f}", round(c.labour_margin),
                    "Settled" if c.settled else "With karigar", o.settled_date or ""])
    return buf.getvalue()
