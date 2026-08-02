"""
Inventario y ciclo de vida, con los dos backends.

El backend `libracore` se ejercita con módulos falsos inyectados en
`sys.modules` —el mismo patrón con el que LibraCore testea su propio
backoffice—: la lógica real de Docker/NPM/planes tiene su suite allá, y lo que
importa acá es que el router traduzca a JSON y mapee los errores del motor a
códigos HTTP. El backend `compose` se ejercita contra archivos reales, porque
lo único que hace es leerlos.
"""
import sys
import types

import pytest
from fastapi.testclient import TestClient

from libra_backoffice.app import create_app
from libra_backoffice.inventario import InventarioCompose, construir_inventario

from .conftest import PASSWORD, USUARIO, construir_settings


class ServiceErrorFalso(Exception):
    pass


@pytest.fixture
def servicios_falsos(inventario):
    """`libracore.admin.services` visto por el router."""
    llamadas = []
    servicios = types.SimpleNamespace()
    servicios.ServiceError = ServiceErrorFalso

    def crear_cliente(**kwargs):
        if kwargs.get("slug") == "acme":
            raise ServiceErrorFalso("Ya existe una instancia con ese slug.")
        llamadas.append(("crear", kwargs))
        return {"slug": kwargs.get("slug") or "nueva", "nombre": kwargs["nombre"]}

    def editar_cliente(slug, nombre, domain):
        if slug not in ("acme", "beta"):
            raise ServiceErrorFalso(f"Instancia '{slug}' no encontrada.")
        return {"slug": slug, "nombre": nombre, "domain": domain}

    def set_plan(slug, plan):
        if plan not in ("basico", "pro"):
            raise ServiceErrorFalso(f"Plan inválido: {plan!r}.")
        llamadas.append(("plan", slug, plan))

    def accion_estado(slug, accion):
        if accion not in ("start", "stop", "restart"):
            raise ServiceErrorFalso(f"Acción inválida: {accion!r}.")
        llamadas.append(("estado", slug, accion))

    servicios.crear_cliente = crear_cliente
    servicios.editar_cliente = editar_cliente
    servicios.set_plan = set_plan
    servicios.accion_estado = accion_estado
    servicios.backup_cliente = lambda slug: f"/backups/{slug}.tar.gz"
    servicios.eliminar_cliente = lambda slug, hacer_backup=True: {
        "slug": slug, "backup": None, "npm": None
    }
    servicios.planes_info = lambda: [
        {"key": "basico", "label": "Básico", "precio": 0, "modulos": ["ventas"]},
        {"key": "pro", "label": "Pro", "precio": 100, "modulos": ["stock", "ventas"]},
    ]

    inventario.servicios = servicios
    servicios.llamadas = llamadas
    return servicios


@pytest.fixture
def admin(tmp_path, instancias_falsas, inventario, servicios_falsos):
    app = create_app(construir_settings(tmp_path), inventario=inventario)
    c = TestClient(app, base_url="https://testserver")
    c.post("/api/login", json={"username": USUARIO, "password": PASSWORD})
    return c


def test_pide_sesion(cliente):
    assert cliente.get("/api/instancias").status_code == 401


def test_listar_declara_lo_que_soporta(admin):
    cuerpo = admin.get("/api/instancias").json()
    assert [i["slug"] for i in cuerpo["instancias"]] == ["acme", "beta", "caida"]
    assert cuerpo["soporta_ciclo_de_vida"] is True
    assert cuerpo["soporta_planes"] is True


def test_detalle_y_404(admin):
    assert admin.get("/api/instancias/acme").json()["nombre"] == "ACME SA"
    assert admin.get("/api/instancias/fantasma").status_code == 404


def test_alta(admin):
    resp = admin.post("/api/instancias", json={"nombre": "Nueva SA", "slug": "nueva"})
    assert resp.status_code == 201
    assert resp.json()["slug"] == "nueva"


def test_alta_duplicada_es_422(admin):
    assert admin.post("/api/instancias", json={"nombre": "ACME", "slug": "acme"}).status_code == 422


def test_editar(admin):
    resp = admin.put("/api/instancias/acme", json={"nombre": "ACME SRL", "domain": "acme.test"})
    assert resp.json()["nombre"] == "ACME SRL"


def test_plan_invalido(admin):
    assert admin.put("/api/instancias/acme/plan", json={"plan": "enterprise"}).status_code == 422


def test_plan_valido(admin, servicios_falsos):
    assert admin.put("/api/instancias/acme/plan", json={"plan": "basico"}).status_code == 200
    assert ("plan", "acme", "basico") in servicios_falsos.llamadas


def test_accion_de_estado(admin, servicios_falsos):
    assert admin.post("/api/instancias/acme/estado", json={"accion": "restart"}).status_code == 200
    assert ("estado", "acme", "restart") in servicios_falsos.llamadas


def test_accion_invalida(admin):
    assert admin.post("/api/instancias/acme/estado", json={"accion": "formatear"}).status_code == 422


def test_backup(admin):
    assert admin.post("/api/instancias/acme/backup").json()["archivo"].endswith(".tar.gz")


def test_la_baja_exige_repetir_el_slug(admin):
    resp = admin.request("DELETE", "/api/instancias/acme",
                         json={"confirmar_slug": "acmee", "hacer_backup": False})
    assert resp.status_code == 422


def test_baja_con_confirmacion_correcta(admin):
    resp = admin.request("DELETE", "/api/instancias/acme",
                         json={"confirmar_slug": "acme", "hacer_backup": False})
    assert resp.json()["slug"] == "acme"


def test_planes(admin):
    assert [p["key"] for p in admin.get("/api/planes").json()] == ["basico", "pro"]


# ── Backend `compose` (LibraDesk) ───────────────────────────────────────────

def _clientes(tmp_path, slug, container, con_meta=False):
    d = tmp_path / "clientes" / slug
    d.mkdir(parents=True)
    (d / "docker-compose.yml").write_text(
        f"services:\n  app:\n    image: libradesk:v1\n    container_name: {container}\n",
        encoding="utf-8",
    )
    if con_meta:
        (d / "cliente.json").write_text(
            '{"nombre": "Compu Libra", "domain": "soporte.compulibra.com.ar"}', encoding="utf-8"
        )
    return d


def test_compose_enumera_por_directorio(tmp_path):
    _clientes(tmp_path, "compulibra", "libradesk-compulibra", con_meta=True)
    _clientes(tmp_path, "demo", "libradesk-demo")

    instancias = InventarioCompose(tmp_path).listar()

    assert [i.slug for i in instancias] == ["compulibra", "demo"]
    assert instancias[0].container == "libradesk-compulibra"
    assert instancias[0].nombre == "Compu Libra"
    # Sin cliente.json el nombre es el slug, no un invento.
    assert instancias[1].nombre == "demo"


def test_compose_no_afirma_un_estado_que_no_verifico(tmp_path):
    _clientes(tmp_path, "demo", "libradesk-demo")
    assert InventarioCompose(tmp_path).listar()[0].estado == "desconocido"


def test_compose_sin_directorio_clientes_no_explota(tmp_path):
    assert InventarioCompose(tmp_path).listar() == []


def test_compose_no_soporta_ciclo_de_vida(tmp_path, instancias_falsas):
    """LibraDesk despliega con su propio script: el backoffice lista, no opera.
    Un 501 lo dice; un 500 haría buscar un bug que no existe."""
    _clientes(tmp_path, "demo", "libradesk-demo")
    settings = construir_settings(tmp_path, instancias_backend="compose", db_filename="")
    app = create_app(settings, inventario=construir_inventario(settings))
    c = TestClient(app, base_url="https://testserver")
    c.post("/api/login", json={"username": USUARIO, "password": PASSWORD})

    assert c.get("/api/instancias").json()["soporta_ciclo_de_vida"] is False
    resp = c.post("/api/instancias/demo/estado", json={"accion": "restart"})
    assert resp.status_code == 501
    assert "deploy_cliente.sh" in resp.json()["detail"]


def test_construir_inventario_elige_por_settings(tmp_path):
    settings = construir_settings(tmp_path, instancias_backend="compose", db_filename="")
    assert isinstance(construir_inventario(settings), InventarioCompose)


def test_instancia_desconocida_en_compose(tmp_path):
    from libra_backoffice.inventario import InstanciaDesconocida

    with pytest.raises(InstanciaDesconocida):
        InventarioCompose(tmp_path).obtener("fantasma")


def test_compose_con_yaml_sin_container_name(tmp_path):
    """No se adivina: el default de Docker Compose no es predecible desde
    afuera, y la feature `salud` lo reporta como 'sin contenedor'."""
    d = tmp_path / "clientes" / "raro"
    d.mkdir(parents=True)
    (d / "docker-compose.yml").write_text("services:\n  app:\n    image: x\n", encoding="utf-8")
    assert InventarioCompose(tmp_path).obtener("raro").container == ""


def test_compose_con_cliente_json_roto_no_tumba_el_listado(tmp_path):
    d = _clientes(tmp_path, "roto", "libradesk-roto")
    (d / "cliente.json").write_text("{no es json", encoding="utf-8")
    assert InventarioCompose(tmp_path).obtener("roto").nombre == "roto"


# ── sys.modules: el backend libracore de verdad ─────────────────────────────

def test_inventario_libracore_usa_admin_services(tmp_path, monkeypatch):
    """Que `construir_inventario` cablea `libracore.admin.services` y lo
    configura con el repo del producto."""
    panel_admin = types.ModuleType("panel_admin")
    panel_admin.CLIENTES_DIR = tmp_path / "clientes"
    panel_admin._NPM_AVAILABLE = False
    panel_admin.load_clients = lambda: [
        {"slug": "acme", "nombre": "ACME", "container": "prod-acme",
         "domain": "acme.test", "port": 8081, "plan": "pro", "dir": tmp_path / "acme"}
    ]
    panel_admin.container_status = lambda c: {"status": "running", "started": "hace 1 día"}
    monkeypatch.setitem(sys.modules, "panel_admin", panel_admin)

    settings = construir_settings(tmp_path)
    instancias = construir_inventario(settings).listar()

    assert instancias[0].slug == "acme"
    assert instancias[0].container == "prod-acme"
    assert instancias[0].estado == "running"
