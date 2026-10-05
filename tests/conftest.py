import pytest

from app import create_app
from app.models import User, db


@pytest.fixture()
def app(tmp_path, monkeypatch):
    for var in ("DATABASE_URL", "ADMIN_USERNAME", "ADMIN_PASSWORD", "RENDER", "SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "test",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "test.db"),
    })
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture(autouse=True)
def _reset_lockout():
    from app import auth
    auth._FAILURES.clear()
    yield
    auth._FAILURES.clear()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_client(app, client):
    with app.app_context():
        u = User(username="owner")
        u.set_password("gold-secret-1")
        db.session.add(u)
        db.session.commit()
    r = client.post("/login", data={"username": "owner", "password": "gold-secret-1"})
    assert r.status_code == 302
    return client
