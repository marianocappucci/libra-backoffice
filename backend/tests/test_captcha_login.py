"""El captcha del login y la IP del bloqueo (F2.6, libraauth v0.39.0 y v0.40.0).

Lo que se fija, en orden de lo que se rompe sin que se note:

1. 🔴 **Que rotar `X-Forwarded-For` no esquive el bloqueo.** Con el `_ip` de
   antes —el header entero como clave— cada request con un header distinto
   contaba como otra IP, y el bloqueo por intentos no bloqueaba a nadie que
   se tomara el trabajo de cambiarlo.
2. Que sin captcha no se pruebe ninguna contraseña, y que un desafío resuelto
   sirva una sola vez: sin eso se resuelve uno y se lo reusa, y el costo por
   intento —lo único que aporta un captcha de prueba de trabajo— desaparece.
3. Que un captcha que falta no cuente como intento fallido, y que el bloqueo
   corte antes que el captcha.
4. Que la app de verdad emita el desafío caro, y no el barato de la suite.
"""
from altcha import Challenge, Payload, solve_challenge
from fastapi.testclient import TestClient
from libraauth.captcha import COSTO, Captcha
from libraauth.session_auth import CAPTCHA_INVALIDO

from libra_backoffice.app import create_app

from .conftest import PASSWORD, USUARIO, captcha_barato, construir_settings, login, resolver_captcha

CLAVE_BUENA = {"username": USUARIO, "password": PASSWORD}
CLAVE_MALA = {"username": USUARIO, "password": "mal"}

#: El par directo cuando el request viene de NPM: una IP de la red de Docker
#: (`stack_stack-net`), que `ip_del_request` reconoce como proxy de confianza.
NPM = ("172.18.0.19", 50000)


def _app(tmp_path, inventario):
    return create_app(construir_settings(tmp_path), inventario=inventario)


def _xff(forjada: str, real: str) -> dict:
    """El header como lo deja NPM: agrega la IP del par TCP al final
    (`$proxy_add_x_forwarded_for`). Lo de la izquierda lo escribió el cliente."""
    return {"X-Forwarded-For": f"{forjada}, {real}"}


# ── El desafío ──────────────────────────────────────────────────────────────

def test_el_desafio_no_pide_sesion_y_no_se_cachea(cliente):
    r = cliente.get("/api/captcha")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    # La forma que libra-ui chequea antes de dibujar el recuadro. Un 200 solo
    # no alcanza: el catch-all de la SPA también contesta 200.
    desafio = r.json()
    assert isinstance(desafio["parameters"], dict)
    assert isinstance(desafio["signature"], str)


def test_la_app_emite_desafios_con_el_costo_de_produccion(monkeypatch, tmp_path, inventario):
    """Control del conftest: la suite loguea con un captcha barato, y sin esto
    un `create_app` que armara ése también en producción pasaría en verde."""
    monkeypatch.setattr("libra_backoffice.app.Captcha", Captcha)
    with TestClient(_app(tmp_path, inventario), base_url="https://testserver") as c:
        assert c.get("/api/captcha").json()["parameters"]["cost"] == COSTO


# ── El login con captcha ────────────────────────────────────────────────────

def test_sin_captcha_no_entra_aunque_la_clave_sea_buena(cliente):
    r = cliente.post("/api/login", json=CLAVE_BUENA)
    assert r.status_code == 400
    assert r.json()["detail"] == CAPTCHA_INVALIDO
    assert cliente.get("/api/me").status_code == 401


def test_con_captcha_entra(cliente):
    assert login(cliente, CLAVE_BUENA).status_code == 200
    assert cliente.get("/api/me").status_code == 200


def test_un_desafio_resuelto_sirve_una_sola_vez(cliente):
    captcha = resolver_captcha(cliente)
    assert cliente.post("/api/login", json={**CLAVE_BUENA, "captcha": captcha}).status_code == 200
    cliente.post("/api/logout")
    r = cliente.post("/api/login", json={**CLAVE_BUENA, "captcha": captcha})
    assert r.status_code == 400
    assert cliente.get("/api/me").status_code == 401


def test_un_captcha_emitido_con_otra_clave_no_vale(cliente):
    ch = Challenge.from_dict(captcha_barato("el-secret-key-de-otra-instancia").emitir())
    ajeno = Payload(ch, solve_challenge(ch)).to_base64()
    assert cliente.post("/api/login", json={**CLAVE_BUENA, "captcha": ajeno}).status_code == 400


def test_un_captcha_roto_es_400_y_no_500(cliente):
    for basura in ("no-es-base64", "e30=", "x" * 10_000):
        assert cliente.post("/api/login", json={**CLAVE_BUENA, "captcha": basura}).status_code == 400


def test_un_captcha_que_falta_no_cuenta_como_intento_fallido(cliente):
    """Si contara, cualquiera bloquearía gratis una IP compartida: sin resolver
    nada y sin probar ninguna contraseña."""
    for _ in range(10):
        assert cliente.post("/api/login", json=CLAVE_MALA).status_code == 400
    assert login(cliente, CLAVE_BUENA).status_code == 200


def test_el_bloqueo_corta_antes_que_el_captcha(cliente):
    for _ in range(5):
        assert login(cliente, CLAVE_MALA).status_code == 401
    # Sin captcha y con la clave buena: si el captcha se mirara primero, esto
    # sería un 400 y no el 429.
    assert cliente.post("/api/login", json=CLAVE_BUENA).status_code == 429


# ── La IP del bloqueo ───────────────────────────────────────────────────────

def test_rotar_la_parte_forjada_del_header_no_esquiva_el_bloqueo(tmp_path, inventario):
    """El agujero de antes de v0.39.0, con el `_ip` propio de este backoffice."""
    with TestClient(_app(tmp_path, inventario), base_url="https://testserver", client=NPM) as c:
        for i in range(5):
            assert login(c, CLAVE_MALA, headers=_xff(f"192.0.2.{i}", "203.0.113.7")).status_code == 401
        r = login(c, CLAVE_BUENA, headers=_xff("192.0.2.250", "203.0.113.7"))
        assert r.status_code == 429


def test_el_bloqueo_de_una_ip_no_alcanza_a_otra(tmp_path, inventario):
    """El otro lado: si la IP saliera del par directo —NPM—, todos los clientes
    serían uno solo y cinco fallos de cualquiera bloquearían al resto."""
    with TestClient(_app(tmp_path, inventario), base_url="https://testserver", client=NPM) as c:
        for _ in range(5):
            login(c, CLAVE_MALA, headers=_xff("192.0.2.1", "203.0.113.7"))
        assert login(c, CLAVE_BUENA, headers=_xff("192.0.2.1", "198.51.100.9")).status_code == 200


def test_sin_pasar_por_un_proxy_el_header_no_se_cree(tmp_path, inventario):
    """Un par directo que no es proxy escribió el header entero: se cuenta por
    el par, diga lo que diga."""
    directo = ("203.0.113.50", 50000)
    with TestClient(_app(tmp_path, inventario), base_url="https://testserver", client=directo) as c:
        for i in range(5):
            login(c, CLAVE_MALA, headers={"X-Forwarded-For": f"198.51.100.{i}"})
        assert login(c, CLAVE_BUENA, headers={"X-Forwarded-For": "198.51.100.200"}).status_code == 429
