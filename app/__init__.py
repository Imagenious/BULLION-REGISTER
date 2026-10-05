"""Bullion Register — gold reserve, customer advances and karigar orders."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from flask import Flask
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.exc import IntegrityError

from . import filters
from .models import User, db

csrf = CSRFProtect()


def _database_url(instance_path: str) -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///" + str(Path(instance_path) / "bullion.db")
    # Render / Heroku style URLs -> SQLAlchemy psycopg 3 driver
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _secret_key(instance_path: str) -> str:
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    path = Path(instance_path) / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip()


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    # Secure (HTTPS-only) cookies on Render, or wherever COOKIE_SECURE=1 is set.
    on_cloud = os.environ.get("COOKIE_SECURE", "1" if os.environ.get("RENDER") else "0") == "1"
    app.config.update(
        SECRET_KEY=_secret_key(app.instance_path),
        SQLALCHEMY_DATABASE_URI=_database_url(app.instance_path),
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=on_cloud,
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14,
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        WTF_CSRF_TIME_LIMIT=None,
        # First-run account setup is only offered from this computer unless explicitly allowed.
        ALLOW_REMOTE_SETUP=os.environ.get("ALLOW_REMOTE_SETUP") == "1",
    )
    if test_config:
        app.config.update(test_config)

    if os.environ.get("RENDER") or os.environ.get("BEHIND_PROXY") == "1":
        # Trust the host's load balancer for the visitor's address and https scheme.
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    db.init_app(app)
    csrf.init_app(app)
    filters.register(app)

    from .auth import bp as auth_bp
    from .views import bp as main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    with app.app_context():
        db.create_all()
        _bootstrap_owner()

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


def _bootstrap_owner() -> None:
    """On the cloud, create the owner account from ADMIN_USERNAME / ADMIN_PASSWORD on first start."""
    username = os.environ.get("ADMIN_USERNAME", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not username or not password or db.session.query(User).count():
        return
    u = User(username=username)
    u.set_password(password)
    db.session.add(u)
    try:
        db.session.commit()
    except IntegrityError:  # another worker created it first
        db.session.rollback()
