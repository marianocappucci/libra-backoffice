"""Login en dos pasos (F4, 2026-09-13, libraauth v0.42.0): `POST /api/login`
sin `codigo` y con segundo factor no loguea — devuelve un desafío firmado de
vida corta— y `POST /api/login/codigo` es el segundo paso, el que recién ahí
abre la sesión. El camino de un solo paso (`codigo` ya en `/api/login`) sigue
existiendo sin cambios, para el cliente viejo.

Cubre las dos rutas por las que `AdminAuth` puede tener un segundo factor
activo — mismo criterio que el resto de la suite (`test_auth_totp.py`,
`test_seguridad_totp.py`):

- **origen entorno** (`ADMIN_PANEL_TOTP_SECRET`, el secreto fijo del vector
  RFC 6238 que usa `test_auth_totp.py`);
- **origen archivo** (`ADMIN_PANEL_ESTADO_PATH`, secreto enrolado en runtime
  vía `/api/seguridad/totp/iniciar` + `/confirmar`, como en
  `test_seguridad_totp.py`).

`reloj_fijo` va SIEMPRE primero en la firma de un fixture o test que combine
reloj congelado con login: pisa `time.time()` para TODO el proceso, incluida
la cookie de sesión de `itsdangerous` — ver el comentario de
`test_seguridad_totp.py`.
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
#: El mismo vector del RFC 6238 que `test_auth_totp.py`, para el origen entorno.
SECRETO_ENTORNO = base64.b32encode(b"12345678901234567890").decode()


def _codigo(secreto: str, paso: int = PASO) -> str:
    return totp_mod.codigo(totp_mod.decodificar_secreto(secreto), paso)


@pytest.fixture
def reloj_fijo(monkeypatch):
    monkeypatch.setattr("libraauth.totp.time.time", lambda: AHORA)


def _cliente(tmp_path, instancias_falsas, inventario) -> TestClient:
    """Igual que el fixture `cliente` del conftest, pero construido DESPUÉS de
    tocar el entorno: `AdminAuth` lee las variables al crearse."""
    app = create_app(construir_settings(tmp_path), inventario=inventario)
    app.state.cliente_instancia = ClienteInstancia(
        token=TOKEN, transport=_TransporteDeInstancias(instancias_falsas)
    )
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def con_entorno(monkeypatch, tmp_path, instancias_falsas, inventario, reloj_fijo):
    """Segundo factor por `ADMIN_PANEL_TOTP_SECRET`. El código de `PASO` queda
    sin usar: nada lo consumió todavía."""
    monkeypatch.setenv("ADMIN_PANEL_TOTP_SECRET", SECRETO_ENTORNO)
    with _cliente(tmp_path, instancias_falsas, inventario) as c:
        yield c, SECRETO_ENTORNO


@pytest.fixture
def con_archivo(monkeypatch, tmp_path, instancias_falsas, inventario, reloj_fijo):
    """Segundo factor enrolado en runtime. El código de `PASO` lo consume la
    confirmación (`ultimo_paso_totp` queda en `PASO`): el primer código
    disponible para loguearse es el de `PASO + 1`, igual que en
    `test_seguridad_totp.py`."""
    monkeypatch.setenv("ADMIN_PANEL_ESTADO_PATH", str(tmp_path / "estado" / "login.json"))
    with _cliente(tmp_path, instancias_falsas, inventario) as c:
        resp = login(c, {"username": USUARIO, "password": PASSWORD})
        assert resp.status_code == 200, resp.text
        secreto = c.post("/api/seguridad/totp/iniciar").json()["secreto"]
        confirmado = c.post("/api/seguridad/totp/confirmar", json={"codigo": _codigo(secreto)})
        assert confirmado.status_code == 200, confirmado.text
        c.post("/api/logout")
        yield c, secreto


@pytest.fixture(params=["entorno", "archivo"])
def con_totp(request):
    """Parametriza los tests comunes sobre las dos rutas de segundo factor.

    El código de `PASO + 1` está disponible sin usar en las dos: en
    `con_entorno` porque no se usó ningún código todavía, en `con_archivo`
    porque `PASO` es justo el que gastó la confirmación.
    """
    cliente, secreto = request.getfixturevalue(f"con_{request.param}")
    return cliente, secreto, _codigo(secreto, PASO + 1)


# ── Sin segundo factor: el paso 1 no cambia ─────────────────────────────────

def test_sin_segundo_factor_el_paso_1_loguea_como_siempre(cliente):
    resp = login(cliente, {"username": USUARIO, "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.json() == {"username": USUARIO}
    assert "set-cookie" in resp.headers
    assert cliente.get("/api/me").status_code == 200


# ── Paso 1 con segundo factor ───────────────────────────────────────────────

def test_paso_1_con_segundo_factor_devuelve_desafio_sin_cookie(con_totp):
    cliente, _secreto, _codigo_disponible = con_totp
    resp = login(cliente, {"username": USUARIO, "password": PASSWORD})
    assert resp.status_code == 200
    datos = resp.json()
    assert datos["requiere_codigo"] is True
    assert isinstance(datos["desafio"], str) and datos["desafio"]
    assert "set-cookie" not in resp.headers
    assert resp.headers["cache-control"] == "no-store"
    # No hubo cookie: la sesión no se abrió con sólo pasar la clave.
    assert cliente.get("/api/me").status_code == 401


def test_paso_1_clave_mala_401_y_suma_intento(con_totp):
    cliente, _secreto, _codigo_disponible = con_totp
    resp = login(cliente, {"username": USUARIO, "password": "mal"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Usuario o contraseña incorrectos."
    # Cuenta para el bloqueo: cuatro más alcanzan para el 429.
    for _ in range(4):
        login(cliente, {"username": USUARIO, "password": "mal"})
    assert login(cliente, {"username": USUARIO, "password": PASSWORD}).status_code == 429


# ── Paso 2 ───────────────────────────────────────────────────────────────────

def test_paso_2_con_codigo_correcto_loguea(con_totp):
    cliente, _secreto, codigo_disponible = con_totp
    desafio = login(cliente, {"username": USUARIO, "password": PASSWORD}).json()["desafio"]
    resp = cliente.post("/api/login/codigo", json={"desafio": desafio, "codigo": codigo_disponible})
    assert resp.status_code == 200
    assert resp.json() == {"username": USUARIO}
    assert "set-cookie" in resp.headers
    assert resp.headers["cache-control"] == "no-store"
    assert cliente.get("/api/me").status_code == 200


def test_paso_2_codigo_incorrecto_401(con_totp):
    cliente, _secreto, _codigo_disponible = con_totp
    desafio = login(cliente, {"username": USUARIO, "password": PASSWORD}).json()["desafio"]
    resp = cliente.post("/api/login/codigo", json={"desafio": desafio, "codigo": "000000"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Código incorrecto."
    # Que cuenta para el bloqueo lo prueba, con el detalle de qué mensaje pisa
    # a cuál, `test_paso_2_5_fallos_bloquea_incluso_con_codigo_correcto`.


def test_paso_2_desafio_inventado_401_vencido_y_suma_intento(con_totp):
    cliente, *_ = con_totp
    for _ in range(5):
        resp = cliente.post(
            "/api/login/codigo", json={"desafio": "esto-no-es-un-desafio", "codigo": "000000"}
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "El código venció: volvé a ingresar."
    resp = cliente.post(
        "/api/login/codigo", json={"desafio": "esto-no-es-un-desafio", "codigo": "000000"}
    )
    assert resp.status_code == 429


def test_paso_2_desafio_vencido_401_y_suma_intento(con_totp, monkeypatch):
    cliente, _secreto, codigo_disponible = con_totp
    desafio = login(cliente, {"username": USUARIO, "password": PASSWORD}).json()["desafio"]
    # El desafío es válido en este instante; lo que se mueve es la ventana de
    # vigencia, no el reloj — más simple y no toca la cookie de sesión (que
    # usa el mismo `time.time()` de itsdangerous).
    monkeypatch.setattr("libraauth.admin_auth.DESAFIO_TOTP_SEGUNDOS", -1)
    for _ in range(5):
        resp = cliente.post("/api/login/codigo", json={"desafio": desafio, "codigo": codigo_disponible})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "El código venció: volvé a ingresar."
    resp = cliente.post("/api/login/codigo", json={"desafio": desafio, "codigo": codigo_disponible})
    assert resp.status_code == 429


def test_paso_2_5_fallos_bloquea_incluso_con_codigo_correcto(con_totp):
    cliente, _secreto, codigo_disponible = con_totp
    # Un solo desafío para los seis intentos: `validar_desafio_totp` no lo
    # invalida ante un código incorrecto, sólo cuando lo consume uno correcto
    # (que acá nunca pasa). Pedir uno nuevo por intento mezclaría el bloqueo
    # del paso 2 con el del paso 1 — éste sólo prueba el del paso 2.
    desafio = login(cliente, {"username": USUARIO, "password": PASSWORD}).json()["desafio"]
    for _ in range(5):
        resp = cliente.post("/api/login/codigo", json={"desafio": desafio, "codigo": "000000"})
        assert resp.status_code == 401
    resp = cliente.post("/api/login/codigo", json={"desafio": desafio, "codigo": codigo_disponible})
    assert resp.status_code == 429


# ── El código no se reusa entre caminos ─────────────────────────────────────

def test_el_mismo_codigo_no_sirve_dos_veces_por_el_paso_2(con_totp):
    cliente, _secreto, codigo_disponible = con_totp
    desafio_1 = login(cliente, {"username": USUARIO, "password": PASSWORD}).json()["desafio"]
    assert cliente.post(
        "/api/login/codigo", json={"desafio": desafio_1, "codigo": codigo_disponible}
    ).status_code == 200
    cliente.post("/api/logout")
    desafio_2 = login(cliente, {"username": USUARIO, "password": PASSWORD}).json()["desafio"]
    resp = cliente.post("/api/login/codigo", json={"desafio": desafio_2, "codigo": codigo_disponible})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Código incorrecto."


def test_el_codigo_usado_por_el_paso_2_no_sirve_en_el_camino_de_un_paso(con_totp):
    cliente, _secreto, codigo_disponible = con_totp
    desafio = login(cliente, {"username": USUARIO, "password": PASSWORD}).json()["desafio"]
    assert cliente.post(
        "/api/login/codigo", json={"desafio": desafio, "codigo": codigo_disponible}
    ).status_code == 200
    cliente.post("/api/logout")
    resp = login(cliente, {"username": USUARIO, "password": PASSWORD, "codigo": codigo_disponible})
    assert resp.status_code == 401


# ── El camino de un paso sigue andando ──────────────────────────────────────

def test_el_camino_de_un_paso_con_codigo_sigue_andando(con_totp):
    cliente, _secreto, codigo_disponible = con_totp
    resp = login(cliente, {"username": USUARIO, "password": PASSWORD, "codigo": codigo_disponible})
    assert resp.status_code == 200
    assert resp.json() == {"username": USUARIO}
    assert "set-cookie" in resp.headers
    assert cliente.get("/api/me").status_code == 200


# ── El desafío no es una cookie ─────────────────────────────────────────────

def test_el_desafio_no_sirve_como_cookie_de_sesion(con_totp):
    cliente, _secreto, _codigo_disponible = con_totp
    desafio = login(cliente, {"username": USUARIO, "password": PASSWORD}).json()["desafio"]
    cliente.cookies.set("cladmin_session", desafio)
    assert cliente.get("/api/me").status_code == 401
