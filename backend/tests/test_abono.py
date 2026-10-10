"""El abono de una instancia: precio del plan + sucursales adicionales CONTRATADAS (ADR-041 de libracore).

La instancia con límites es una app FastAPI de verdad con el router REAL de `libracore.limites` y sus guardas (ver `conftest.py`): el backoffice
no habla con un doble que esté de acuerdo con cualquier contrato. Se prueba lo que decide el backoffice: a quién le pregunta, cómo calcula, qué
muestra cuando la instancia no puede contestar, y que cargar el número es un error de verdad cuando no se pudo cargar.
"""
import types

import pytest
from fastapi.testclient import TestClient
from libracore import config_manager

from libra_backoffice.app import create_app

from .conftest import (
    PASSWORD, USUARIO, ClienteInstancia, _TransporteDeInstancias, construir_instancia_falsa, construir_settings, login,
)

UNICO = {
    "key": "unico", "label": "Plan único", "precio": 39900, "modulos": [],
    "adicional": {"unidad": "sucursal", "incluidas": 1, "precio": 19950},
}
BASICO = {"key": "basico", "label": "Básico", "precio": 1000, "modulos": [], "adicional": None}


class ServiceErrorFalso(Exception):
    pass


@pytest.fixture
def servicios(inventario):
    """`libracore.admin.services` visto por el router: los planes y el alta, nada más."""
    llamadas = []
    s = types.SimpleNamespace(llamadas=llamadas, ServiceError=ServiceErrorFalso)
    s.planes_info = lambda: [UNICO, BASICO]
    # Una instancia vieja guarda `premium` en su cliente.json; hoy el plan vigente es `unico`.
    s.plan_vigente = lambda plan: {"premium": "unico"}.get(plan, plan)

    def crear_cliente(**kwargs):
        llamadas.append(kwargs)
        return {"slug": kwargs.get("slug") or "nueva", "nombre": kwargs["nombre"], "container": "producto-nueva", "plan": kwargs.get("plan", "")}

    s.crear_cliente = crear_cliente
    inventario.servicios = s
    return s


@pytest.fixture
def activas():
    return {"n": 1}


@pytest.fixture
def datos_de_la_instancia(tmp_path, monkeypatch):
    """El `config.json` de la instancia con límites (es de ese proceso, que acá es el de la suite)."""
    monkeypatch.setattr(config_manager, "CONFIG_PATH", str(tmp_path / "config-instancia.json"))
    return config_manager


def _backoffice(tmp_path, inventario, apps, *, token=None):
    app = create_app(construir_settings(tmp_path), inventario=inventario)
    kwargs = {"transport": _TransporteDeInstancias(apps)}
    app.state.cliente_instancia = ClienteInstancia(token=token or app.state.settings.service_token, **kwargs)
    c = TestClient(app, base_url="https://testserver")
    assert login(c, {"username": USUARIO, "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def admin(tmp_path, inventario, servicios, activas, datos_de_la_instancia):
    """`acme` es de un producto con sucursales adicionales y expone los límites; `beta` es de otro que no."""
    inventario.reemplazar("acme", plan="unico")
    apps = {
        "producto-acme": construir_instancia_falsa(tmp_path / "acme.db", sucursales_activas=lambda: activas["n"]),
        "producto-beta": construir_instancia_falsa(tmp_path / "beta.db"),
    }
    return _backoffice(tmp_path, inventario, apps)


# ── Auth ─────────────────────────────────────────────────────────────────────

def test_exigen_sesion(cliente):
    assert cliente.get("/api/instancias/acme/abono").status_code == 401
    assert cliente.put("/api/instancias/acme/sucursales", json={"contratadas": 2}).status_code == 401


# ── GET /abono ───────────────────────────────────────────────────────────────

def test_sin_dato_cargado_dice_sin_cargar_y_el_total_es_la_base(admin):
    r = admin.get("/api/instancias/acme/abono")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["estado"] == "ok" and cuerpo["aplica"] is True
    assert cuerpo["contratadas"] is None  # «Sin cargar»
    assert cuerpo["activas"] == 1
    assert cuerpo["plan"] == "unico" and cuerpo["plan_label"] == "Plan único"
    assert (cuerpo["precio_base"], cuerpo["precio_adicional"], cuerpo["incluidas"], cuerpo["unidad"]) == (39900, 19950, 1, "sucursal")
    assert cuerpo["abono"]["total"] == 39900 and cuerpo["abono"]["adicionales"] == 0


@pytest.mark.parametrize("contratadas, adicionales, total", [(1, 0, 39900), (2, 1, 59850), (3, 2, 79800)])
def test_el_abono_sale_de_lo_contratado(admin, contratadas, adicionales, total):
    assert admin.put("/api/instancias/acme/sucursales", json={"contratadas": contratadas}).status_code == 200
    cuerpo = admin.get("/api/instancias/acme/abono").json()
    assert cuerpo["contratadas"] == contratadas
    assert (cuerpo["abono"]["adicionales"], cuerpo["abono"]["extra"], cuerpo["abono"]["total"]) == (adicionales, adicionales * 19950, total)


def test_las_activas_vienen_de_la_instancia(admin, activas):
    activas["n"] = 3
    admin.put("/api/instancias/acme/sucursales", json={"contratadas": 2})
    cuerpo = admin.get("/api/instancias/acme/abono").json()
    assert (cuerpo["activas"], cuerpo["contratadas"]) == (3, 2)  # pasadas de lo contratado: la pantalla lo marca


def test_un_plan_sin_adicional_no_aplica_y_ni_le_habla_a_la_instancia(admin):
    r = admin.get("/api/instancias/beta/abono")  # `beta` es del plan `basico`
    assert r.status_code == 200
    assert r.json() == {"slug": "beta", "plan": "basico", "aplica": False, "estado": "no_aplica", "detalle": ""}


def test_un_plan_retirado_se_busca_por_el_plan_vigente(admin, inventario):
    """El `cliente.json` de una instancia vieja dice `premium`; el plan que rige hoy es `unico`."""
    inventario.reemplazar("acme", plan="premium")
    cuerpo = admin.get("/api/instancias/acme/abono").json()
    assert cuerpo["aplica"] is True and cuerpo["plan"] == "unico"


def test_instancia_desconocida_es_404(admin):
    assert admin.get("/api/instancias/no-existe/abono").status_code == 404
    assert admin.put("/api/instancias/no-existe/sucursales", json={"contratadas": 2}).status_code == 404


def test_instancia_detenida_no_se_consulta(admin, inventario):
    inventario.reemplazar("caida", plan="unico")
    cuerpo = admin.get("/api/instancias/caida/abono").json()
    assert cuerpo["estado"] == "detenida" and cuerpo["abono"] is None and cuerpo["contratadas"] is None
    assert cuerpo["precio_base"] == 39900  # el precio del plan se sabe igual


def test_instancia_que_no_contesta_es_inalcanzable_y_no_rompe(admin, inventario):
    inventario.reemplazar("acme", container="producto-fantasma")
    r = admin.get("/api/instancias/acme/abono")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["estado"] == "inalcanzable" and cuerpo["abono"] is None


def test_instancia_sin_el_endpoint_dice_que_hay_que_actualizarla(admin, inventario, tmp_path):
    """`beta` con un plan que cobra sucursales pero una libracore vieja: el fallback de la SPA contesta 200 con HTML. No es un error del backoffice."""
    inventario.reemplazar("beta", plan="unico")
    r = admin.get("/api/instancias/beta/abono")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["estado"] == "sin_soporte" and "actualizar" in cuerpo["detalle"]
    assert cuerpo["abono"] is None and cuerpo["contratadas"] is None


def test_instancia_que_contesta_con_un_error_lo_muestra_con_su_motivo(tmp_path, inventario, servicios):
    from fastapi import FastAPI, HTTPException

    inventario.reemplazar("acme", plan="unico")
    rota = FastAPI()

    @rota.get("/api/limites/sucursales")
    def _():
        raise HTTPException(503, "Servicio suspendido")

    cuerpo = _backoffice(tmp_path, inventario, {"producto-acme": rota}).get("/api/instancias/acme/abono").json()
    assert cuerpo["estado"] == "error" and cuerpo["detalle"] == "Servicio suspendido" and cuerpo["abono"] is None


# ── PUT /sucursales ──────────────────────────────────────────────────────────

def test_cargar_guarda_en_la_instancia_y_devuelve_el_abono(admin, datos_de_la_instancia):
    r = admin.put("/api/instancias/acme/sucursales", json={"contratadas": 3})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert (cuerpo["contratadas"], cuerpo["activas"], cuerpo["estado"]) == (3, 1, "ok")
    assert cuerpo["abono"]["total"] == 79800
    # El dato quedó en la INSTANCIA (su config.json), que es quien bloquea el alta.
    from libracore.limites import sucursales_contratadas
    assert sucursales_contratadas() == 3


def test_null_quita_el_dato(admin):
    admin.put("/api/instancias/acme/sucursales", json={"contratadas": 3})
    cuerpo = admin.put("/api/instancias/acme/sucursales", json={"contratadas": None}).json()
    assert cuerpo["contratadas"] is None and cuerpo["abono"]["total"] == 39900


@pytest.mark.parametrize("malo", [0, -1, 1001, True, "muchas", 1.5])
def test_no_deja_cargar_lo_que_no_es_un_entero_valido(admin, malo):
    assert admin.put("/api/instancias/acme/sucursales", json={"contratadas": malo}).status_code == 422
    assert admin.get("/api/instancias/acme/abono").json()["contratadas"] is None


def test_sin_el_campo_es_422_y_no_borra_el_dato(admin):
    admin.put("/api/instancias/acme/sucursales", json={"contratadas": 2})
    assert admin.put("/api/instancias/acme/sucursales", json={}).status_code == 422
    assert admin.get("/api/instancias/acme/abono").json()["contratadas"] == 2


def test_un_plan_sin_adicional_no_deja_cargar(admin):
    r = admin.put("/api/instancias/beta/sucursales", json={"contratadas": 2})
    assert r.status_code == 422
    assert "no cobra sucursales adicionales" in r.json()["detail"]


def test_si_la_instancia_no_contesta_cargar_es_502_no_un_ok(admin, inventario):
    inventario.reemplazar("acme", container="producto-fantasma")
    assert admin.put("/api/instancias/acme/sucursales", json={"contratadas": 2}).status_code == 502


def test_si_la_instancia_no_tiene_el_endpoint_cargar_es_409_y_dice_que_la_actualicen(admin, inventario):
    inventario.reemplazar("beta", plan="unico")
    r = admin.put("/api/instancias/beta/sucursales", json={"contratadas": 2})
    assert r.status_code == 409
    assert "actualizar" in r.json()["detail"]


def test_el_codigo_de_error_de_la_instancia_llega_tal_cual(tmp_path, inventario, servicios):
    """Si la instancia rechaza el pedido (acá un 422 propio), el motivo llega al formulario con su código; no se convierte en un error genérico."""
    from fastapi import FastAPI, HTTPException

    inventario.reemplazar("acme", plan="unico")
    estricta = FastAPI()

    @estricta.put("/api/limites/sucursales")
    def _():
        raise HTTPException(422, "La cantidad de sucursales contratadas tiene que ser un entero entre 1 y 1000.")

    r = _backoffice(tmp_path, inventario, {"producto-acme": estricta}).put("/api/instancias/acme/sucursales", json={"contratadas": 2})
    assert r.status_code == 422 and "entero entre 1 y 1000" in r.json()["detail"]


# ── El alta ──────────────────────────────────────────────────────────────────

def _alta(admin, **extra):
    return admin.post("/api/instancias", json={"nombre": "Nueva SA", "slug": "nueva", "empresa_cuit": "30-71234567-8", **extra})


def test_el_alta_pasa_las_sucursales_contratadas_al_motor(admin, servicios):
    r = _alta(admin, plan="unico", sucursales_contratadas=2)
    assert r.status_code == 201, r.text
    assert servicios.llamadas[-1]["sucursales_contratadas"] == 2


def test_el_alta_sin_el_dato_no_carga_nada(admin, servicios):
    assert _alta(admin, plan="unico").status_code == 201
    assert servicios.llamadas[-1]["sucursales_contratadas"] is None


def test_el_alta_de_un_plan_sin_adicional_rechaza_el_dato_y_no_crea_nada(admin, servicios):
    r = _alta(admin, plan="basico", sucursales_contratadas=2)
    assert r.status_code == 422
    assert "no cobra sucursales adicionales" in r.json()["detail"]
    assert servicios.llamadas == []


@pytest.mark.parametrize("malo", [0, -1, 1001, True, "x"])
def test_el_alta_rechaza_un_dato_invalido(admin, servicios, malo):
    assert _alta(admin, plan="unico", sucursales_contratadas=malo).status_code == 422
    assert servicios.llamadas == []


def test_el_alta_con_un_plan_retirado_se_resuelve_al_vigente(admin, servicios):
    """El formulario viejo manda `premium`: el plan vigente (`unico`) sí cobra sucursales."""
    assert _alta(admin, plan="premium", sucursales_contratadas=1).status_code == 201


# ── Los planes ───────────────────────────────────────────────────────────────

def test_los_planes_traen_el_adicional_para_el_formulario(admin):
    planes = {p["key"]: p for p in admin.get("/api/planes").json()}
    assert planes["unico"]["adicional"] == {"unidad": "sucursal", "incluidas": 1, "precio": 19950}
    assert planes["basico"]["adicional"] is None
