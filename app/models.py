from __future__ import annotations

from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class AppSettings(db.Model):
    """One row holding the owner's defaults, SOP limits and today's rate."""
    __tablename__ = "settings"
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(JSON, nullable=False, default=dict)


class LedgerEntry(db.Model):
    """Own bullion added to or withdrawn from the reserve."""
    __tablename__ = "ledger"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), nullable=False)
    type = db.Column(db.String(3), nullable=False, default="in")  # in | out
    gross = db.Column(db.Float, nullable=False, default=0)
    purity = db.Column(db.Float, nullable=False, default=999)       # per-mille
    fine = db.Column(db.Float, nullable=False, default=0)
    note = db.Column(db.String(200), default="")
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)


class Order(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(40), unique=True, nullable=False)
    date = db.Column(db.String(10), nullable=False)
    customer = db.Column(db.String(120), default="")
    item = db.Column(db.String(120), default="")
    karigar = db.Column(db.String(120), default="")
    weight = db.Column(db.Float, nullable=False, default=0)
    karat = db.Column(db.String(10), default="22")
    rate24 = db.Column(db.Float, default=0)          # 24K order rate fixed with the customer
    k_touch = db.Column(db.Float, default=0)
    k_wastage = db.Column(db.Float, default=0)
    k_labour = db.Column(db.Float, default=0)
    c_mode = db.Column(db.String(5), default="touch")  # touch | rate
    c_touch = db.Column(db.Float, default=0)
    c_rate = db.Column(db.Float, default=0)
    c_wastage = db.Column(db.Float, default=0)
    c_labour = db.Column(db.Float, default=0)
    labour_to_gold = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text, default="")
    status = db.Column(db.String(10), default="open")  # open | settled
    settled_date = db.Column(db.String(10))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    payments = db.relationship("Payment", backref="order", cascade="all, delete-orphan",
                               order_by="Payment.date")
    bookings = db.relationship("GoldBooking", backref="order", cascade="all, delete-orphan",
                               order_by="GoldBooking.date")
    gold_receipts = db.relationship("GoldReceipt", backref="order", cascade="all, delete-orphan",
                                    order_by="GoldReceipt.date")

    @property
    def karat_label(self) -> str:
        return "Custom" if self.karat == "custom" else f"{self.karat}K"


class Payment(db.Model):
    """Cash received from the customer."""
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    date = db.Column(db.String(10), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(120), default="Cash")


class GoldBooking(db.Model):
    """Fine gold bought with the customer's cash, at the rate actually paid."""
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    date = db.Column(db.String(10), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    rate = db.Column(db.Float, nullable=False)

    @property
    def grams(self) -> float:
        return self.amount / self.rate if self.rate else 0.0


class GoldReceipt(db.Model):
    """Gold the customer handed over as advance (old jewellery, bars, coins)."""
    __tablename__ = "gold_receipts"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    date = db.Column(db.String(10), nullable=False)
    type = db.Column(db.String(40), default="Old jewellery")
    gross = db.Column(db.Float, default=0)
    less = db.Column(db.Float, default=0)          # stones / dirt
    purity_pct = db.Column(db.Float, default=0)
    melt = db.Column(db.Float, default=0)          # melting loss %
    fine = db.Column(db.Float, nullable=False)
    credit_rate = db.Column(db.Float, default=0)   # 24K rate credited; 0 = order rate
    note = db.Column(db.String(120), default="")
