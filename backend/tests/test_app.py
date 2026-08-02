"""Arranque de la app: base ausente, salud de la instancia y servido de la SPA."""
import httpx
import pytest
from fastapi.testclient import TestClient

from libra_backoffice.app import create_app

from .conftest import PASSWORD, USUARIO, construir_settings


def _logueado(app):
    c = TestClient(app, base_url="https://testserver")
    c.post("/api/login", json={"username": USUARIO, "password": PASSWORD})
    return c


def test_base_sin_las_tablas_da_503_explicativo(tmp_path):
    """El caso real: `AUTH_DB_PATH` apunta a una instancia que nunca arrancó.

    Un 500 pelado mandaría a buscar el problema en el backoffice; el 503 dice
    dónde está de verdad.
    """
    vacia = tmp_path / "sin_schema.db"
    vacia.touch()
    app = create_app(construir_settings(vacia, {"usuarios"}))
    resp = _logueado(app).get("/api/usuarios")
    assert resp.status_code == 503
    assert "sin_schema.db" in resp.json()["detail"]


def test_no_crea_las_tablas_en_la_base_de_la_instancia(tmp_path):
    """El schema lo owna el producto. Si el backoffice lo creara, apuntar a una
    base equivocada dejaría de ser un error visible."""
    import sqlite3

    vacia = tmp_path / "sin_schema.db"
    vacia.touch()
    create_app(construir_settings(vacia, {"usuarios", "smtp"}))
    con = sqlite3.connect(vacia)
    tablas = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    con.close()
    assert tablas == []


class _RespuestaFalsa:
    def __init__(self, status_code):
        self.status_code = status_code


class _ClienteFalso:
    """Reemplazo de `httpx.AsyncClient` para no depender de la red en la suite."""

    def __init__(self, status_code=None, error=None):
        self._status_code = status_code
        self._error = error

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        if self._error:
            raise self._error
        return _RespuestaFalsa(self._status_code)


@pytest.fixture
def app_con_salud(db_instancia):
    settings = construir_settings(db_instancia, {"salud"})
    return create_app(
        settings.__class__(**{**settings.__dict__, "product_health_url": "http://producto:8000/health"})
    )


def test_salud_instancia_ok(app_con_salud, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _ClienteFalso(status_code=200))
    instancia = _logueado(app_con_salud).get("/api/salud").json()["instancia"]
    assert instancia["estado"] == "ok"
    assert instancia["detalle"] == "HTTP 200"


def test_salud_instancia_con_error_http(app_con_salud, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _ClienteFalso(status_code=502))
    instancia = _logueado(app_con_salud).get("/api/salud").json()["instancia"]
    assert instancia["estado"] == "error"


def test_salud_instancia_inalcanzable_no_tumba_el_backoffice(app_con_salud, monkeypatch):
    """Si el producto está caído, el backoffice tiene que seguir contestando —
    es justo el momento en que alguien lo va a abrir."""
    monkeypatch.setattr(httpx, "AsyncClient", _ClienteFalso(error=httpx.ConnectError("sin ruta")))
    resp = _logueado(app_con_salud).get("/api/salud")
    assert resp.status_code == 200
    assert resp.json()["instancia"]["estado"] == "inalcanzable"


# ── servido de la SPA ────────────────────────────────────────────────────────

@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (d / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return d


def test_sirve_la_spa_y_sus_assets(db_instancia, dist):
    app = create_app(construir_settings(db_instancia, {"salud"}), frontend_dist=str(dist))
    c = TestClient(app, base_url="https://testserver")
    assert "<div id=root>" in c.get("/").text
    assert c.get("/assets/app.js").status_code == 200


def test_una_ruta_del_router_de_react_devuelve_el_index(db_instancia, dist):
    """Recargar el navegador en `/smtp` no puede dar 404: el ruteo lo resuelve
    React y el servidor devuelve siempre el mismo HTML."""
    app = create_app(construir_settings(db_instancia, {"salud"}), frontend_dist=str(dist))
    c = TestClient(app, base_url="https://testserver")
    assert "<div id=root>" in c.get("/smtp").text


def test_la_api_gana_sobre_el_fallback(db_instancia, dist):
    app = create_app(construir_settings(db_instancia, {"salud"}), frontend_dist=str(dist))
    c = TestClient(app, base_url="https://testserver")
    # Sin sesión: 401 de la API, no el index.html.
    assert c.get("/api/salud").status_code == 401


def test_sin_frontend_construido_la_api_sigue_andando(db_instancia, tmp_path):
    app = create_app(construir_settings(db_instancia, {"salud"}), frontend_dist=str(tmp_path / "no-existe"))
    c = TestClient(app, base_url="https://testserver")
    assert c.get("/health").status_code == 200
