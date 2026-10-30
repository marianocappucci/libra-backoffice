"""«Marca» de una instancia: lo que el backoffice decide al hablarle a `libracore.marca_router` y `libracore.terminos_propios`.

La "instancia" es una app FastAPI de verdad con los routers REALES del motor (ver `conftest.py`, `con_marca=True`), alcanzada por un
`ASGITransport`. Lo que fijan estos tests, en orden de lo que se rompe sin que se note:

1. 🔴 **Que no se deje sin entrar a los usuarios de un cliente.** Una marca propia sin Términos propios deja la instancia frenada
   (libraauth ADR-030). Guardar la marca antes que los términos se rechaza, y quitar los términos de una instancia con marca también.
2. 🔴 **Que «Apariencia» no le pise la suya a una instancia de marca blanca** (el tema de la suite es una sola elección para todas).
3. Que el logo (un archivo, multipart) llegue entero a la instancia, y que la vista previa salga por la sesión del superadmin.
4. Que cada fallo de la instancia —vieja, caída, que rechaza el dato— llegue con su código y no como un 500 del backoffice.
"""
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from libra_backoffice.app import create_app

from .conftest import (
    PASSWORD, TOKEN, USUARIO, ClienteInstancia, _TransporteDeInstancias, construir_instancia_falsa, construir_settings, login,
)

FEATURES = ("instancias", "smtp", "usuarios", "salud", "demos", "reenvio-correo", "apariencia", "marca")
TEXTO = "# Términos de Gestión Sur\n\n1. El servicio lo presta Gestión Sur.\n2. Los datos son del Cliente.\n"
TERMINOS = {"version": "2026-1", "vigente_desde": "01-11-2026", "texto": TEXTO}
RUTA = "/api/instancias/acme/marca"


def png(ancho=400, alto=300, color=(200, 30, 30, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (ancho, alto), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def datos_de_la_instancia(tmp_path, monkeypatch):
    """El `config.json` y el directorio de la marca del proceso de la instancia falsa: uno propio de cada prueba."""
    from libracore import config_manager

    monkeypatch.setattr(config_manager, "CONFIG_PATH", str(tmp_path / "config-instancia.json"))
    monkeypatch.setattr(config_manager, "MARCA_DIR", str(tmp_path / "marca"))
    monkeypatch.setattr(config_manager, "LOGO_DIR", str(tmp_path / "logos"))
    return config_manager


def _backoffice(tmp_path, inventario, instancias, features=FEATURES):
    app = create_app(construir_settings(tmp_path, features=features), inventario=inventario)
    app.state.cliente_instancia = ClienteInstancia(token=TOKEN, transport=_TransporteDeInstancias(instancias))
    return app


@pytest.fixture
def bo(tmp_path, inventario, datos_de_la_instancia):
    """El backoffice logueado. `acme` tiene la marca del motor; `beta` es una instancia vieja (sin las rutas); `caida` no responde."""
    instancias = {
        "producto-acme": construir_instancia_falsa(tmp_path / "acme.db", con_marca=True),
        "producto-beta": construir_instancia_falsa(tmp_path / "beta.db"),  # con_tema: la ruta que no existe es un 404
    }
    with TestClient(_backoffice(tmp_path, inventario, instancias), base_url="https://testserver") as c:
        assert login(c, {"username": USUARIO, "password": PASSWORD}).status_code == 200
        yield c


def cargar_terminos(bo, **cambios):
    r = bo.put(f"{RUTA}/terminos", json={**TERMINOS, **cambios})
    assert r.status_code == 200, r.text
    return r.json()


# ── Acceso ─────────────────────────────────────────────────────────────────

def test_exige_sesion(cliente):
    for metodo, sufijo in (("get", ""), ("put", ""), ("post", "/logo"), ("delete", "/logo"), ("delete", ""),
                           ("get", "/logo"), ("put", "/terminos"), ("delete", "/terminos")):
        r = getattr(cliente, metodo)(f"{RUTA}{sufijo}")
        assert r.status_code in (401, 404), (metodo, sufijo, r.status_code)  # 404: este `cliente` no tiene la feature
    r = cliente.get("/api/me")
    assert r.status_code == 401


def test_sin_la_feature_no_existe(tmp_path, inventario):
    app = _backoffice(tmp_path, inventario, {}, features=("instancias", "smtp", "salud"))
    with TestClient(app, base_url="https://testserver") as c:
        assert login(c, {"username": USUARIO, "password": PASSWORD}).status_code == 200
        assert c.get(RUTA).status_code == 404
        assert "marca" not in c.get("/api/me").json()["features"]


def test_con_la_feature_la_ve_el_frontend(bo):
    assert "marca" in bo.get("/api/me").json()["features"]


# ── Leer ───────────────────────────────────────────────────────────────────

def test_una_instancia_sin_marca(bo):
    r = bo.get(RUTA)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["marca"]["propia"] is False and cuerpo["marca"]["terminos_propios"] is False
    assert cuerpo["terminos"]["cargados"] is False
    assert cuerpo["producto"] == "gestiolibra"


def test_una_instancia_inexistente_es_404(bo):
    assert bo.get("/api/instancias/fantasma/marca").status_code == 404


# ── 1. Primero los términos, después la marca ───────────────────────────────

def test_guardar_la_marca_sin_terminos_se_rechaza_y_no_deja_nada(bo):
    r = bo.put(RUTA, json={"nombre": "Gestión Sur", "color": "#336699"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "terminos_primero"
    assert "Cargá primero los Términos" in r.json()["detail"]["mensaje"]
    assert bo.get(RUTA).json()["marca"]["propia"] is False  # la instancia no se tocó


def test_subir_el_logo_sin_terminos_tambien_se_rechaza(bo):
    r = bo.post(f"{RUTA}/logo", files={"logo": ("l.png", png(), "image/png")})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "terminos_primero"
    assert bo.get(f"{RUTA}/logo").status_code == 404


def test_con_los_terminos_cargados_la_marca_se_guarda(bo):
    t = cargar_terminos(bo)
    assert t["cargados"] is True and t["version"] == "2026-1" and len(t["hash"]) == 64
    r = bo.put(RUTA, json={"nombre": "  Gestión Sur  ", "nombre_corto": "GSur", "color": "#336699"})
    assert r.status_code == 200, r.text
    assert r.json()["propia"] is True and r.json()["nombre"] == "Gestión Sur" and r.json()["terminos_propios"] is True
    leida = bo.get(RUTA).json()
    assert leida["marca"]["color"] == "#336699" and leida["terminos"]["version"] == "2026-1"


def test_el_texto_de_los_terminos_no_vuelve_a_la_pantalla(bo):
    cargar_terminos(bo)
    assert "Gestión Sur" not in json.dumps(bo.get(RUTA).json()["terminos"])


def test_entendiendo_que_queda_frenada_se_puede_guardar_igual(bo):
    r = bo.put(RUTA, json={"nombre": "Gestión Sur", "sin_terminos": True})
    assert r.status_code == 200, r.text
    estado = bo.get(RUTA).json()
    assert estado["marca"]["propia"] is True and estado["terminos"]["cargados"] is False


def test_el_permiso_para_seguir_sin_terminos_no_se_manda_a_la_instancia(bo, datos_de_la_instancia):
    bo.put(RUTA, json={"nombre": "Gestión Sur", "sin_terminos": True})
    assert "sin_terminos" not in json.dumps(datos_de_la_instancia.load().get("marca", {}))


def test_una_instancia_que_ya_es_propia_no_pide_los_terminos_para_cambiar_el_nombre(bo):
    bo.put(RUTA, json={"nombre": "Gestión Sur", "sin_terminos": True})
    r = bo.put(RUTA, json={"nombre": "Gestión Sur SRL"})
    assert r.status_code == 200 and r.json()["nombre"] == "Gestión Sur SRL"


def test_quitar_los_terminos_de_una_instancia_con_marca_pide_confirmar(bo):
    cargar_terminos(bo)
    bo.put(RUTA, json={"nombre": "Gestión Sur"})
    r = bo.delete(f"{RUTA}/terminos")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "quedaria_frenada"
    assert bo.get(RUTA).json()["terminos"]["cargados"] is True  # siguen ahí

    assert bo.delete(f"{RUTA}/terminos?confirmar=true").json()["cargados"] is False


def test_quitar_los_terminos_de_una_instancia_sin_marca_no_pide_nada(bo):
    cargar_terminos(bo)
    assert bo.delete(f"{RUTA}/terminos").status_code == 200


# ── Términos ───────────────────────────────────────────────────────────────

def test_la_misma_version_con_otro_texto_llega_como_409_con_el_motivo_de_la_instancia(bo):
    cargar_terminos(bo)
    r = bo.put(f"{RUTA}/terminos", json={**TERMINOS, "texto": TEXTO + "3. Nueva.\n"})
    assert r.status_code == 409 and "otro número de versión" in r.json()["detail"]


@pytest.mark.parametrize("cambio", [{"version": "con espacios"}, {"vigente_desde": "2026-11-01"}, {"texto": "   "}])
def test_lo_que_la_instancia_rechaza_llega_como_422(bo, cambio):
    assert bo.put(f"{RUTA}/terminos", json={**TERMINOS, **cambio}).status_code == 422
    assert bo.get(RUTA).json()["terminos"]["cargados"] is False


def test_un_texto_gigante_no_pasa_de_largo(bo):
    assert bo.put(f"{RUTA}/terminos", json={**TERMINOS, "texto": "x" * 300_001}).status_code == 422


def test_volver_a_la_marca_del_producto_se_lleva_tambien_los_terminos(bo):
    cargar_terminos(bo)
    bo.put(RUTA, json={"nombre": "Gestión Sur"})
    r = bo.delete(RUTA)
    assert r.status_code == 200 and r.json()["propia"] is False and r.json()["terminos_propios"] is False
    assert bo.get(RUTA).json()["terminos"]["cargados"] is False


# ── 3. El logo ─────────────────────────────────────────────────────────────

def test_el_logo_llega_entero_a_la_instancia_y_se_ve_en_la_vista_previa(bo):
    cargar_terminos(bo)
    r = bo.post(f"{RUTA}/logo", files={"logo": ("logo.png", png(800, 400), "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["propia"] is True and r.json()["logo"].startswith("/api/marca/logo?v=")

    vista = bo.get(f"{RUTA}/logo")
    assert vista.status_code == 200 and vista.headers["content-type"] == "image/png"
    assert vista.headers["cache-control"] == "private, no-cache"
    assert Image.open(io.BytesIO(vista.content)).size == (800, 400)


def test_quitar_el_logo_conserva_el_resto(bo):
    cargar_terminos(bo)
    bo.put(RUTA, json={"nombre": "Gestión Sur"})
    bo.post(f"{RUTA}/logo", files={"logo": ("logo.png", png(), "image/png")})
    r = bo.delete(f"{RUTA}/logo")
    assert r.status_code == 200 and r.json()["logo"] == "" and r.json()["nombre"] == "Gestión Sur"
    assert bo.get(f"{RUTA}/logo").status_code == 404


def test_un_logo_de_mas_de_un_mega_se_corta_antes_de_llegar_a_la_instancia(bo, datos_de_la_instancia):
    cargar_terminos(bo)
    r = bo.post(f"{RUTA}/logo", files={"logo": ("l.png", b"\x00" * 1_000_010, "image/png")})
    assert r.status_code == 413
    assert bo.get(RUTA).json()["marca"]["logo"] == ""


@pytest.mark.parametrize(
    "datos, nombre", [(b"no soy una imagen", "l.png"), (b"<svg><script>alert(1)</script></svg>", "l.svg"), (png(100, 100), "chico.png")],
)
def test_un_logo_que_la_instancia_rechaza_llega_como_422(bo, datos, nombre):
    cargar_terminos(bo)
    assert bo.post(f"{RUTA}/logo", files={"logo": (nombre, datos, "image/png")}).status_code == 422


def test_sin_logo_la_vista_previa_es_404_y_no_un_error(bo):
    assert bo.get(f"{RUTA}/logo").status_code == 404


def test_el_logo_sin_terminos_con_permiso_explicito(bo):
    r = bo.post(f"{RUTA}/logo?sin_terminos=true", files={"logo": ("l.png", png(), "image/png")})
    assert r.status_code == 200 and r.json()["propia"] is True


# ── 4. Los fallos de la instancia ──────────────────────────────────────────

def test_una_instancia_vieja_sin_las_rutas_dice_que_hay_que_actualizarla(bo):
    # `beta` es una instancia con tema y sin marca: la ruta que no existe contesta 404.
    for metodo, sufijo in (("get", ""), ("put", "/terminos")):
        kwargs = {"json": TERMINOS} if metodo == "put" else {}
        r = getattr(bo, metodo)(f"/api/instancias/beta/marca{sufijo}", **kwargs)
        assert r.status_code == 409 and "hay que actualizarla" in r.json()["detail"], (metodo, sufijo)


def test_una_instancia_con_el_fallback_de_la_spa_tambien(tmp_path, inventario, datos_de_la_instancia):
    """Sin `con_tema` la instancia contesta 200 con HTML a cualquier GET (el fallback de la SPA): es lo que pasa en producción con un
    libracore viejo. El cuerpo que no es JSON se traduce al mismo mensaje."""
    instancias = {"producto-acme": construir_instancia_falsa(tmp_path / "acme.db", con_tema=False)}
    with TestClient(_backoffice(tmp_path, inventario, instancias), base_url="https://testserver") as c:
        login(c, {"username": USUARIO, "password": PASSWORD})
        r = c.get(RUTA)
        assert r.status_code == 409 and "hay que actualizarla" in r.json()["detail"]
        assert c.get(f"{RUTA}/logo").status_code == 404  # y la vista previa no devuelve el HTML como si fuera una imagen


def test_una_instancia_caida_es_un_502_con_el_slug(bo):
    r = bo.get("/api/instancias/caida/marca")
    assert r.status_code == 502 and "caida" in r.json()["detail"]


def test_el_backoffice_le_habla_a_la_instancia_con_el_token_de_servicio(bo):
    """Si no mandara el token, la guarda de la instancia (admin o servicio) rechazaría la escritura."""
    cargar_terminos(bo)
    assert bo.put(RUTA, json={"nombre": "Gestión Sur"}).status_code == 200


# ── El contrato con el motor ───────────────────────────────────────────────

def test_el_contrato_de_la_marca_real(tmp_path, datos_de_la_instancia):
    """Lo que el backoffice lee de la instancia, medido contra el router REAL del motor. Si `libracore` renombra `propia` o
    `terminos_propios`, este test se pone rojo ANTES que la pantalla: el doble `marca_falsa` de `conftest.py` descansa en esto."""
    instancia = construir_instancia_falsa(tmp_path / "x.db", con_marca=True)
    c = TestClient(instancia)
    marca = c.get("/api/marca").json()
    assert set(marca) >= {"propia", "nombre", "nombre_corto", "color", "logo", "terminos_propios"}
    assert marca["propia"] is False and marca["terminos_propios"] is False
    # La escritura va por el token de servicio (la guarda de admin o servicio del producto); lo que devuelve es lo que lee la pantalla.
    encabezado = {"x-internal-auth": TOKEN}
    cargados = c.put("/api/marca/terminos", json=TERMINOS, headers=encabezado)
    assert cargados.status_code == 200, cargados.text
    assert cargados.json().keys() >= {"cargados", "version", "vigente_desde", "hash", "caracteres"}
    assert c.get("/api/marca").json()["terminos_propios"] is True


# ── 2. «Apariencia» no le pisa la suya a una instancia de marca blanca ──────

def _con_apariencia(tmp_path, inventario, acme_marca, beta_marca=None):
    instancias = {
        "producto-acme": construir_instancia_falsa(tmp_path / "acme.db", marca_falsa=acme_marca),
        "producto-beta": construir_instancia_falsa(tmp_path / "beta.db", marca_falsa=beta_marca),
    }
    return _backoffice(tmp_path, inventario, instancias), instancias


def test_apariencia_no_empuja_el_tema_a_una_instancia_con_marca_propia(tmp_path, inventario):
    app, instancias = _con_apariencia(tmp_path, inventario, {"propia": True, "nombre": "Gestión Sur"}, {"propia": False})
    with TestClient(app, base_url="https://testserver") as c:
        login(c, {"username": USUARIO, "password": PASSWORD})
        r = c.put("/api/apariencia", json={"tema": {"menuActivoFondo": "#FDF2F8"}})
        assert r.status_code == 200, r.text
        por_slug = {x["slug"]: x for x in r.json()["resultados"]}
        assert por_slug["acme"]["estado"] == "marca_propia" and "marca propia" in por_slug["acme"]["detalle"]
        assert por_slug["beta"]["estado"] == "aplicada"
    assert instancias["producto-acme"].state.tema == {}  # a la de marca propia no llegó
    assert instancias["producto-beta"].state.tema == {"menuActivoFondo": "#fdf2f8"}


def test_reaplicar_y_el_estado_tambien_la_saltean(tmp_path, inventario):
    app, instancias = _con_apariencia(tmp_path, inventario, {"propia": True}, {"propia": False})
    with TestClient(app, base_url="https://testserver") as c:
        login(c, {"username": USUARIO, "password": PASSWORD})
        c.put("/api/apariencia", json={"tema": {"menuActivoFondo": "#FDF2F8"}})
        aplicar = {x["slug"]: x["estado"] for x in c.post("/api/apariencia/aplicar").json()["resultados"]}
        estado = {x["slug"]: x["estado"] for x in c.get("/api/apariencia/estado").json()["instancias"]}
    assert aplicar["acme"] == "marca_propia" and estado["acme"] == "marca_propia"
    assert aplicar["beta"] == "aplicada" and estado["beta"] == "al_dia"
    assert instancias["producto-acme"].state.tema == {}


def test_una_marca_que_no_es_propia_no_cambia_nada(tmp_path, inventario):
    app, instancias = _con_apariencia(tmp_path, inventario, {"propia": False}, {"propia": False})
    with TestClient(app, base_url="https://testserver") as c:
        login(c, {"username": USUARIO, "password": PASSWORD})
        r = c.put("/api/apariencia", json={"tema": {"menuActivoFondo": "#FDF2F8"}})
        por_slug = {x["slug"]: x["estado"] for x in r.json()["resultados"]}
        assert por_slug["acme"] == por_slug["beta"] == "aplicada"  # (`caida` está detenida: no cuenta)
    assert instancias["producto-acme"].state.tema == {"menuActivoFondo": "#fdf2f8"}


@pytest.mark.parametrize("marca", [None, {"propia": "true"}, {"propia": 1}, {"nombre": "x"}, [], "texto"])
def test_solo_un_true_de_verdad_cuenta_como_marca_propia(tmp_path, inventario, marca):
    """`"true"` o `1` no son `True`: una instancia que contesta cualquier cosa rara sigue recibiendo el tema como siempre."""
    app, _ = _con_apariencia(tmp_path, inventario, marca, marca)
    with TestClient(app, base_url="https://testserver") as c:
        login(c, {"username": USUARIO, "password": PASSWORD})
        r = c.put("/api/apariencia", json={"tema": {"menuActivoFondo": "#FDF2F8"}})
        assert "marca_propia" not in {x["estado"] for x in r.json()["resultados"]}


def test_la_instancia_vieja_sin_marca_sigue_recibiendo_el_tema(logueado):
    """El camino de siempre (las dos instancias del `cliente` de la suite no tienen la ruta): el chequeo nuevo no le cambia nada."""
    r = logueado.put("/api/apariencia", json={"tema": {"menuActivoFondo": "#FDF2F8"}})
    por_slug = {x["slug"]: x["estado"] for x in r.json()["resultados"]}
    assert por_slug["acme"] == "aplicada" and por_slug["beta"] == "aplicada"


def test_una_instancia_que_falla_al_preguntar_por_la_marca_no_tumba_el_recorrido(tmp_path, inventario):
    from fastapi import HTTPException

    app, instancias = _con_apariencia(tmp_path, inventario, None, {"propia": False})
    # La de `acme` contesta 500 a `GET /api/marca`.
    instancias["producto-acme"].router.routes[:] = [r for r in instancias["producto-acme"].router.routes if getattr(r, "path", "") != "/api/marca"]

    @instancias["producto-acme"].get("/api/marca")
    def rota():
        raise HTTPException(500, "se rompió")

    with TestClient(app, base_url="https://testserver") as c:
        login(c, {"username": USUARIO, "password": PASSWORD})
        r = c.put("/api/apariencia", json={"tema": {"menuActivoFondo": "#FDF2F8"}})
        assert r.status_code == 200
        por_slug = {x["slug"]: x["estado"] for x in r.json()["resultados"]}
        assert por_slug["acme"] == por_slug["beta"] == "aplicada"
