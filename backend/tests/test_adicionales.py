"""Los adicionales fuera de la escalera en el backoffice (ADR-048 de libracore): catálogo, contratar, abono por líneas y cambio de plan.

La instancia es una app FastAPI de verdad con el router REAL de `libracore.adicionales_router` y sus guardas (ver `conftest.py`); el catálogo y las
cuentas son las REALES de `libracore.adicionales` sobre un `plans.py` de juguete. Lo que se prueba es lo que decide el backoffice: a quién le
pregunta, qué muestra cuando la instancia no puede contestar, qué rechaza antes de molestarla y que el cambio de plan no pierde ni deja pasar un
adicional incompatible.
"""
import types

import pytest
from fastapi.testclient import TestClient
from libracore import adicionales as ad
from libracore import config_manager
from libracore.admin import services as servicios_reales

from .conftest import (
    PASSWORD, USUARIO, ClienteInstancia, _TransporteDeInstancias, construir_instancia_falsa, construir_settings, login,
)

from libra_backoffice.app import create_app


def _plans():
    """Un producto como RestoLibra + las sucursales de VentaLibra: offline por sucursal (solo en `pro`), un sí/no y unidades con precio."""
    m = types.ModuleType("plans")
    m.PLANES = ["basico", "pro"]
    m.PLAN_LABELS = {"basico": "Básico", "pro": "Pro"}
    m.PLAN_PRECIOS = {"basico": 27000, "pro": 69000}
    m.PLAN_MODULOS = {"basico": {"ventas"}, "pro": {"ventas", "stock"}}
    m.ADDONS = {"resguardo_externo"}
    m.ADICIONALES = {
        "offline": {"label": "Modo offline", "precio": None, "modulos": {"offline"}, "unidad": "sucursal", "limite": "sucursales_offline",
                    "planes": {"pro"}},
        "sucursal": {"label": "Sucursales", "precio": 19950, "unidad": "sucursal", "incluidas": {"basico": 1, "pro": 2}, "limite": "sucursales"},
    }
    return m


@pytest.fixture
def plans():
    return _plans()


class _ServiceError(Exception):
    pass


@pytest.fixture
def servicios(inventario, plans):
    """`libracore.admin.services` visto por el router, con la lógica de adicionales REAL (catálogo y abono) y el resto de mentira."""
    s = types.SimpleNamespace(ServiceError=_ServiceError, llamadas=[], copia={})
    s.AdicionalIncompatibleError = servicios_reales.AdicionalIncompatibleError
    s.planes_info = lambda: [{"key": p, "label": p, "precio": plans.PLAN_PRECIOS[p], "modulos": [], "adicional": None} for p in plans.PLANES]
    s.plan_vigente = lambda p: p
    s.adicionales_info = lambda: [a.como_dict() for _, a in sorted(ad.catalogo(plans).items())]

    def abono_por_lineas(plan, contratados):
        r = ad.resolver(plans, plan, contratados)
        return {"plan": plan, **ad.calcular_abono_total(plans.PLAN_PRECIOS[plan], r["lineas_abono"]), "incompatibles": r["incompatibles"]}

    s.abono_por_lineas = abono_por_lineas

    def set_plan(slug, plan, contratados=None):
        s.llamadas.append(("plan", slug, plan, contratados))
        fuera = ad.incompatibles(plans, plan, contratados or {})
        if fuera:
            raise servicios_reales.AdicionalIncompatibleError(plan, fuera)
        inventario.reemplazar(slug, plan=plan)

    def set_adicional(slug, clave, habilitado):
        s.llamadas.append(("set_adicional", slug, clave, habilitado))
        if clave == "offline":
            raise _ServiceError("«Modo offline» se cuenta por sucursal: la instancia tiene que exponer /api/adicionales.")
        s.docker[(slug, clave)] = habilitado

    s.docker = {}
    s.adicionales_de_instancia = lambda slug: {"resguardo_externo": s.docker.get((slug, "resguardo_externo"), False), "offline": False}
    s.registrar_copia_de_adicionales = lambda slug, cambios: s.copia.setdefault(slug, {}).update(cambios)
    s.sincronizar_copia_de_adicionales = lambda slug, contratados: s.copia.__setitem__(slug, {k: v for k, v in contratados.items() if v})
    s.set_plan = set_plan
    s.set_adicional = set_adicional

    def crear_cliente(**kwargs):
        s.llamadas.append(("alta", kwargs))
        return {"slug": kwargs.get("slug") or "nueva", "nombre": kwargs["nombre"], "container": "producto-nueva", "plan": kwargs.get("plan", "")}

    s.crear_cliente = crear_cliente
    inventario.servicios = s
    return s


@pytest.fixture
def datos_de_la_instancia(tmp_path, monkeypatch):
    monkeypatch.setattr(config_manager, "CONFIG_PATH", str(tmp_path / "config-instancia.json"))
    return config_manager


def _backoffice(tmp_path, inventario, apps):
    app = create_app(construir_settings(tmp_path), inventario=inventario)
    app.state.cliente_instancia = ClienteInstancia(
        token=app.state.settings.service_token, transport=_TransporteDeInstancias(apps))
    c = TestClient(app, base_url="https://testserver")
    assert login(c, {"username": USUARIO, "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def en_uso():
    return {"sucursal": 1, "offline": 0}


@pytest.fixture
def instancia(tmp_path, plans, en_uso):
    return construir_instancia_falsa(tmp_path / "acme.db", adicionales_plans=plans, en_uso={k: (lambda k=k: en_uso[k]) for k in en_uso})


@pytest.fixture
def admin(tmp_path, inventario, servicios, datos_de_la_instancia, instancia):
    """`acme` (plan `pro`) expone los adicionales; `beta` (plan `basico`) es una instancia vieja sin la ruta; `caida` no corre."""
    apps = {"producto-acme": instancia, "producto-beta": construir_instancia_falsa(tmp_path / "beta.db")}
    return _backoffice(tmp_path, inventario, apps)


def _por_clave(cuerpo):
    return {i["clave"]: i for i in cuerpo["adicionales"]}


def test_exigen_sesion(cliente):
    assert cliente.get("/api/instancias/acme/adicionales").status_code == 401
    assert cliente.put("/api/instancias/acme/adicionales/offline", json={"cantidad": 1}).status_code == 401
    assert cliente.delete("/api/instancias/acme/adicionales/offline").status_code == 401


# ── GET ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_sin_nada_contratado_el_abono_es_la_base(admin):
    r = admin.get("/api/instancias/acme/adicionales")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert (cuerpo["estado"], cuerpo["plan"]) == ("ok", "pro")
    items = _por_clave(cuerpo)
    assert sorted(items) == ["offline", "resguardo_externo", "sucursal"]
    assert (items["sucursal"]["incluidas"], items["sucursal"]["precio"], items["sucursal"]["usadas"]) == (2, 19950, 1)  # las incluidas son las del PLAN
    assert items["offline"]["habilitado"] is False and items["offline"]["cantidad"] is None and items["offline"]["editable"] is True
    assert cuerpo["abono"]["total"] == 69000 and cuerpo["abono"]["lineas"] == [] and cuerpo["abono"]["a_cotizar"] == []


def test_contratar_el_offline_por_dos_sucursales_sale_a_cotizar(admin):
    r = admin.put("/api/instancias/acme/adicionales/offline", json={"cantidad": 2})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    offline = _por_clave(cuerpo)["offline"]
    assert (offline["habilitado"], offline["cantidad"]) == (True, 2)
    (linea,) = cuerpo["abono"]["lineas"]
    assert (linea["clave"], linea["cantidad"], linea["precio"], linea["subtotal"], linea["a_cotizar"]) == ("offline", 2, None, None, True)
    assert cuerpo["abono"]["total"] == 69000 and cuerpo["abono"]["a_cotizar"] == ["offline"]  # lo que se sabe; el resto, a cotizar


def test_el_abono_arma_una_linea_por_adicional_con_su_precio(admin):
    admin.put("/api/instancias/acme/adicionales/sucursal", json={"cantidad": 4})
    cuerpo = admin.put("/api/instancias/acme/adicionales/resguardo_externo", json={"habilitado": True}).json()
    assert [ln["clave"] for ln in cuerpo["abono"]["lineas"]] == ["resguardo_externo", "sucursal"]
    assert cuerpo["abono"]["extra"] == 2 * 19950 and cuerpo["abono"]["total"] == 69000 + 2 * 19950  # 4 contratadas, 2 incluidas en `pro`
    assert cuerpo["abono"]["a_cotizar"] == ["resguardo_externo"]


def test_el_dato_queda_en_la_instancia_y_la_copia_en_el_host(admin, servicios, datos_de_la_instancia):
    admin.put("/api/instancias/acme/adicionales/offline", json={"cantidad": 3})
    assert ad.cantidad_contratada("offline") == 3  # el config.json de la instancia
    assert servicios.copia["acme"]["offline"] == 3  # la copia informativa de `cliente.json`


def test_la_baja_con_delete_o_con_null(admin):
    admin.put("/api/instancias/acme/adicionales/offline", json={"cantidad": 3})
    assert _por_clave(admin.delete("/api/instancias/acme/adicionales/offline").json())["offline"]["habilitado"] is False
    admin.put("/api/instancias/acme/adicionales/offline", json={"cantidad": 3})
    assert _por_clave(admin.put("/api/instancias/acme/adicionales/offline", json={"cantidad": None}).json())["offline"]["cantidad"] is None


def test_la_copia_que_difiere_se_alinea_y_gana_la_instancia(admin, servicios):
    servicios.copia["acme"] = {"offline": 9, "resguardo_externo": True}
    admin.get("/api/instancias/acme/adicionales")
    assert servicios.copia["acme"] == {}  # la instancia no tiene nada contratado


def test_un_producto_sin_adicionales_no_aplica(admin, servicios):
    servicios.adicionales_info = lambda: []
    cuerpo = admin.get("/api/instancias/acme/adicionales").json()
    assert (cuerpo["estado"], cuerpo["adicionales"], cuerpo["abono"]) == ("no_aplica", [], None)


def test_instancia_detenida_o_inalcanzable_no_se_inventa_el_estado(admin):
    cuerpo = admin.get("/api/instancias/caida/adicionales").json()
    assert cuerpo["estado"] == "detenida" and cuerpo["abono"] is None
    assert all(i["habilitado"] is None and i["cantidad"] is None and i["editable"] is False for i in cuerpo["adicionales"])


def test_instancia_desconocida_es_404(admin):
    assert admin.get("/api/instancias/fantasma/adicionales").status_code == 404


# ── instancia vieja, sin la ruta ─────────────────────────────────────────────────────────────────────────────────────

def test_una_instancia_vieja_dice_sin_soporte_y_deja_prender_los_si_no_por_docker(admin, servicios):
    cuerpo = admin.get("/api/instancias/beta/adicionales").json()
    assert cuerpo["estado"] == "sin_soporte" and "libracore anterior a v1.162.0" in cuerpo["detalle"]
    items = _por_clave(cuerpo)
    assert items["resguardo_externo"]["habilitado"] is False and items["resguardo_externo"]["editable"] is True
    assert items["sucursal"]["editable"] is False, "una cantidad no se puede cargar por docker exec"
    assert cuerpo["abono"] is None

    r = admin.put("/api/instancias/beta/adicionales/resguardo_externo", json={"habilitado": True})
    assert r.status_code == 200, r.text
    assert ("set_adicional", "beta", "resguardo_externo", True) in servicios.llamadas


def test_una_cantidad_en_una_instancia_vieja_es_409(admin):
    r = admin.put("/api/instancias/beta/adicionales/sucursal", json={"cantidad": 2})
    assert r.status_code == 409 and "hay que actualizarla" in r.json()["detail"]


# ── lo que se rechaza antes de molestar a la instancia ───────────────────────────────────────────────────────────────

def test_un_adicional_que_el_plan_no_admite_es_422(admin, inventario):
    inventario.reemplazar("acme", plan="basico")  # `offline` es sólo de `pro`
    r = admin.put("/api/instancias/acme/adicionales/offline", json={"cantidad": 1})
    assert r.status_code == 422 and "no se puede contratar con el plan 'basico'" in r.json()["detail"]
    assert ad.cantidad_contratada("offline") is None


def test_un_adicional_que_no_existe_es_404(admin):
    assert admin.put("/api/instancias/acme/adicionales/cohetes", json={"habilitado": True}).status_code == 404


@pytest.mark.parametrize("ruta, cuerpo", [
    ("offline", {}), ("offline", {"habilitado": True, "cantidad": 2}), ("offline", {"habilitado": True}),
    ("resguardo_externo", {"cantidad": 2}), ("offline", {"cantidad": 0}), ("offline", {"cantidad": True}), ("offline", {"cantidad": 1001}),
])
def test_un_cuerpo_que_no_corresponde_es_422(admin, ruta, cuerpo):
    assert admin.put(f"/api/instancias/acme/adicionales/{ruta}", json=cuerpo).status_code == 422
    assert ad.cantidad_contratada("offline") is None


def test_la_instancia_que_rechaza_viaja_con_su_estado(admin, tmp_path, inventario, servicios, datos_de_la_instancia):
    """Un token que la instancia no acepta es un error de verdad (nunca un 200 que dice que se guardó)."""
    app = admin.app
    app.state.cliente_instancia = ClienteInstancia(token="otro", transport=app.state.cliente_instancia._transport)
    r = admin.put("/api/instancias/acme/adicionales/offline", json={"cantidad": 1})
    assert r.status_code in (401, 403)
    assert ad.cantidad_contratada("offline") is None


def test_instancia_inalcanzable_es_502_al_cargar(admin, inventario):
    inventario.reemplazar("caida", plan="pro")
    assert admin.put("/api/instancias/caida/adicionales/offline", json={"cantidad": 1}).status_code == 502


# ── el cambio de plan ────────────────────────────────────────────────────────────────────────────────────────────────

def test_cambiar_de_plan_conserva_los_adicionales(admin, servicios):
    admin.put("/api/instancias/acme/adicionales/sucursal", json={"cantidad": 3})
    admin.put("/api/instancias/acme/adicionales/resguardo_externo", json={"habilitado": True})
    r = admin.put("/api/instancias/acme/plan", json={"plan": "basico"})
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == "basico"
    assert servicios.llamadas[-1] == ("plan", "acme", "basico", {"sucursal": 3, "resguardo_externo": True})
    cuerpo = admin.get("/api/instancias/acme/adicionales").json()
    items = _por_clave(cuerpo)
    assert (items["sucursal"]["cantidad"], items["resguardo_externo"]["habilitado"]) == (3, True)  # nada se apagó solo
    assert items["sucursal"]["incluidas"] == 1  # y las incluidas son ahora las del plan nuevo


def test_pasar_a_un_plan_que_no_admite_un_adicional_contratado_es_409_con_la_lista(admin, servicios, inventario):
    admin.put("/api/instancias/acme/adicionales/offline", json={"cantidad": 2})
    r = admin.put("/api/instancias/acme/plan", json={"plan": "basico"})
    assert r.status_code == 409, r.text
    assert r.json()["incompatibles"] == ["offline"] and "offline" in r.json()["detail"]
    assert inventario.obtener("acme").plan == "pro", "no se aplicó nada"


def test_dado_de_baja_el_incompatible_el_cambio_pasa(admin):
    admin.put("/api/instancias/acme/adicionales/offline", json={"cantidad": 2})
    admin.delete("/api/instancias/acme/adicionales/offline")
    assert admin.put("/api/instancias/acme/plan", json={"plan": "basico"}).status_code == 200


def test_si_la_instancia_no_contesta_el_cambio_de_plan_usa_la_copia_del_motor(admin, servicios, inventario):
    inventario.reemplazar("caida", plan="pro")
    assert admin.put("/api/instancias/caida/plan", json={"plan": "basico"}).status_code == 200
    assert servicios.llamadas[-1] == ("plan", "caida", "basico", None)


# ── el alta ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_el_alta_pasa_los_adicionales_al_motor(admin, servicios):
    r = admin.post("/api/instancias", json={"nombre": "Nueva SA", "slug": "nueva", "plan": "pro", "adicionales": {"offline": 2, "resguardo_externo": True}})
    assert r.status_code == 201, r.text
    assert servicios.llamadas[-1][1]["adicionales"] == {"offline": 2, "resguardo_externo": True}


def test_el_alta_sin_adicionales_no_los_manda(admin, servicios):
    admin.post("/api/instancias", json={"nombre": "Nueva SA", "slug": "nueva", "plan": "pro"})
    assert "adicionales" not in servicios.llamadas[-1][1]


@pytest.mark.parametrize("plan, adicionales, texto", [
    ("pro", {"cohetes": True}, "desconocido"),
    ("pro", {"offline": True}, "se cuenta por sucursal"),
    ("pro", {"offline": 0}, "entero desde 1"),
    ("pro", {"resguardo_externo": 2}, "sí/no"),
    ("basico", {"offline": 1}, "no se puede contratar con el plan 'basico'"),
])
def test_el_alta_rechaza_adicionales_invalidos_con_el_motivo(admin, servicios, plan, adicionales, texto):
    r = admin.post("/api/instancias", json={"nombre": "Mala SA", "slug": "mala", "plan": plan, "adicionales": adicionales})
    assert r.status_code == 422, r.text
    assert texto in r.text
    assert not [ll for ll in servicios.llamadas if ll[0] == "alta"]


def test_el_fallback_html_de_la_spa_tambien_es_sin_soporte(tmp_path, inventario, servicios, datos_de_la_instancia):
    """En producción una ruta que no existe contesta 200 con el HTML de la SPA: es la misma «instancia vieja», no un error."""
    apps = {"producto-acme": construir_instancia_falsa(tmp_path / "acme.db", con_tema=False)}
    c = _backoffice(tmp_path, inventario, apps)
    cuerpo = c.get("/api/instancias/acme/adicionales").json()
    assert cuerpo["estado"] == "sin_soporte"
