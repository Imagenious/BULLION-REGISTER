"""Jinja number formatting in Indian style (grams to 3 decimals, rupees with lakh grouping)."""
from __future__ import annotations

from datetime import date

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def indian_group(n: int) -> str:
    s = str(abs(int(n)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return s


def g3(v) -> str:
    v = float(v or 0)
    whole, frac = f"{abs(v):.3f}".split(".")
    return ("-" if v < -0.0005 else "") + indian_group(int(whole)) + "." + frac


def sg3(v) -> str:
    v = float(v or 0)
    sign = "+" if v > 0.0005 else "−" if v < -0.0005 else ""
    return sign + g3(abs(v))


def inr(v) -> str:
    v = round(float(v or 0))
    return ("−" if v < 0 else "") + "₹" + indian_group(abs(v))


def pct(v, digits: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:+.{digits}f}%".replace("-", "−")


def fdate(s) -> str:
    if not s:
        return ""
    try:
        d = date.fromisoformat(str(s)[:10])
    except ValueError:
        return str(s)
    return f"{d.day:02d} {MONTHS[d.month - 1]} {d.year % 100:02d}"


def register(app) -> None:
    app.jinja_env.filters.update(g3=g3, sg3=sg3, inr=inr, pct=pct, fdate=fdate)
