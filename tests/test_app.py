"""End-to-end flows through the web app (Flask test client, temporary SQLite database)."""
import html as html_lib
import io
import json
import re

from app import create_app
from app.models import GoldBooking, GoldReceipt, LedgerEntry, Order, Payment, User, db


def text(r):
    return html_lib.unescape(r.get_data(as_text=True))


def figure(html, element_id):
    m = re.search(r'id="%s">([\d,.\-−]+)<small>' % element_id, html)
    assert m, f"{element_id} not on page"
    return m.group(1)


ORDER_01 = {
    "order_no": "01", "date": "2026-10-01", "customer": "Narayan", "item": "Bangles", "karigar": "Ghanshyam",
    "weight": "50", "karat": "22", "rate24": "15000", "k_touch": "92", "k_wastage": "5", "k_labour": "0",
    "c_mode": "rate", "c_touch": "91.6", "c_rate": "14250", "c_wastage": "15", "c_labour": "0", "labour_to_gold": "on",
    "gin_item_desc": ["Bangles"], "gin_item_net": ["30"], "gin_item_purity": ["70"], "gin_item_rate": ["15000"],
    "adv_cash": "150000", "book_adv": "on", "book_amt": "150000", "book_rate": "15000",
}


# ---------------------------------------------------------------- auth

def test_first_run_setup_then_dashboard(client):
    r = client.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/setup")
    r = client.post("/setup", data={"username": "owner", "password": "short", "confirm": "short"})
    assert "at least 8 characters" in text(r)
    r = client.post("/setup", data={"username": "owner", "password": "gold-secret-1", "confirm": "gold-secret-1"})
    assert r.status_code == 302
    assert client.get("/").status_code == 200
    assert client.get("/setup").status_code == 302  # setup closes once an owner exists


def test_setup_is_blocked_from_the_internet(client):
    r = client.get("/setup", environ_base={"REMOTE_ADDR": "203.0.113.9"})
    assert r.status_code == 403 and "ADMIN_USERNAME" in text(r)


def test_login_required_and_wrong_password(auth_client, client):
    client.post("/logout")
    r = client.get("/orders")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    r = client.post("/login", data={"username": "owner", "password": "nope"})
    assert "Wrong username or password" in text(r)


def test_repeated_wrong_passwords_lock_out(auth_client, client):
    client.post("/logout")
    for _ in range(5):
        client.post("/login", data={"username": "owner", "password": "guess"})
    r = client.post("/login", data={"username": "owner", "password": "gold-secret-1"})
    assert r.status_code == 429 and "Too many wrong attempts" in text(r)


def test_login_does_not_redirect_offsite(auth_client, client):
    client.post("/logout")
    r = client.post("/login?next=//evil.example", data={"username": "owner", "password": "gold-secret-1"})
    assert r.headers["Location"] == "/"


def test_cloud_owner_created_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "very-secret-pw")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "c.db"), "SECRET_KEY": "x"})
    with app.app_context():
        u = db.session.query(User).one()
        assert u.username == "boss" and u.check_password("very-secret-pw")


def test_csrf_is_enforced(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "c.db"), "SECRET_KEY": "x"})
    r = app.test_client().post("/login", data={"username": "a", "password": "b"})
    assert r.status_code == 400


def test_change_password(auth_client, app):
    r = auth_client.post("/account/password", data={"current": "gold-secret-1", "password": "new-secret-22", "confirm": "new-secret-22"})
    assert r.status_code == 302
    with app.app_context():
        assert db.session.query(User).one().check_password("new-secret-22")


# ---------------------------------------------------------------- the owner's full flow

def test_full_flow_reserve_advances_settlement(auth_client, app):
    c = auth_client
    r = c.post("/reserve", data={"type": "in", "date": "2026-10-01", "gross": "500", "purity": "999", "note": "Opening"},
               follow_redirects=True)
    assert "Added 499.500 g fine" in text(r)

    r = c.post("/orders/new", data=ORDER_01, follow_redirects=True)
    assert "48.500 g fine deployed to order 01" in text(r)

    html = text(c.get("/"))
    assert figure(html, "own-reserve") == "451.000"
    assert figure(html, "adv-gold") == "31.000"
    assert figure(html, "total-gold") == "482.000"

    with app.app_context():
        o = db.session.query(Order).one()
        g = o.gold_receipts[0]
        assert g.fine == 21.0 and g.purity_pct == 70
        oid = o.id

    # more gold arrives: a 22K coin bought at a lower rate (purity typed as per-mille)
    r = c.post("/advances/record", data={"order_id": oid, "kind": "gold", "date": "2026-10-02", "item_desc": ["Coin"],
                                         "item_net": ["10"], "item_purity": ["916"], "item_rate": ["14500"]},
               follow_redirects=True)
    assert "1 old-gold item received for order 01: 9.160 g fine, credited ₹1,32,820" in text(r)
    # cash, booked straight into gold
    r = c.post("/advances/record", data={"order_id": oid, "kind": "cash", "date": "2026-10-02", "cash_amount": "50000",
                                         "book_now": "on", "rate": "15200"}, follow_redirects=True)
    assert "₹50,000 cash recorded" in text(r)

    page = text(c.get(f"/orders/{oid}"))
    assert "Customer advances" in page and "Settle order" in page

    # settle: the rest is booked at the settlement rate and everything moves into the own reserve
    r = c.post(f"/orders/{oid}/settle", data={"date": "2026-10-10", "amount": "100000", "rate": "15300"}, follow_redirects=True)
    assert "settled" in text(r)
    with app.app_context():
        o = db.session.get(Order, oid)
        assert o.status == "settled"
        from app import calc
        cc = calc.order_calc(o)
        assert cc.uncovered < 1
        own = 499.5 - cc.k_fine + cc.locked_g
    html = text(c.get("/"))
    assert figure(html, "adv-gold") == "0.000"
    assert figure(html, "own-reserve") == f"{own:.3f}"

    # reopen puts the advance back on hold
    c.post(f"/orders/{oid}/reopen")
    assert figure(text(c.get("/")), "own-reserve") == "451.000"


def test_order_validation(auth_client):
    bad = dict(ORDER_01, rate24="")
    r = auth_client.post("/orders/new", data=bad)
    assert r.status_code == 400 and "24K order rate" in text(r)
    auth_client.post("/orders/new", data=ORDER_01)
    r = auth_client.post("/orders/new", data=ORDER_01)
    assert r.status_code == 400 and "already exists" in text(r)


def test_edit_and_delete_entries(auth_client, app):
    auth_client.post("/orders/new", data=ORDER_01)
    with app.app_context():
        o = db.session.query(Order).one()
        oid, gid, bid = o.id, o.gold_receipts[0].id, o.bookings[0].id
    r = auth_client.post(f"/orders/{oid}/edit", data=dict(ORDER_01, customer="Narayan S"), follow_redirects=True)
    assert "Order 01 updated" in text(r)
    auth_client.post(f"/orders/{oid}/gold/{gid}/delete")
    auth_client.post(f"/orders/{oid}/booking/{bid}/delete")
    with app.app_context():
        o = db.session.get(Order, oid)
        assert o.customer == "Narayan S" and not o.gold_receipts and not o.bookings
    auth_client.post(f"/orders/{oid}/delete")
    with app.app_context():
        assert db.session.query(Order).count() == 0
        assert db.session.query(Payment).count() == 0


def test_advance_errors_are_explained(auth_client, app):
    auth_client.post("/orders/new", data=ORDER_01)
    with app.app_context():
        oid = db.session.query(Order).one().id
    r = auth_client.post("/advances/record", data={"order_id": oid, "kind": "gold", "item_desc": ["Ring"], "item_net": ["10"],
                                                   "item_purity": [""], "item_rate": [""]}, follow_redirects=True)
    assert "Enter the purity for Ring" in text(r)
    r = auth_client.post("/advances/record", data={"order_id": oid, "kind": "gold", "item_desc": [""], "item_net": [""],
                                                   "item_purity": [""], "item_rate": ["15000"]}, follow_redirects=True)
    assert "Add at least one old-gold item" in text(r)
    r = auth_client.post("/advances/record", data={"order_id": oid, "kind": "cash", "cash_amount": "1000", "book_now": "on"},
                         follow_redirects=True)
    assert "rate you paid" in text(r)


def test_pages_render(auth_client):
    auth_client.post("/orders/new", data=ORDER_01)
    for url in ["/", "/orders", "/orders?f=open&q=nar", "/orders/new", "/advances", "/reserve", "/sop", "/settings",
                "/account/password", "/orders/1", "/orders/1/edit"]:
        r = auth_client.get(url)
        assert r.status_code == 200, url
    assert auth_client.get("/orders/999").status_code == 404


def test_todays_rate_and_alerts(auth_client):
    auth_client.post("/orders/new", data=dict(ORDER_01, book_adv=""))
    r = auth_client.post("/rate", data={"rate": "15600"}, follow_redirects=True)
    assert "Today's rate set to ₹15,600" in text(r)
    assert "above the order rate" in text(r)


def test_settings_saved(auth_client):
    data = {"alert_pct": "2", "lock_days": "3", "max_open_g": "40", "adv_pct": "60", "c_wastage": "8",
            "c_labour": "500", "k_wastage": "2", "k_labour": "300"}
    data.update({f"c_{k}": "90" for k in ["24", "22", "20", "18", "14"]})
    data.update({f"k_{k}": "91" for k in ["24", "22", "20", "18", "14"]})
    auth_client.post("/settings", data=data)
    html = text(auth_client.get("/sop"))
    assert "at least 60% advance" in html


# ---------------------------------------------------------------- previews

def test_order_preview(auth_client):
    r = auth_client.post("/api/preview/order", data=ORDER_01)
    html = text(r)
    assert r.status_code == 200
    assert "48.500 g" in html and "21.000 g" in html and "31.000 g" in html


def test_advance_preview_gold(auth_client, app):
    auth_client.post("/orders/new", data=ORDER_01)
    with app.app_context():
        oid = db.session.query(Order).one().id
    r = auth_client.post("/api/preview/advance", data={"order_id": oid, "kind": "gold", "item_desc": ["Chain", "Ring"],
                                                       "item_net": ["20", "9.4"], "item_purity": ["70", "70"],
                                                       "item_rate": ["14000", "14000"]})
    assert "2 items: 29.400 g net → 20.580 g fine, worth ₹2,88,120" in text(r) and "+1.372 g extra" in text(r)


def test_several_old_gold_items_in_one_go(auth_client, app):
    auth_client.post("/orders/new", data=dict(ORDER_01, **{
        "gin_item_desc": ["Bangle", "Chain", ""], "gin_item_net": ["18.5", "11.5", ""],
        "gin_item_purity": ["70", "75", ""], "gin_item_rate": ["15000", "14800", "15000"]}))
    with app.app_context():
        o = db.session.query(Order).one()
        items = sorted(o.gold_receipts, key=lambda g: g.note)
        assert [(g.note, g.gross, g.fine, g.credit_rate) for g in items] == [
            ("Bangle", 18.5, 12.95, 15000), ("Chain", 11.5, 8.625, 14800)]
    page = text(auth_client.get(f"/orders/{o.id}"))
    assert "Bangle · 18.500 g × 70%" in page and "Chain · 11.500 g × 75% @ ₹14,800" in page


def test_new_order_keeps_gold_rows_after_an_error(auth_client):
    auth_client.post("/orders/new", data=ORDER_01)
    r = auth_client.post("/orders/new", data=dict(ORDER_01, **{"gin_item_desc": ["Bangle", "Chain"],
                                                               "gin_item_net": ["18.5", "11.5"], "gin_item_purity": ["70", "75"],
                                                               "gin_item_rate": ["15000", "15000"]}))
    assert r.status_code == 400
    assert 'value="Chain"' in r.get_data(as_text=True) and 'value="11.5"' in r.get_data(as_text=True)


# ---------------------------------------------------------------- backup

BROWSER_BACKUP = {
    "ledger": {"l1": {"type": "in", "date": "2026-10-01", "gross": 500, "purity": 999, "fine": 499.5}},
    "orders": {
        "a": {"orderNo": "01", "date": "2026-10-01", "customer": "Narayan", "karigar": "Ghanshyam", "weight": 50,
              "karat": "22", "rate24": 15000, "kTouch": 92, "kWastage": 5, "cMode": "rate", "cRate": 14250, "cTouch": 91.6,
              "cWastage": 15, "labourToGold": True, "status": "open",
              "payments": [{"date": "2026-10-01", "amount": 150000}],
              "locks": [{"date": "2026-10-01", "amount": 150000, "rate": 15000}],
              "goldIn": [{"date": "2026-10-01", "gross": 30, "purityPct": 70, "fine": 21, "creditRate": 15000}]},
        "b": {"orderNo": "OLD", "date": "2026-09-20", "weight": 40, "karat": "20", "rate24": 10000, "kTouch": 84,
              "kWastage": 2, "cTouch": 83.3, "cWastage": 10, "status": "settled", "settledDate": "2026-09-29"},
    },
    "settings": {"todayRate": 15000, "todayDate": "2026-10-01", "alertPct": 1.5},
}


def _upload(client, data, replace=False):
    payload = {"file": (io.BytesIO(json.dumps(data).encode()), "backup.json")}
    if replace:
        payload["replace"] = "on"
    return client.post("/backup/import", data=payload, content_type="multipart/form-data", follow_redirects=True)


def test_import_browser_backup(auth_client, app):
    r = _upload(auth_client, BROWSER_BACKUP)
    assert "Imported 2 orders and 1 bullion entries" in text(r)
    with app.app_context():
        old = db.session.query(Order).filter_by(order_no="OLD").one()
        assert len(old.bookings) == 1 and old.bookings[0].rate == 10000  # settled before bookings existed
    html = text(auth_client.get("/"))
    # own = 499.5 - 48.5 (open 01) - 34.4 (OLD) + 36.652 (OLD back) ; advances = 31
    assert figure(html, "own-reserve") == "453.252"
    assert figure(html, "adv-gold") == "31.000"
    r = _upload(auth_client, BROWSER_BACKUP)
    assert "already have records" in text(r)


def test_export_then_restore_round_trip(auth_client, app):
    _upload(auth_client, BROWSER_BACKUP)
    before = text(auth_client.get("/"))
    backup = json.loads(auth_client.get("/backup/export.json").get_data())
    with app.app_context():
        for m in (Payment, GoldBooking, GoldReceipt, Order, LedgerEntry):
            db.session.query(m).delete()
        db.session.commit()
    _upload(auth_client, backup)
    after = text(auth_client.get("/"))
    for el in ("own-reserve", "adv-gold", "total-gold"):
        assert figure(before, el) == figure(after, el)


def test_bad_backup_rejected(auth_client):
    r = auth_client.post("/backup/import", data={"file": (io.BytesIO(b"not json"), "x.json")},
                         content_type="multipart/form-data", follow_redirects=True)
    assert "isn't valid JSON" in text(r)
    r = _upload(auth_client, {"hello": 1})
    assert "not a Bullion Book backup" in text(r)


def test_csv_export(auth_client):
    auth_client.post("/orders/new", data=ORDER_01)
    r = auth_client.get("/backup/orders.csv")
    body = text(r)
    assert r.mimetype == "text/csv"
    assert body.splitlines()[0].startswith("Order,Date,Customer")
    assert "01,2026-10-01,Narayan" in body


def test_healthz(client):
    assert client.get("/healthz").get_json() == {"ok": True}
