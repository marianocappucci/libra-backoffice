"""Los endpoints de `routers/seguridad.py`: el doble factor enrolable en
runtime desde la pantalla Seguridad (F3, 2026-09-13).

Sigue el mismo patrón que `test_auth_totp.py`: `ADMIN_PANEL_ESTADO_PATH` se
setea con `monkeypatch` ANTES de construir la app (`AdminAuth` lo lee al
crearse) y el reloj de `libraauth.totp` se fija para poder calcular a mano el
código de un secreto que acá se genera al azar (`iniciar_totp`), no es fijo
como el de `test_auth_totp.py`.
"""
import base64

import pytest
from fastapi.testclient import TestClient
from libraauth import totp as totp_mod

from libra_backoffice.app import create_app
from libra_backoffice.cliente_instancia import ClienteInstancia

from .conftest import (
    PASSWORD,
    TOKEN,
    USUARIO,
    _TransporteDeInstancias,
    construir_settings,
    login,
)

AHORA = 1234567890
PASO = AHORA // 30
#: El mismo vector del RFC 6238 que usa `test_auth_totp.py`, para el caso con
#: `ADMIN_PANEL_TOTP_SECRET` por entorno.
SECRETO_ENTORNO = base64.b32encode(b"12345678901234567890").decode()


def _codigo(secreto: str, paso: int = PASO) -> str:
    return totp_mod.codigo(totp_mod.decodificar_secreto(secreto), paso)


@pytest.fixture
def reloj_fijo(monkeypatch):
    """🔴 `libraauth.totp` sólo importa el módulo `time` de la stdlib, así que
    esto pisa `time.time()` para TODO el proceso — incluida la cookie de
    sesión de `itsdangerous`, que también usa `time.time()` para sellar y
    validar. Por eso los tests que combinan esta fixture con `logueado` la
    piden PRIMERO en la firma (`reloj_fijo, logueado`, nunca al revés): si el
    login ocurre con el reloj real y después se congela a un instante
    anterior, `itsdangerous` ve una cookie sellada "en el futuro" y la
    rechaza (`SignatureExpired: token used too soon`) — un 401 que no tiene
    nada que ver con TOTP."""
    monkeypatch.setattr("libraauth.totp.time.time", lambda: AHORA)


def _cliente(tmp_path, instancias_falsas, inventario) -> TestClient:
    """Igual que el fixture `cliente` del conftest, pero construido DESPUÉS de
    tocar el entorno (ver `_cliente` de `test_auth_totp.py`)."""
    app = create_app(construir_settings(tmp_path), inventario=inventario)
    app.state.cliente_instancia = ClienteInstancia(
        token=TOKEN, transport=_TransporteDeInstancias(instancias_falsas)
    )
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def con_archivo(monkeypatch, tmp_path, instancias_falsas, inventario):
    """El caso normal: hay dónde guardar el secreto (`ADMIN_PANEL_ESTADO_PATH`)
    y todavía no hay ninguno enrolado."""
    monkeypatch.setenv("ADMIN_PANEL_ESTADO_PATH", str(tmp_path / "estado" / "login.json"))
    with _cliente(tmp_path, instancias_falsas, inventario) as c:
        yield c


@pytest.fixture
def logueado(con_archivo):
    resp = login(con_archivo, {"username": USUARIO, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return con_archivo


# ── Sin sesión ───────────────────────────────────────────────────────────────

def test_401_sin_sesion_en_los_cuatro(con_archivo):
    c = con_archivo
    assert c.get("/api/seguridad/totp").status_code == 401
    assert c.post("/api/seguridad/totp/iniciar").status_code == 401
    assert c.post("/api/seguridad/totp/confirmar", json={"codigo": "000000"}).status_code == 401
    assert c.post("/api/seguridad/totp/desactivar", json={"codigo": "000000"}).status_code == 401


# ── Estado ───────────────────────────────────────────────────────────────────

def test_estado_inicial(logueado):
    r = logueado.get("/api/seguridad/totp")
    assert r.status_code == 200
    assert r.json() == {"activo": False, "origen": None, "enrolable": True}
    assert r.headers["cache-control"] == "no-store"


def test_sin_estado_path_no_es_enrolable(cliente):
    """`cliente` (conftest) no setea `ADMIN_PANEL_ESTADO_PATH`: no hay dónde
    guardar un secreto nuevo."""
    resp = login(cliente, {"username": USUARIO, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    assert cliente.get("/api/seguridad/totp").json() == {
        "activo": False, "origen": None, "enrolable": False,
    }
    r = cliente.post("/api/seguridad/totp/iniciar")
    assert r.status_code == 409
    assert "no tiene dónde guardar" in r.json()["detail"]


# ── Iniciar ──────────────────────────────────────────────────────────────────

def test_iniciar_devuelve_secreto_uri_qr_y_no_se_cachea(logueado):
    r = logueado.post("/api/seguridad/totp/iniciar")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    datos = r.json()
    assert len(datos["secreto"]) >= 16
    assert "gestiolibra" in datos["uri"]  # `product_slug` de `construir_settings`
    assert datos["qr"].startswith("data:image/svg+xml")


# ── Confirmar: activa, y el código pasa a valer para loguearse ───────────────

def test_confirmar_activa_y_habilita_el_login_con_codigo(reloj_fijo, logueado):
    c = logueado
    secreto = c.post("/api/seguridad/totp/iniciar").json()["secreto"]

    r = c.post("/api/seguridad/totp/confirmar", json={"codigo": _codigo(secreto)})
    assert r.status_code == 200
    assert r.json() == {"activo": True}
    assert c.get("/api/seguridad/totp").json() == {
        "activo": True, "origen": "archivo", "enrolable": True,
    }

    assert c.get("/api/login/opciones").json() == {"totp": True}

    c.post("/api/logout")
    # Desde la F4 (login en dos pasos, libraauth v0.42.0) esto ya no es un
    # 401: es el paso 1, y devuelve el desafío del paso 2 en vez de rechazar
    # (ver `test_login_dos_pasos.py` para el contrato completo).
    sin_codigo = login(c, {"username": USUARIO, "password": PASSWORD})
    assert sin_codigo.status_code == 200
    assert sin_codigo.json()["requiere_codigo"] is True
    siguiente = _codigo(secreto, PASO + 1)
    assert login(c, {"username": USUARIO, "password": PASSWORD, "codigo": siguiente}).status_code == 200


def test_el_codigo_de_la_confirmacion_no_sirve_para_loguearse(reloj_fijo, logueado):
    c = logueado
    secreto = c.post("/api/seguridad/totp/iniciar").json()["secreto"]
    codigo = _codigo(secreto)
    assert c.post("/api/seguridad/totp/confirmar", json={"codigo": codigo}).status_code == 200
    c.post("/api/logout")
    assert login(c, {"username": USUARIO, "password": PASSWORD, "codigo": codigo}).status_code == 401


def test_confirmar_5_codigos_malos_bloquea(reloj_fijo, logueado):
    c = logueado
    c.post("/api/seguridad/totp/iniciar")
    for _ in range(5):
        r = c.post("/api/seguridad/totp/confirmar", json={"codigo": "000000"})
        assert r.status_code == 400
        assert r.json()["detail"] == "Código incorrecto o vencido."
    r = c.post("/api/seguridad/totp/confirmar", json={"codigo": "000000"})
    assert r.status_code == 429


# ── Desactivar ───────────────────────────────────────────────────────────────

def test_desactivar_codigo_malo_400_y_codigo_bueno_apaga(reloj_fijo, logueado):
    c = logueado
    secreto = c.post("/api/seguridad/totp/iniciar").json()["secreto"]
    c.post("/api/seguridad/totp/confirmar", json={"codigo": _codigo(secreto)})

    r = c.post("/api/seguridad/totp/desactivar", json={"codigo": "000000"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Código incorrecto."

    r = c.post("/api/seguridad/totp/desactivar", json={"codigo": _codigo(secreto, PASO + 1)})
    assert r.status_code == 200
    assert r.json() == {"activo": False}
    assert c.get("/api/seguridad/totp").json()["activo"] is False


# ── Origen entorno: 409 en los tres, nada editable desde la app ─────────────

def test_409_con_totp_por_entorno(monkeypatch, tmp_path, instancias_falsas, inventario, reloj_fijo):
    monkeypatch.setenv("ADMIN_PANEL_TOTP_SECRET", SECRETO_ENTORNO)
    with _cliente(tmp_path, instancias_falsas, inventario) as c:
        resp = login(c, {
            "username": USUARIO, "password": PASSWORD, "codigo": _codigo(SECRETO_ENTORNO),
        })
        assert resp.status_code == 200, resp.text

        assert c.get("/api/seguridad/totp").json() == {
            "activo": True, "origen": "entorno", "enrolable": False,
        }

        r = c.post("/api/seguridad/totp/iniciar")
        assert r.status_code == 409
        assert r.json()["detail"] == "El doble factor lo maneja la configuración del servidor."

        r = c.post("/api/seguridad/totp/confirmar", json={"codigo": "000000"})
        assert r.status_code == 409

        r = c.post("/api/seguridad/totp/desactivar", json={"codigo": "000000"})
        assert r.status_code == 409


# ── La IP del bloqueo también en este router (mismo agujero que el login) ───

NPM = ("172.18.0.19", 50000)


def _xff(forjada: str, real: str) -> dict:
    return {"X-Forwarded-For": f"{forjada}, {real}"}


def test_login_con_xff_inventado_no_esquiva_el_bloqueo(tmp_path, inventario):
    """El agujero de antes de v0.39.0 (ver `test_captcha_login.py`), repetido
    acá porque el rate limiting de `confirmar`/`desactivar` usa la misma
    `ip_del_request` — si algún día uno de los dos vuelve a un `_ip` propio
    que lea el header entero, este test (o el de `test_captcha_login.py`) se
    pone rojo."""
    app = create_app(construir_settings(tmp_path), inventario=inventario)
    with TestClient(app, base_url="https://testserver", client=NPM) as c:
        for i in range(5):
            resp = login(c, {"username": USUARIO, "password": "mal"},
                         headers=_xff(f"192.0.2.{i}", "203.0.113.9"))
            assert resp.status_code == 401
        r = login(c, {"username": USUARIO, "password": PASSWORD},
                  headers=_xff("192.0.2.250", "203.0.113.9"))
        assert r.status_code == 429
