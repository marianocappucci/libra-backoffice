"""Salud del despliegue, feature flags y validación del entorno."""
import pytest
from fastapi.testclient import TestClient

from libra_backoffice.app import create_app
from libra_backoffice.settings import ConfiguracionInvalida, cargar_settings

from .conftest import PASSWORD, TOKEN, USUARIO, construir_settings


# ── Salud ───────────────────────────────────────────────────────────────────

def test_salud_reporta_arranque_y_features(logueado):
    cuerpo = logueado.get("/api/salud").json()
    assert cuerpo["producto"]["slug"] == "gestiolibra"
    assert cuerpo["features"] == ["instancias", "salud", "smtp", "usuarios"]
    assert cuerpo["backoffice"]["uptime_segundos"] >= 0


def test_salud_distingue_instancia_viva_de_caida(logueado):
    """Una instancia caída es información, no una falla del backoffice — y es
    justo el momento en que alguien va a abrir esta pantalla."""
    estados = {i["slug"]: i["estado"] for i in logueado.get("/api/salud").json()["instancias"]}
    assert estados == {"acme": "ok", "beta": "ok", "caida": "inalcanzable"}


def test_salud_pide_sesion(cliente):
    assert cliente.get("/api/salud").status_code == 401


# El chequeo mira el cuerpo, no sólo el 200 — ver el docstring de `routers/salud.py`.
# `_app` se define más abajo, en la sección de feature flags; Python lo resuelve
# al llamar, así que estos tests quedan junto al resto de los de salud.

def _instancia_que_solo_sirve_la_spa():
    """Una instancia con la API muerta y el frontend horneado en la imagen.

    Es exactamente la forma de los seis productos: el catch-all de la SPA
    contesta `index.html` con **200** en cualquier ruta, `/health` incluida. Es
    el caso que la pantalla tiene que poder reportar y no podía.
    """
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    app = FastAPI()

    @app.get("/{camino:path}")
    def catch_all(camino: str):
        return HTMLResponse("<!doctype html><div id=root></div>")

    return app


def _instancia_con_health_que_no_es_objeto():
    """200 con JSON válido que **no** es un objeto.

    Separa las dos mitades del criterio: `resp.json()` no revienta —la cadena
    `"ok"` es JSON perfectamente válido—, así que sin el `isinstance(dict)` esto
    pasaría por sano.
    """
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/health")
    def health():
        return "ok"

    return app


def _salud_con(tmp_path, instancias_falsas, inventario, app_de_acme):
    c = _app(
        tmp_path,
        {**instancias_falsas, "producto-acme": app_de_acme},
        inventario,
        ("instancias", "smtp", "usuarios", "salud"),
    )
    return {i["slug"]: i for i in c.get("/api/salud").json()["instancias"]}


def test_una_instancia_que_solo_sirve_la_spa_no_es_ok(tmp_path, instancias_falsas, inventario):
    """🔴 El caso que motivó el arreglo.

    Con `esperar_json=False` esto daba `ok`: el chequeo miraba el 200, y el 200
    lo contesta el fallback del frontend aunque la API no exista.
    """
    estados = _salud_con(
        tmp_path, instancias_falsas, inventario, _instancia_que_solo_sirve_la_spa()
    )

    assert estados["acme"]["estado"] == "error"
    assert "no es JSON" in estados["acme"]["detalle"]
    # Control: la de al lado, sana, sigue leyéndose ok. Sin esto, un chequeo que
    # rompiera *todas* las instancias pasaría este test igual.
    assert estados["beta"]["estado"] == "ok"


def test_un_health_que_no_devuelve_un_objeto_tampoco_es_ok(
    tmp_path, instancias_falsas, inventario
):
    estados = _salud_con(
        tmp_path, instancias_falsas, inventario, _instancia_con_health_que_no_es_objeto()
    )

    assert estados["acme"]["estado"] == "error"
    assert "no es un objeto JSON (str)" in estados["acme"]["detalle"]
    assert estados["beta"]["estado"] == "ok"


@pytest.mark.parametrize("forma", [
    {"status": "ok"},                                              # contalibra, restolibra
    {"ok": True, "product": "gestiolibra"},                        # gestiolibra, medlibra, ventalibra
    {"status": "ok", "timestamp": "2026-08-15T20:28:44+00:00"},    # libradesk
])
def test_las_tres_formas_de_health_de_la_familia_pasan_igual(
    tmp_path, instancias_falsas, inventario, forma
):
    """No se exige ninguna clave, a propósito.

    Los seis productos devuelven tres formas distintas —medidas contra las 18
    instancias del VPS el 2026-08-15—. Pedir `status`, o pedir `ok`, habría
    puesto en rojo a productos sanos, que es el error opuesto y se nota menos.
    """
    from fastapi import FastAPI

    app = FastAPI()
    app.get("/health")(lambda: forma)

    estados = _salud_con(tmp_path, instancias_falsas, inventario, app)
    assert estados["acme"]["estado"] == "ok"


# ── Feature flags ───────────────────────────────────────────────────────────

def _app(tmp_path, instancias_falsas, inventario, features):
    from libra_backoffice.cliente_instancia import ClienteInstancia

    from .conftest import _TransporteDeInstancias

    app = create_app(construir_settings(tmp_path, features=features), inventario=inventario)
    app.state.cliente_instancia = ClienteInstancia(
        token=TOKEN, transport=_TransporteDeInstancias(instancias_falsas)
    )
    c = TestClient(app, base_url="https://testserver")
    c.post("/api/login", json={"username": USUARIO, "password": PASSWORD})
    return c


def test_sin_la_feature_smtp_esa_ruta_no_existe(tmp_path, instancias_falsas, inventario):
    c = _app(tmp_path, instancias_falsas, inventario, ("instancias", "usuarios", "salud"))
    assert c.get("/api/instancias/acme/smtp").status_code == 404
    assert c.get("/api/instancias/acme/usuarios").status_code == 200


def test_sin_la_feature_instancias_no_hay_inventario(tmp_path, instancias_falsas, inventario):
    c = _app(tmp_path, instancias_falsas, inventario, ("smtp", "salud"))
    assert c.get("/api/instancias").status_code == 404


def test_la_feature_gana_al_401(tmp_path, instancias_falsas, inventario):
    """Sin sesión y sin la feature: 404, no 401.

    Un 401 le confirmaría a alguien sin credenciales qué features tiene
    habilitadas este producto.
    """
    from libra_backoffice.cliente_instancia import ClienteInstancia

    from .conftest import _TransporteDeInstancias

    app = create_app(
        construir_settings(tmp_path, features=("instancias", "salud")), inventario=inventario
    )
    app.state.cliente_instancia = ClienteInstancia(
        token=TOKEN, transport=_TransporteDeInstancias(instancias_falsas)
    )
    c = TestClient(app, base_url="https://testserver")
    assert c.get("/api/instancias/acme/smtp").status_code == 404


# ── Settings ────────────────────────────────────────────────────────────────

BASE = {
    "PRODUCT_SLUG": "gestiolibra", "FEATURES": "instancias,smtp,usuarios,salud",
    "REPO_ROOT": "/root/gestiolibra", "DB_FILENAME": "gestiolibra.db",
    "LIBRA_SERVICE_TOKEN": "t",
}


def test_settings_completo():
    s = cargar_settings({**BASE, "PRODUCT_NAME": "Gestiolibra", "USERS_PATH": "/api/usuarios"})
    assert s.product_name == "Gestiolibra"
    assert s.users_path == "/api/usuarios"
    assert s.smtp_path == "/admin/smtp"
    assert s.health_path == "/health"
    assert s.features_por_instancia == ["smtp", "usuarios"]


def test_health_path_configurable():
    """La ruta se puede mover, aunque hoy ningún producto la mueva.

    Esto existía porque LibraDesk servía su health en `/api/health`. **Ya no**:
    la ruta se normalizó a `/health` en toda la familia el 2026-08-12, y medido
    contra el VPS el 2026-08-15 los seis backoffice apuntan ahí (tres explícito,
    tres por el default). Se conserva la costura porque el día que un producto
    la mueva, apuntar mal ya no da un falso 'ok': el chequeo mira el cuerpo.
    """
    s = cargar_settings({**BASE, "HEALTH_PATH": "/api/salud-interna"})
    assert s.health_path == "/api/salud-interna"


def test_falta_product_slug():
    with pytest.raises(ConfiguracionInvalida, match="PRODUCT_SLUG"):
        cargar_settings({**BASE, "PRODUCT_SLUG": ""})


def test_features_vacio():
    with pytest.raises(ConfiguracionInvalida, match="vacío"):
        cargar_settings({**BASE, "FEATURES": ""})


def test_feature_mal_escrita_no_pasa_en_silencio():
    """`FEATURES=smpt` dejaría el backoffice sin la pantalla de correo y sin
    ninguna señal de por qué."""
    with pytest.raises(ConfiguracionInvalida, match="smpt"):
        cargar_settings({**BASE, "FEATURES": "smpt,salud"})


def test_falta_repo_root():
    with pytest.raises(ConfiguracionInvalida, match="REPO_ROOT"):
        cargar_settings({**BASE, "REPO_ROOT": ""})


def test_falta_db_filename():
    with pytest.raises(ConfiguracionInvalida, match="DB_FILENAME"):
        cargar_settings({**BASE, "DB_FILENAME": ""})


def test_smtp_sin_token_de_servicio():
    """Sin token no hay forma de hablarle a una instancia: mejor no levantar
    que levantar y dar 401 en cada pantalla."""
    with pytest.raises(ConfiguracionInvalida, match="LIBRA_SERVICE_TOKEN"):
        cargar_settings({**BASE, "LIBRA_SERVICE_TOKEN": ""})


def test_sin_features_por_instancia_no_hace_falta_el_token():
    s = cargar_settings({**BASE, "FEATURES": "instancias,salud", "LIBRA_SERVICE_TOKEN": ""})
    assert s.service_token == ""


# ── SPA ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (d / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return d


def test_sirve_la_spa_y_sus_assets(tmp_path, inventario, dist):
    app = create_app(construir_settings(tmp_path), inventario=inventario, frontend_dist=str(dist))
    c = TestClient(app, base_url="https://testserver")
    assert "<div id=root>" in c.get("/").text
    assert c.get("/assets/app.js").status_code == 200


def test_una_ruta_de_react_devuelve_el_index(tmp_path, inventario, dist):
    """Recargar el navegador en una ruta interna no puede dar 404."""
    app = create_app(construir_settings(tmp_path), inventario=inventario, frontend_dist=str(dist))
    c = TestClient(app, base_url="https://testserver")
    assert "<div id=root>" in c.get("/instancias/acme/smtp").text


def test_la_api_gana_sobre_el_fallback(tmp_path, inventario, dist):
    app = create_app(construir_settings(tmp_path), inventario=inventario, frontend_dist=str(dist))
    c = TestClient(app, base_url="https://testserver")
    assert c.get("/api/salud").status_code == 401


def test_sin_frontend_construido_la_api_sigue_andando(tmp_path, inventario):
    app = create_app(
        construir_settings(tmp_path), inventario=inventario, frontend_dist=str(tmp_path / "nada")
    )
    assert TestClient(app, base_url="https://testserver").get("/health").status_code == 200
