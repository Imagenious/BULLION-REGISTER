"""Single-owner login. The first account is created on /setup (from this computer) or from env vars on the cloud."""
from __future__ import annotations

import time
from functools import wraps

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from .models import User, db

bp = Blueprint("auth", __name__)

LOCAL_ADDRS = {"127.0.0.1", "::1", "localhost"}

# Wrong-password lockout: 5 failures within 15 minutes from one address.
_FAILURES: dict[str, list[float]] = {}
LOCKOUT_WINDOW, LOCKOUT_LIMIT = 15 * 60, 5


def _too_many_failures(ip: str) -> bool:
    now = time.monotonic()
    recent = [t for t in _FAILURES.get(ip, []) if now - t < LOCKOUT_WINDOW]
    _FAILURES[ip] = recent
    return len(recent) >= LOCKOUT_LIMIT


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id") or db.session.get(User, session["user_id"]) is None:
            if db.session.query(User).count() == 0:
                return redirect(url_for("auth.setup"))
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def _setup_allowed() -> bool:
    if db.session.query(User).count():
        return False
    return current_app.config.get("ALLOW_REMOTE_SETUP") or request.remote_addr in LOCAL_ADDRS


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    if not _setup_allowed():
        if db.session.query(User).count():
            return redirect(url_for("auth.login"))
        return render_template("setup_blocked.html"), 403
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if len(username) < 3:
            error = "Choose a username of at least 3 characters."
        elif len(password) < 8:
            error = "Choose a password of at least 8 characters."
        elif password != request.form.get("confirm", ""):
            error = "The two passwords don't match."
        else:
            u = User(username=username)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            session.clear()
            session["user_id"] = u.id
            session.permanent = True
            flash("Account created. Start by lodging your opening bullion.")
            return redirect(url_for("main.reserve"))
    return render_template("setup.html", error=error)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if db.session.query(User).count() == 0:
        return redirect(url_for("auth.setup"))
    error = None
    if request.method == "POST":
        ip = request.remote_addr or "?"
        if _too_many_failures(ip):
            return render_template("login.html", error="Too many wrong attempts. Wait 15 minutes, then try again."), 429
        u = db.session.query(User).filter_by(username=request.form.get("username", "").strip()).first()
        if not (u and u.check_password(request.form.get("password", ""))):
            _FAILURES.setdefault(ip, []).append(time.monotonic())
        else:
            session.clear()
            session["user_id"] = u.id
            session.permanent = True
            _FAILURES.pop(ip, None)
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("main.dashboard"))
        error = "Wrong username or password."
    return render_template("login.html", error=error)


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    error = None
    if request.method == "POST":
        u = db.session.get(User, session["user_id"])
        if not u.check_password(request.form.get("current", "")):
            error = "Your current password is wrong."
        elif len(request.form.get("password", "")) < 8:
            error = "Choose a password of at least 8 characters."
        elif request.form.get("password") != request.form.get("confirm"):
            error = "The two new passwords don't match."
        else:
            u.set_password(request.form["password"])
            db.session.commit()
            flash("Password changed.")
            return redirect(url_for("main.settings"))
    return render_template("password.html", error=error)
