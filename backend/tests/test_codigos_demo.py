"""
El backoffice emitiendo códigos de acceso a la demo.

> *"los codigos de las demos las generamos desde los backoffice de las apps"*

Corre contra instancias FastAPI reales con el router real de libraauth, así que
prueba de punta a punta lo que importa: que un código emitido desde acá **sirve
para entrar a esa demo**, y que no se puede leer de vuelta.

El par que hace útil a todo el archivo son las dos instancias del conftest:
`acme` monta el ABM porque es una demo, `beta` no. Sin la segunda, un proxy que
contestara lo mismo para cualquier instancia pasaría en verde — y ahí es donde
se le muestran los códigos de la demo a quien abrió la ficha de un cliente.
"""
import pytest
from fastapi.testclient import TestClient

from libra_backoffice.app import create_app
from libra_backoffice.cliente_instancia import ClienteInstancia

from .conftest import (
    PASSWORD,
    TOKEN,
    USUARIO,
    _TransporteDeInstancias,
    construir_settings,
)

ALTA = {"etiqueta": "Estudio Pérez", "dias": 3, "usos_max": 5}


# ── Los cerrojos de siempre ───────────────────────────────────────────────

def test_pide_sesion_del_superadmin(cliente):
    assert cliente.get("/api/instancias/acme/demo-codigos").status_code == 401


def test_instancia_inexistente_es_404(logueado):
    assert logueado.get("/api/instancias/fantasma/demo-codigos").status_code == 404


def test_una_instancia_caida_es_502(logueado):
    """502 y no 500: el backoffice está bien, la instancia no contesta. La
    pantalla tiene que poder decir cuál."""
    r = logueado.get("/api/instancias/caida/demo-codigos")

    assert r.status_code == 502
    assert "caida" in r.json()["detail"]


# ── Emitir ────────────────────────────────────────────────────────────────

def test_emitir_devuelve_el_codigo(logueado):
    r = logueado.post("/api/instancias/acme/demo-codigos", json=ALTA)

    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["codigo"]
    assert cuerpo["etiqueta"] == "Estudio Pérez"
    assert cuerpo["usos_max"] == 5
    assert cuerpo["estado"] == "vigente"


def test_el_codigo_emitido_abre_esa_demo(logueado, instancias_falsas):
    """🔴 El test que hace que todo lo demás signifique algo: sin esto, "emitir"
    es un formulario que escribe una fila que nadie usa.

    Se entra por el `POST /auth/demo` de la instancia real, no por el
    backoffice: es el camino del visitante."""
    codigo = logueado.post(
        "/api/instancias/acme/demo-codigos", json=ALTA).json()["codigo"]
    demo = instancias_falsas["producto-acme"].state.demo_codigos

    assert demo.consumir(codigo)["usos"] == 1


def test_un_codigo_inventado_no_abre_nada(logueado, instancias_falsas):
    """La mitad negativa. Sin ella, el test de arriba pasaría con un
    `consumir()` que dijera que sí a cualquier cosa."""
    from libraauth.demo_codigos import CodigoInvalido
    logueado.post("/api/instancias/acme/demo-codigos", json=ALTA)
    demo = instancias_falsas["producto-acme"].state.demo_codigos

    with pytest.raises(CodigoInvalido):
        demo.consumir("ZZZZ-ZZZZ-ZZZZ")


def test_los_defaults_van_explicitos(logueado):
    """Sin cuerpo, el backoffice manda sus propios defaults: 7 días y 10
    ingresos. Están escritos en el modelo del router a propósito, para que un
    cambio de default del motor no mueva en silencio lo que emite acá."""
    cuerpo = logueado.post("/api/instancias/acme/demo-codigos", json={}).json()

    assert cuerpo["usos_max"] == 10
    assert cuerpo["etiqueta"] == ""


def test_un_alta_invalida_llega_como_422(logueado):
    """El 422 de la instancia se propaga tal cual, no convertido en genérico:
    es un error del formulario y tiene que volver al formulario."""
    r = logueado.post("/api/instancias/acme/demo-codigos", json={"dias": 0})

    assert r.status_code == 422, r.text


# ── Listar ────────────────────────────────────────────────────────────────

def test_el_listado_no_trae_los_codigos(logueado):
    """🔴 Se busca el VALOR concreto en todo el cuerpo, no la ausencia de una
    clave: si mañana viajara dentro de otro campo, un `"codigo" not in fila`
    pasaría igual."""
    codigo = logueado.post(
        "/api/instancias/acme/demo-codigos", json=ALTA).json()["codigo"]

    r = logueado.get("/api/instancias/acme/demo-codigos")

    assert r.status_code == 200, r.text
    assert r.json()["codigos"][0]["etiqueta"] == "Estudio Pérez"
    assert codigo not in r.text
    assert codigo.replace("-", "") not in r.text


def test_el_prefijo_permite_reconocerlo(logueado):
    codigo = logueado.post(
        "/api/instancias/acme/demo-codigos", json=ALTA).json()["codigo"]

    fila = logueado.get("/api/instancias/acme/demo-codigos").json()["codigos"][0]

    assert fila["prefijo"] == codigo.replace("-", "")[:4]


# ── Revocar ───────────────────────────────────────────────────────────────

def test_revocar(logueado, instancias_falsas):
    from libraauth.demo_codigos import CodigoInvalido
    creado = logueado.post("/api/instancias/acme/demo-codigos", json=ALTA).json()

    r = logueado.delete(f"/api/instancias/acme/demo-codigos/{creado['id']}")

    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "revocado"
    demo = instancias_falsas["producto-acme"].state.demo_codigos
    with pytest.raises(CodigoInvalido):
        demo.consumir(creado["codigo"])


def test_revocar_uno_inexistente_es_404(logueado):
    assert logueado.delete("/api/instancias/acme/demo-codigos/9999").status_code == 404


# ── 🔴 Cada instancia tiene los suyos, y las que no son demo no tienen ────

def test_una_instancia_que_no_es_demo_contesta_404(logueado):
    """🔴 `beta` no monta el router porque no es una demo. Es la instancia la
    que sabe, no el backoffice: guardarlo en la config del backoffice sería un
    segundo lugar donde el dato puede quedar viejo.

    Que dé 404 y no un listado vacío importa: un listado vacío se lee como
    "esta demo todavía no emitió códigos" e invita a emitir uno que no va a
    servir para nada."""
    logueado.post("/api/instancias/acme/demo-codigos", json=ALTA)

    r = logueado.get("/api/instancias/beta/demo-codigos")

    assert r.status_code == 404, r.text


def test_no_se_puede_emitir_en_una_instancia_que_no_es_demo(logueado):
    assert logueado.post(
        "/api/instancias/beta/demo-codigos", json=ALTA).status_code == 404


# ── La feature ────────────────────────────────────────────────────────────

def test_sin_la_feature_las_rutas_no_existen(tmp_path, instancias_falsas, inventario):
    """Un producto cuyo backoffice no declara `demos` no tiene estas rutas. Es
    el mismo criterio que el resto: la feature se declara por entorno."""
    app = create_app(
        construir_settings(tmp_path, features=("instancias", "smtp", "salud")),
        inventario=inventario,
    )
    app.state.cliente_instancia = ClienteInstancia(
        token=TOKEN, transport=_TransporteDeInstancias(instancias_falsas))
    with TestClient(app, base_url="https://testserver") as c:
        c.post("/api/login", json={"username": USUARIO, "password": PASSWORD})

        assert c.get("/api/instancias/acme/demo-codigos").status_code == 404


# ── 🔴 El catch-all de la SPA no es un 404 ────────────────────────────────
#
# `test_una_instancia_que_no_es_demo_contesta_404` pasa contra la instancia
# falsa del conftest, que es una app FastAPI **sin fallback**. Las seis reales
# sirven su SPA con uno, así que una ruta no montada devuelve `200` con el
# `index.html`.
#
# Medido contra `dev.libradesk.com.ar` el 2026-08-18, y peor de lo esperado: el
# `200` viene con `Content-Type: application/json` y cuerpo HTML. Un cliente
# que confíe en el content-type parsea y explota.
#
# Sin esto, la pantalla del backoffice recibía un `200` con
# `{"detail": "…el cuerpo no es JSON…"}` y mostraba un error de parseo donde la
# respuesta correcta es "esta instancia no tiene demo".

def _instancia_con_catch_all():
    """Una instancia que sirve su SPA con fallback, como las seis reales."""
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    app = FastAPI()

    @app.get("/{ruta:path}")
    def spa(ruta: str):
        # El content-type mentiroso es parte del caso medido, no un adorno: es
        # lo que hace que "mirar el content-type" no alcance para detectarlo.
        return HTMLResponse("<!doctype html><html lang=es><head></head></html>",
                            headers={"content-type": "application/json"})

    return app


def test_el_catch_all_de_la_spa_se_traduce_a_404(
    tmp_path, instancias_falsas, inventario,
):
    """🔴 El caso real de una instancia de cliente."""
    from fastapi.testclient import TestClient

    from libra_backoffice.app import create_app
    from libra_backoffice.cliente_instancia import ClienteInstancia

    from .conftest import (
        PASSWORD,
        TOKEN,
        USUARIO,
        _TransporteDeInstancias,
        construir_settings,
    )

    apps = {**instancias_falsas, "producto-beta": _instancia_con_catch_all()}
    app = create_app(construir_settings(tmp_path), inventario=inventario)
    app.state.cliente_instancia = ClienteInstancia(
        token=TOKEN, transport=_TransporteDeInstancias(apps))

    with TestClient(app, base_url="https://testserver") as c:
        c.post("/api/login", json={"username": USUARIO, "password": PASSWORD})

        r = c.get("/api/instancias/beta/demo-codigos")

        assert r.status_code == 404, r.text
        assert "no es una demo" in r.json()["detail"]


def test_el_catch_all_tampoco_deja_emitir(tmp_path, instancias_falsas, inventario):
    """La otra ruta. Sin esto, el alta contra una instancia de cliente
    devolvería 200 y la pantalla mostraría un código que no existe en ningún
    lado."""
    from fastapi.testclient import TestClient

    from libra_backoffice.app import create_app
    from libra_backoffice.cliente_instancia import ClienteInstancia

    from .conftest import (
        PASSWORD,
        TOKEN,
        USUARIO,
        _TransporteDeInstancias,
        construir_settings,
    )

    apps = {**instancias_falsas, "producto-beta": _instancia_con_catch_all()}
    app = create_app(construir_settings(tmp_path), inventario=inventario)
    app.state.cliente_instancia = ClienteInstancia(
        token=TOKEN, transport=_TransporteDeInstancias(apps))

    with TestClient(app, base_url="https://testserver") as c:
        c.post("/api/login", json={"username": USUARIO, "password": PASSWORD})

        r = c.post("/api/instancias/beta/demo-codigos", json=ALTA)

        assert r.status_code == 404, r.text


def test_la_demo_de_verdad_sigue_contestando(tmp_path, instancias_falsas, inventario):
    """🔴 La mitad que hace útil a las dos de arriba: la traducción a 404 no
    puede tragarse las respuestas buenas. `acme` sí es demo y contesta JSON."""
    from fastapi.testclient import TestClient

    from libra_backoffice.app import create_app
    from libra_backoffice.cliente_instancia import ClienteInstancia

    from .conftest import (
        PASSWORD,
        TOKEN,
        USUARIO,
        _TransporteDeInstancias,
        construir_settings,
    )

    apps = {**instancias_falsas, "producto-beta": _instancia_con_catch_all()}
    app = create_app(construir_settings(tmp_path), inventario=inventario)
    app.state.cliente_instancia = ClienteInstancia(
        token=TOKEN, transport=_TransporteDeInstancias(apps))

    with TestClient(app, base_url="https://testserver") as c:
        c.post("/api/login", json={"username": USUARIO, "password": PASSWORD})

        r = c.get("/api/instancias/acme/demo-codigos")

        assert r.status_code == 200, r.text
        assert r.json() == {"codigos": []}
