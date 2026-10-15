"""`/docs`, `/redoc` y `/openapi.json` no se publican en producción (ADR-053 de libracore).

Medido el 2026-10-15: `/openapi.json` daba 200 sin sesión en el backoffice real y publicaba el mapa de sus rutas. El
`docs_url=None` que ya tenía no alcanzaba: `openapi_url` seguía en su valor por omisión, y las rutas apagadas caían en el
fallback de la SPA, que contesta `index.html` con 200 a lo que no existe.

El criterio (sólo `ENV=development`, o `LIBRA_DOCS_API=1` a propósito) y su detalle tienen sus pruebas en libracore; acá se
fija que **este** backoffice lo usa, con la SPA montada como en producción.
"""
import pytest
from fastapi.testclient import TestClient

from libra_backoffice.app import create_app

from .conftest import construir_settings

RUTAS = ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect")


@pytest.fixture
def produccion(monkeypatch):
    """Lo que tiene una instancia real: ni `ENV=development` ni el interruptor del Swagger."""
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("LIBRA_DOCS_API", raising=False)
    # `create_app` pide el secreto de la cookie y el admin: en producción vienen del `.env`.
    monkeypatch.setenv("SECRET_KEY", "0" * 64)


def _con_spa(tmp_path, inventario) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<!doctype html><div id="root"></div>')
    app = create_app(construir_settings(tmp_path), inventario=inventario, frontend_dist=str(dist))
    return TestClient(app, base_url="https://testserver")


@pytest.mark.parametrize("ruta", RUTAS)
def test_en_produccion_con_la_spa_montada_dan_404_y_no_el_index(produccion, tmp_path, inventario, ruta):
    r = _con_spa(tmp_path, inventario).get(ruta)
    assert r.status_code == 404, r.text[:200]
    assert "root" not in r.text and "openapi" not in r.text.lower()


def test_en_produccion_sin_spa_tambien(produccion, tmp_path, inventario):
    c = TestClient(create_app(construir_settings(tmp_path), inventario=inventario), base_url="https://testserver")
    assert {ruta: c.get(ruta).status_code for ruta in RUTAS} == dict.fromkeys(RUTAS, 404)


def test_en_desarrollo_se_sigue_viendo(monkeypatch, tmp_path, inventario):
    """`ENV=development` lo pone la suite entera (conftest): el Swagger se ve, y trae las rutas del backoffice."""
    monkeypatch.delenv("LIBRA_DOCS_API", raising=False)
    c = TestClient(create_app(construir_settings(tmp_path), inventario=inventario), base_url="https://testserver")
    esquema = c.get("/openapi.json")
    assert esquema.status_code == 200
    assert "/api/login/opciones" in esquema.json()["paths"]
    assert c.get("/docs").status_code == 200


def test_el_resto_de_las_rutas_no_cambia(produccion, tmp_path, inventario):
    c = _con_spa(tmp_path, inventario)
    assert c.get("/health").status_code == 200
    assert c.get("/instancias/acme").status_code == 200  # la SPA sigue atendiendo sus rutas
