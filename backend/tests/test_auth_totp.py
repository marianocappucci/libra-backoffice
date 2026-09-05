"""El login del backoffice con lo que trae libraauth v0.36.0 (F2): segundo
factor TOTP y bloqueo por intentos que sobrevive a un reinicio.

`test_auth.py` queda como estaba: sin las dos variables de entorno nuevas,
el login es el de siempre."""
import base64

import pytest
from fastapi.testclient import TestClient
from libraauth import totp
from libraauth.session_auth import SERVICE_TOKEN_ENV  # noqa: F401  (documenta la dependencia del conftest)

from libra_backoffice.app import create_app
from libra_backoffice.cliente_instancia import ClienteInstancia

from .conftest import PASSWORD, TOKEN, USUARIO, _TransporteDeInstancias, construir_settings

SECRETO = base64.b32encode(b"12345678901234567890").decode()
AHORA = 1234567890
CODIGO_AHORA = "005924"  # el vector del RFC 6238 para ese instante


def _cliente(tmp_path, instancias_falsas, inventario):
    """Igual que el fixture `cliente` del conftest, pero construido DESPUES de
    tocar el entorno: `AdminAuth` lee las variables al crearse."""
    app = create_app(construir_settings(tmp_path), inventario=inventario)
    app.state.cliente_instancia = ClienteInstancia(
        token=TOKEN, transport=_TransporteDeInstancias(instancias_falsas)
    )
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def reloj_fijo(monkeypatch):
    monkeypatch.setattr("libraauth.totp.time.time", lambda: AHORA)


def test_sin_secreto_las_opciones_dicen_que_no_hay_segundo_factor(cliente):
    assert cliente.get("/api/login/opciones").json() == {"totp": False}


def test_sin_secreto_un_codigo_de_mas_no_molesta(cliente):
    resp = cliente.post("/api/login", json={"username": USUARIO, "password": PASSWORD, "codigo": "000000"})
    assert resp.status_code == 200


class TestConSegundoFactor:
    @pytest.fixture
    def con_totp(self, monkeypatch, tmp_path, instancias_falsas, inventario, reloj_fijo):
        monkeypatch.setenv("ADMIN_PANEL_TOTP_SECRET", SECRETO)
        with _cliente(tmp_path, instancias_falsas, inventario) as c:
            yield c

    def test_las_opciones_lo_anuncian(self, con_totp):
        assert con_totp.get("/api/login/opciones").json() == {"totp": True}

    def test_sin_codigo_401(self, con_totp):
        resp = con_totp.post("/api/login", json={"username": USUARIO, "password": PASSWORD})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Usuario, contraseña o código incorrectos."

    def test_codigo_incorrecto_es_el_mismo_401_que_clave_incorrecta(self, con_totp):
        """Un solo mensaje: no se le dice a quien prueba cuál de los dos acertó."""
        a = con_totp.post("/api/login", json={"username": USUARIO, "password": PASSWORD, "codigo": "123456"})
        b = con_totp.post("/api/login", json={"username": USUARIO, "password": "mal", "codigo": CODIGO_AHORA})
        assert a.status_code == b.status_code == 401
        assert a.json() == b.json()

    def test_con_codigo_correcto_entra(self, con_totp):
        resp = con_totp.post("/api/login", json={"username": USUARIO, "password": PASSWORD, "codigo": CODIGO_AHORA})
        assert resp.status_code == 200
        assert con_totp.get("/api/me").status_code == 200

    def test_el_mismo_codigo_no_entra_dos_veces(self, con_totp):
        assert con_totp.post("/api/login", json={"username": USUARIO, "password": PASSWORD, "codigo": CODIGO_AHORA}).status_code == 200
        con_totp.post("/api/logout")
        assert con_totp.post("/api/login", json={"username": USUARIO, "password": PASSWORD, "codigo": CODIGO_AHORA}).status_code == 401

    def test_los_intentos_fallidos_con_codigo_tambien_cuentan_para_el_bloqueo(self, con_totp):
        for _ in range(5):
            con_totp.post("/api/login", json={"username": USUARIO, "password": PASSWORD, "codigo": "000000"})
        resp = con_totp.post("/api/login", json={"username": USUARIO, "password": PASSWORD, "codigo": CODIGO_AHORA})
        assert resp.status_code == 429


def test_secreto_invalido_no_deja_levantar_la_app(monkeypatch, tmp_path, inventario):
    """Fail-fast: un segundo factor mal cargado que nunca valida parece que está."""
    monkeypatch.setenv("ADMIN_PANEL_TOTP_SECRET", "esto-no-es-base32!")
    with pytest.raises(RuntimeError, match="ADMIN_PANEL_TOTP_SECRET"):
        create_app(construir_settings(tmp_path), inventario=inventario)


def test_el_bloqueo_sobrevive_a_un_reinicio_del_backoffice(monkeypatch, tmp_path, instancias_falsas, inventario):
    """El criterio de salida de la F2: cinco fallos, reinicio, sigue bloqueado."""
    monkeypatch.setenv("ADMIN_PANEL_ESTADO_PATH", str(tmp_path / "estado" / "login.json"))
    with _cliente(tmp_path, instancias_falsas, inventario) as c:
        for _ in range(5):
            c.post("/api/login", json={"username": USUARIO, "password": "mal"})
        assert c.post("/api/login", json={"username": USUARIO, "password": PASSWORD}).status_code == 429
    # "Reinicio": otra app, otro AdminAuth, mismo archivo.
    with _cliente(tmp_path, instancias_falsas, inventario) as c2:
        assert c2.post("/api/login", json={"username": USUARIO, "password": PASSWORD}).status_code == 429
    assert (tmp_path / "estado" / "login.json").exists()


def test_el_codigo_del_rfc_es_el_que_se_usa_en_estos_tests():
    """Control del fixture: si el vector cambia, los tests de arriba se caen
    por el motivo equivocado."""
    assert totp.codigo(totp.decodificar_secreto(SECRETO), AHORA // 30) == CODIGO_AHORA
