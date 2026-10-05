from __future__ import annotations

import json
from datetime import datetime

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for

from . import calc, services as svc
from .auth import login_required
from .filters import g3, inr, sg3
from .services import ValidationError

bp = Blueprint("main", __name__)


def _back(default: str):
    ref = request.form.get("next") or request.args.get("next") or ""
    return redirect(ref if ref.startswith("/") and not ref.startswith("//") else default)


def _order_or_404(order_id: int):
    try:
        return svc.get_order(order_id)
    except LookupError:
        abort(404)


# ---------------------------------------------------------------- dashboard

@bp.get("/")
@login_required
def dashboard():
    st = svc.dashboard_state()
    open_pairs = [(o, c) for o, c in st["pairs"] if not c.settled]
    return render_template("dashboard.html", **st, open_pairs=open_pairs, today=svc.today().isoformat(),
                           sel_order=request.args.get("order", type=int), sel_kind=request.args.get("kind", "cash"))


@bp.post("/rate")
@login_required
def set_rate():
    try:
        svc.set_today_rate(request.form.get("rate"))
        flash(f"Today's rate set to ₹{calc.num(request.form.get('rate')):,.0f}.")
    except ValidationError as e:
        flash(str(e), "error")
    return _back(url_for("main.dashboard"))


@bp.post("/advances/record")
@login_required
def record_advance():
    f = request.form
    order_id = f.get("order_id", type=int)
    if not order_id:
        flash("Choose an open order first.", "error")
        return _back(url_for("main.dashboard"))
    o = _order_or_404(order_id)
    if o.status == "settled":
        flash("That order is already settled.", "error")
        return _back(url_for("main.dashboard"))
    kind, d = f.get("kind", "cash"), f.get("date") or svc.today().isoformat()
    try:
        if kind == "gold":
            rows = svc.record_gold(o, d, f)
            fine = sum(r.fine for r in rows)
            value = sum(r.fine * (r.credit_rate or o.rate24) for r in rows)
            n = len(rows)
            flash(f"{n} old-gold item{'s' if n != 1 else ''} received for order {o.order_no}: "
                  f"{g3(fine)} g fine, credited {inr(value)}.")
        elif kind == "book":
            b = svc.record_booking(o, d, f.get("book_amount"), f.get("rate"))
            flash(f"{g3(b.grams)} g booked into order {o.order_no}'s advance.")
        else:
            p, b = svc.record_cash(o, d, f.get("cash_amount"), f.get("book_now") == "on", f.get("rate"))
            flash(f"{inr(p.amount)} cash recorded for order {o.order_no}." + (f" {g3(b.grams)} g booked into advances." if b else ""))
    except ValidationError as e:
        flash(str(e), "error")
    return _back(url_for("main.dashboard"))


# ---------------------------------------------------------------- orders

@bp.get("/orders")
@login_required
def orders():
    flt, q = request.args.get("f", "all"), request.args.get("q", "").strip().lower()
    st = svc.dashboard_state()
    rows = [(o, c) for o, c in st["pairs"]
            if (flt == "all" or (flt == "settled") == c.settled)
            and (not q or q in " ".join([o.order_no, o.customer or "", o.karigar or "", o.item or ""]).lower())]
    return render_template("orders.html", rows=rows, flt=flt, q=request.args.get("q", ""), settings=st["settings"])


def _order_form_defaults() -> dict:
    s = svc.get_settings()
    t = s["touch"]["22"]
    return {"date": svc.today().isoformat(), "karat": "22", "rate24": s["today_rate"] or "", "c_mode": "touch",
            "c_touch": t["c"], "k_touch": t["k"], "c_wastage": s["c_wastage"], "c_labour": s["c_labour"],
            "k_wastage": s["k_wastage"], "k_labour": s["k_labour"], "labour_to_gold": s["labour_to_gold"],
            "book_adv": True, "gin_purity": "", "adv_cash": "", "book_amt": "", "book_rate": ""}


@bp.route("/orders/new", methods=["GET", "POST"])
@login_required
def new_order():
    if request.method == "POST":
        try:
            o = svc.create_order(request.form)
            flash(f"{g3(calc.order_calc(o).k_fine)} g fine deployed to order {o.order_no}.")
            return redirect(url_for("main.order_detail", order_id=o.id))
        except ValidationError as e:
            f = request.form
            gin_rows = [{"desc": d, "net": n, "purity": p, "rate": r} for d, n, p, r in
                        zip(f.getlist("gin_item_desc"), f.getlist("gin_item_net"), f.getlist("gin_item_purity"), f.getlist("gin_item_rate"))]
            return render_template("order_form.html", v=f.to_dict(), error=str(e), editing=None,
                                   settings=svc.get_settings(), gin_rows=gin_rows), 400
    return render_template("order_form.html", v=_order_form_defaults(), error=None, editing=None, settings=svc.get_settings())


@bp.route("/orders/<int:order_id>/edit", methods=["GET", "POST"])
@login_required
def edit_order(order_id: int):
    o = _order_or_404(order_id)
    if request.method == "POST":
        try:
            svc.update_order(o, request.form)
            flash(f"Order {o.order_no} updated.")
            return redirect(url_for("main.order_detail", order_id=o.id))
        except ValidationError as e:
            return render_template("order_form.html", v=request.form.to_dict(), error=str(e), editing=o,
                                   settings=svc.get_settings()), 400
    v = {k: getattr(o, k) for k in svc.ORDER_FIELDS_FLOAT + svc.ORDER_FIELDS_TEXT + ["c_mode", "labour_to_gold"]}
    return render_template("order_form.html", v=v, error=None, editing=o, settings=svc.get_settings())


@bp.get("/orders/<int:order_id>")
@login_required
def order_detail(order_id: int):
    o = _order_or_404(order_id)
    s = svc.get_settings()
    c = calc.order_calc(o, s["today_rate"])
    return render_template("order_detail.html", o=o, c=c, settings=s, today=svc.today().isoformat(),
                           rate_now=s["today_rate"] or o.rate24)


@bp.post("/orders/<int:order_id>/delete")
@login_required
def delete_order(order_id: int):
    o = _order_or_404(order_id)
    no = o.order_no
    svc.delete_order(o)
    flash(f"Order {no} deleted.")
    return redirect(url_for("main.orders"))


@bp.post("/orders/<int:order_id>/book")
@login_required
def book_gold(order_id: int):
    o = _order_or_404(order_id)
    try:
        b = svc.record_booking(o, request.form.get("date"), request.form.get("amount"), request.form.get("rate"))
        flash(f"{g3(b.grams)} g booked into order {o.order_no}'s advance.")
    except ValidationError as e:
        flash(str(e), "error")
    return redirect(url_for("main.order_detail", order_id=o.id))


@bp.post("/orders/<int:order_id>/settle")
@login_required
def settle(order_id: int):
    o = _order_or_404(order_id)
    try:
        c = svc.settle(o, request.form.get("date"), request.form.get("amount"), request.form.get("rate"))
        flash(f"Order {o.order_no} settled: {g3(c.reserve_in)} g moved to your reserve, gain {sg3(c.gain)} g.")
    except ValidationError as e:
        flash(str(e), "error")
    return redirect(url_for("main.order_detail", order_id=o.id))


@bp.post("/orders/<int:order_id>/reopen")
@login_required
def reopen(order_id: int):
    o = _order_or_404(order_id)
    svc.reopen(o)
    flash(f"Order {o.order_no} reopened. Its advances are held again.")
    return redirect(url_for("main.order_detail", order_id=o.id))


@bp.post("/orders/<int:order_id>/<kind>/<int:child_id>/delete")
@login_required
def delete_child(order_id: int, kind: str, child_id: int):
    o = _order_or_404(order_id)
    try:
        svc.delete_child(o, kind, child_id)
        flash("Entry deleted.")
    except ValidationError as e:
        flash(str(e), "error")
    return redirect(url_for("main.order_detail", order_id=o.id))


# ---------------------------------------------------------------- advances, reserve, SOP

@bp.get("/advances")
@login_required
def advances():
    st = svc.dashboard_state()
    open_rows = [(o, c) for o, c in st["pairs"] if not c.settled and c.tracked]
    entries = []
    for o, c in st["pairs"]:
        if not c.tracked:
            continue
        for p in o.payments:
            entries.append({"date": p.date, "o": o, "type": "Cash received", "detail": p.note, "amount": p.amount, "g": None, "settled": c.settled})
        for g in o.gold_receipts:
            entries.append({"date": g.date, "o": o, "type": "Gold received", "detail": g, "amount": g.fine * (g.credit_rate or c.rate24),
                            "g": g.fine, "settled": c.settled})
        for b in o.bookings:
            entries.append({"date": b.date, "o": o, "type": "Gold booked", "detail": f"{inr(b.amount)} @ ₹{b.rate:,.0f}",
                            "amount": b.amount, "g": b.grams, "settled": c.settled})
    entries.sort(key=lambda e: e["date"], reverse=True)
    return render_template("advances.html", rows=open_rows, entries=entries, totals=st["totals"])


@bp.route("/reserve", methods=["GET", "POST"])
@login_required
def reserve():
    if request.method == "POST":
        try:
            e = svc.add_ledger(request.form.get("type", "in"), request.form.get("date"), request.form.get("gross"),
                               request.form.get("purity"), request.form.get("note", ""))
            flash(("Added " if e.type == "in" else "Withdrew ") + f"{g3(e.fine)} g fine.")
        except ValidationError as e:
            flash(str(e), "error")
        return redirect(url_for("main.reserve"))
    st = svc.dashboard_state()
    lines = calc.statement(svc.all_ledger(), st["pairs"])
    return render_template("reserve.html", lines=lines, totals=st["totals"], today=svc.today().isoformat())


@bp.post("/reserve/<int:entry_id>/delete")
@login_required
def delete_ledger(entry_id: int):
    svc.delete_ledger(entry_id)
    flash("Entry deleted.")
    return redirect(url_for("main.reserve"))


@bp.get("/sop")
@login_required
def sop():
    return render_template("sop.html", s=svc.get_settings())


# ---------------------------------------------------------------- settings & backup

@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        f = request.form
        touch = {k: {"c": calc.num(f.get(f"c_{k}")), "k": calc.num(f.get(f"k_{k}"))} for k in calc.KARAT_PURITY}
        svc.save_settings({
            "touch": touch, "alert_pct": calc.num(f.get("alert_pct")), "lock_days": calc.num(f.get("lock_days")),
            "max_open_g": calc.num(f.get("max_open_g")), "adv_pct": calc.num(f.get("adv_pct")),
            "c_wastage": calc.num(f.get("c_wastage")), "c_labour": calc.num(f.get("c_labour")),
            "k_wastage": calc.num(f.get("k_wastage")), "k_labour": calc.num(f.get("k_labour")),
            "labour_to_gold": f.get("labour_to_gold") == "on",
        })
        flash("Defaults saved.")
        return redirect(url_for("main.settings"))
    return render_template("settings.html", s=svc.get_settings(), karats=list(calc.KARAT_PURITY))


@bp.get("/backup/export.json")
@login_required
def export_json():
    body = json.dumps(svc.export_json(), indent=2, default=str)
    name = f"bullion-register-backup-{datetime.now():%Y-%m-%d}.json"
    return Response(body, mimetype="application/json", headers={"Content-Disposition": f"attachment; filename={name}"})


@bp.get("/backup/orders.csv")
@login_required
def export_csv():
    name = f"bullion-register-orders-{datetime.now():%Y-%m-%d}.csv"
    return Response(svc.orders_csv(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={name}"})


@bp.post("/backup/import")
@login_required
def import_backup():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Choose a backup file (.json) to import.", "error")
        return redirect(url_for("main.settings"))
    try:
        data = json.load(file.stream)
        counts = svc.import_json(data, replace=request.form.get("replace") == "on")
        flash(f"Imported {counts['orders']} orders and {counts['ledger']} bullion entries.")
    except (json.JSONDecodeError, UnicodeDecodeError):
        flash("That file isn't valid JSON. Use a backup exported from Bullion Book.", "error")
    except ValidationError as e:
        flash(str(e), "error")
    return redirect(url_for("main.settings"))


# ---------------------------------------------------------------- live previews (HTML fragments)

class _FormOrder:
    """Wrap a submitted order form so calc.order_calc can read it like an Order."""

    def __init__(self, form):
        v = svc.order_values(form)
        self.__dict__.update(v)
        self.status = "open"
        self.payments, self.bookings, self.gold_receipts = [], [], []
        try:
            self.gin_items = svc.gold_items_from_form(form, "gin_", v["rate24"])
        except ValidationError:
            self.gin_items = []  # half-typed row: the preview ignores it, saving will explain
        for it in self.gin_items:
            self.gold_receipts.append({"fine": it.fine, "credit_rate": it.rate})
        self.adv_cash = calc.num(form.get("adv_cash"))
        if self.adv_cash > 0:
            self.payments.append({"amount": self.adv_cash, "date": v["date"]})
        if form.get("book_adv") in ("on", "true", "1") and self.adv_cash > 0:
            # Same fallbacks as services.create_order: order rate, and the gold share of the cash.
            rate = calc.num(form.get("book_rate")) or v["rate24"]
            amt = calc.num(form.get("book_amt")) or calc.book_share(calc.order_calc(self), self.adv_cash)
            if amt > 0 and rate > 0:
                self.bookings.append({"amount": amt, "rate": rate})


@bp.post("/api/preview/order")
@login_required
def preview_order():
    s = svc.get_settings()
    fo = _FormOrder(request.form)
    c = calc.order_calc(fo, s["today_rate"])
    bare = calc.order_calc({**fo.__dict__, "payments": [], "bookings": [], "gold_receipts": []})
    t = svc.dashboard_state()["totals"]
    avail = t.available
    editing = request.form.get("editing", type=int)
    if editing:
        try:
            e = calc.order_calc(svc.get_order(editing))
            avail -= e.reserve_in - e.k_fine
        except LookupError:
            pass
    # Suggested advance: SOP minimum of the bill, less gold already given; book the gold share of that cash.
    gin_value = sum(it.value for it in fo.gin_items)
    sugg_cash = max(round(bare.bill * s["adv_pct"] / 100 - gin_value), 0) if bare.bill else 0
    adv_for_share = fo.adv_cash or sugg_cash
    sugg_book = round(min(adv_for_share * bare.to_convert / bare.bill, max(bare.to_convert - gin_value, 0))) if bare.bill else 0
    return render_template("_order_working.html", v=fo, c=c, s=s, avail=avail, adv_total=t.advance_g,
                           editing=editing, gin_items=fo.gin_items,
                           sugg_cash=sugg_cash, sugg_book=sugg_book)


@bp.post("/api/preview/advance")
@login_required
def preview_advance():
    f = request.form
    order_id = f.get("order_id", type=int)
    if not order_id:
        return "Pick an order. Cash, gold received and gold booked are held as that customer's advance until you settle the order."
    try:
        o = svc.get_order(order_id)
    except LookupError:
        return "Order not found."
    c = calc.order_calc(o)
    parts = [f"Bill {inr(c.bill)} · received {inr(c.received)} · still to book {inr(c.uncovered)}."]
    kind = f.get("kind", "cash")
    if kind == "gold":
        try:
            items = svc.gold_items_from_form(f, "", c.rate24)
        except ValidationError as e:
            items, parts = [], parts + [str(e)]
        if items:
            fine, value = sum(i.fine for i in items), sum(i.value for i in items)
            extra = fine - value / c.rate24 if c.rate24 else 0
            parts.append(f"{len(items)} item{'s' if len(items) != 1 else ''}: {g3(sum(i.net for i in items))} g net → "
                         f"{g3(fine)} g fine, worth {inr(value)}."
                         + (f" Bought below the order rate, so you keep {sg3(extra)} g extra." if extra > 0.0005 else ""))
        elif len(parts) == 1:
            parts.append("Enter each item's net weight (stones and impurities removed) and purity.")
    elif kind == "cash":
        amt, rate = calc.num(f.get("cash_amount")), calc.num(f.get("rate"))
        if amt and f.get("book_now") == "on":
            share = calc.book_share(c, amt)
            parts.append(f"Books {inr(share)}" + (f" → {g3(share / rate)} g" if rate else "") + " (gold share of this cash; labour part stays cash).")
        elif amt:
            parts.append("This cash stays unbooked until you book it.")
    else:
        amt, rate = calc.num(f.get("book_amount")), calc.num(f.get("rate"))
        if amt and rate:
            parts.append(f"Books {g3(amt / rate)} g into this customer's advance.")
    return " ".join(parts)
