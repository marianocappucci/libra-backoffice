"""«Apariencia»: el tema de la suite, guardado en el backoffice y empujado a las instancias del producto.

La "instancia" es una app FastAPI de verdad alcanzada por un `ASGITransport` (ver `conftest.py`), con el contrato de `libracore.tema_router`.
Se prueba lo que el backoffice decide: qué guarda, a quién le habla, qué hace con cada tipo de fallo, y que una instancia caída o vieja no
tumba a las demás.
"""
import pytest
from fastapi.testclient import TestClient

from .conftest import (
    PASSWORD, TOKEN, USUARIO, ClienteInstancia, _TransporteDeInstancias, construir_instancia_falsa, construir_settings, login,
)
from libra_backoffice.app import create_app

TEMA = {"menuActivoFondo": "#FDF2F8", "menuActivoBorde": "#F9A8D4"}
NORMALIZADO = {"menuActivoFondo": "#fdf2f8", "menuActivoBorde": "#f9a8d4"}


def _por_slug(resultados):
    return {r["slug"]: r for r in resultados}


def test_exige_sesion(cliente):
    for metodo, ruta in (("get", ""), ("put", ""), ("post", "/aplicar"), ("get", "/estado")):
        r = getattr(cliente, metodo)(f"/api/apariencia{ruta}", **({"json": {"tema": {}}} if metodo == "put" else {}))
        assert r.status_code == 401, (metodo, ruta)


def test_sin_la_feature_no_existe(tmp_path, inventario, instancias_falsas):
    app = create_app(construir_settings(tmp_path, features=("instancias", "smtp", "salud")), inventario=inventario)
    with TestClient(app, base_url="https://testserver") as c:
        assert login(c, {"username": USUARIO, "password": PASSWORD}).status_code == 200
        assert c.get("/api/apariencia").status_code == 404
        assert "apariencia" not in c.get("/api/me").json()["features"]


def test_arranca_vacio(logueado):
    assert logueado.get("/api/apariencia").json()["tema"] == {}


def test_leer_dice_de_que_producto_es(logueado):
    # La pantalla necesita el producto para mostrar los colores de siempre de ESE producto (ADR-036 de libra-ui).
    r = logueado.get("/api/apariencia").json()
    assert r["producto"] == logueado.app.state.settings.product_slug
    assert r["producto"]


def test_guardar_normaliza_persiste_y_empuja_a_cada_instancia(logueado, instancias_falsas):
    r = logueado.put("/api/apariencia", json={"tema": TEMA})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["tema"] == NORMALIZADO
    estados = {s: x["estado"] for s, x in _por_slug(cuerpo["resultados"]).items()}
    # `acme` y `beta` corren y contestan; `caida` tiene el contenedor apagado y ni se intenta.
    assert estados == {"acme": "aplicada", "beta": "aplicada", "caida": "detenida"}
    assert instancias_falsas["producto-acme"].state.tema == NORMALIZADO
    assert instancias_falsas["producto-beta"].state.tema == NORMALIZADO
    assert logueado.get("/api/apariencia").json()["tema"] == NORMALIZADO


def test_el_tema_sobrevive_a_un_reinicio_del_backoffice(logueado, tmp_path, inventario, instancias_falsas):
    logueado.put("/api/apariencia", json={"tema": TEMA})
    otra = create_app(construir_settings(tmp_path), inventario=inventario)
    with TestClient(otra, base_url="https://testserver") as c:
        assert login(c, {"username": USUARIO, "password": PASSWORD}).status_code == 200
        assert c.get("/api/apariencia").json()["tema"] == NORMALIZADO


def test_un_tema_vacio_restaura_los_valores_por_defecto_en_todas(logueado, instancias_falsas):
    logueado.put("/api/apariencia", json={"tema": TEMA})
    r = logueado.put("/api/apariencia", json={"tema": {}})
    assert r.status_code == 200
    assert instancias_falsas["producto-acme"].state.tema == {}
    assert logueado.get("/api/apariencia").json()["tema"] == {}


@pytest.mark.parametrize("malo", [{"menuActivoFondo": "verde"}, {"1x": "#ffffff"}, {"a": "#12"}, {"menuActivoFondo": ""}])
def test_lo_que_no_tiene_la_forma_es_422_y_no_se_guarda_ni_se_empuja(logueado, instancias_falsas, malo):
    assert logueado.put("/api/apariencia", json={"tema": malo}).status_code == 422
    assert logueado.get("/api/apariencia").json()["tema"] == {}
    assert instancias_falsas["producto-acme"].state.tema == {}


def test_una_instancia_caida_no_tumba_a_las_demas_y_el_tema_queda_guardado(tmp_path, inventario, instancias_falsas):
    """`beta` corre según el inventario pero no contesta (no tiene app detrás): `inalcanzable`, y `acme` igual recibe el tema."""
    app = create_app(construir_settings(tmp_path), inventario=inventario)
    app.state.cliente_instancia = ClienteInstancia(
        token=TOKEN, transport=_TransporteDeInstancias({"producto-acme": instancias_falsas["producto-acme"]}),
    )
    with TestClient(app, base_url="https://testserver") as c:
        login(c, {"username": USUARIO, "password": PASSWORD})
        r = c.put("/api/apariencia", json={"tema": TEMA}).json()
        estados = {s: x["estado"] for s, x in _por_slug(r["resultados"]).items()}
        assert estados == {"acme": "aplicada", "beta": "inalcanzable", "caida": "detenida"}
        assert instancias_falsas["producto-acme"].state.tema == NORMALIZADO
        assert c.get("/api/apariencia").json()["tema"] == NORMALIZADO


def test_una_instancia_con_un_libracore_viejo_figura_como_sin_soporte(tmp_path, inventario):
    acme = construir_instancia_falsa(tmp_path / "a.db")
    beta = construir_instancia_falsa(tmp_path / "b.db", con_tema=False)
    app = create_app(construir_settings(tmp_path), inventario=inventario)
    app.state.cliente_instancia = ClienteInstancia(
        token=TOKEN, transport=_TransporteDeInstancias({"producto-acme": acme, "producto-beta": beta}),
    )
    with TestClient(app, base_url="https://testserver") as c:
        login(c, {"username": USUARIO, "password": PASSWORD})
        r = _por_slug(c.put("/api/apariencia", json={"tema": TEMA}).json()["resultados"])
        assert r["acme"]["estado"] == "aplicada"
        assert r["beta"]["estado"] == "sin_soporte"
        assert "v1.118.0" in r["beta"]["detalle"]
        estado = _por_slug(c.get("/api/apariencia/estado").json()["instancias"])
        assert estado["beta"]["estado"] == "sin_soporte"


def test_estado_dice_quien_esta_al_dia_y_quien_quedo_atras(logueado, instancias_falsas):
    logueado.put("/api/apariencia", json={"tema": TEMA})
    instancias_falsas["producto-beta"].state.tema = {}  # alguien la restauró a mano, o se restauró un respaldo viejo
    e = logueado.get("/api/apariencia/estado").json()
    assert e["tema"] == NORMALIZADO
    estados = {s: x["estado"] for s, x in _por_slug(e["instancias"]).items()}
    assert estados == {"acme": "al_dia", "beta": "desfasada", "caida": "detenida"}


def test_reaplicar_pone_al_dia_a_las_que_quedaron_atras(logueado, instancias_falsas):
    logueado.put("/api/apariencia", json={"tema": TEMA})
    instancias_falsas["producto-beta"].state.tema = {}
    r = logueado.post("/api/apariencia/aplicar")
    assert r.status_code == 200
    assert instancias_falsas["producto-beta"].state.tema == NORMALIZADO
    estados = {x["slug"]: x["estado"] for x in logueado.get("/api/apariencia/estado").json()["instancias"]}
    assert estados["beta"] == "al_dia"


def test_el_alta_de_una_instancia_le_aplica_el_tema_de_la_suite(tmp_path, instancias_falsas, inventario):
    """Una instancia nueva nace con los colores de la suite. Mejor esfuerzo: no hay forma de que haga fallar el alta."""
    from libra_backoffice.routers import apariencia

    app = create_app(construir_settings(tmp_path), inventario=inventario)
    app.state.cliente_instancia = ClienteInstancia(token=TOKEN, transport=_TransporteDeInstancias(instancias_falsas))
    app.state.almacen_tema.guardar(NORMALIZADO)

    class _Req:  # lo mínimo que lee la función: `request.app.state`
        pass

    req = _Req()
    req.app = app
    apariencia.empujar_a_una_instancia_nueva(req, "beta")
    assert instancias_falsas["producto-beta"].state.tema == NORMALIZADO


def test_el_alta_no_falla_si_la_instancia_nueva_no_contesta(tmp_path, inventario):
    from libra_backoffice.routers import apariencia

    app = create_app(construir_settings(tmp_path), inventario=inventario)
    app.state.cliente_instancia = ClienteInstancia(token=TOKEN, transport=_TransporteDeInstancias({}))
    app.state.almacen_tema.guardar(NORMALIZADO)

    class _Req:
        pass

    req = _Req()
    req.app = app
    apariencia.empujar_a_una_instancia_nueva(req, "beta")  # no lanza
    apariencia.empujar_a_una_instancia_nueva(req, "no-existe")  # tampoco con un slug desconocido
