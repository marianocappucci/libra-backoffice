"""
Inventario y ciclo de vida.

Se ejercita con módulos falsos inyectados en `sys.modules` —el mismo patrón con
el que LibraCore testea su propio backoffice—: la lógica real de
Docker/NPM/planes tiene su suite allá, y lo que importa acá es que el router
traduzca a JSON y mapee los errores del motor a códigos HTTP.

No hay ninguna rama por producto que testear: los seis tienen el mismo
provisioning y se administran igual.
"""
import sys
import types

import pytest
from fastapi.testclient import TestClient

from libra_backoffice.app import create_app
from libra_backoffice.inventario import construir_inventario

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
        # El motor genera la contraseña cuando el alta viene sin una, y la
        # devuelve acá: es la única vez que sale del host.
        return {
            "slug": kwargs.get("slug") or "nueva", "nombre": kwargs["nombre"],
            "domain": kwargs.get("domain", ""), "port": 8090,
            "container": "producto-nueva", "admin_user": kwargs.get("admin_user") or "admin",
            "admin_password": kwargs.get("admin_password") or "generada-por-el-motor",
            "plan": kwargs.get("plan", "basico"), "proxy_ok": None,
            "dir": "/root/producto/clientes/nueva",
        }

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
    def eliminar_cliente(slug, hacer_backup=True):
        llamadas.append(("baja", slug, hacer_backup))
        return {"slug": slug, "backup": None, "npm": None}

    servicios.backup_cliente = lambda slug: f"/backups/{slug}.tar.gz"
    servicios.eliminar_cliente = eliminar_cliente
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


def test_listar(admin):
    cuerpo = admin.get("/api/instancias").json()
    assert [i["slug"] for i in cuerpo["instancias"]] == ["acme", "beta", "caida"]


def test_detalle_y_404(admin):
    assert admin.get("/api/instancias/acme").json()["nombre"] == "ACME SA"
    assert admin.get("/api/instancias/fantasma").status_code == 404


def test_alta(admin):
    resp = admin.post("/api/instancias", json={"nombre": "Nueva SA", "slug": "nueva"})
    assert resp.status_code == 201
    assert resp.json()["slug"] == "nueva"


def test_el_alta_devuelve_la_password_generada(admin):
    """Si el alta no trae contraseña, el motor genera una y **esta respuesta es
    la única vez que la UI la ve**. Sin este campo, dar de alta un cliente por
    el backoffice dejaría un admin al que nadie puede entrar sin ir al host."""
    cuerpo = admin.post("/api/instancias", json={"nombre": "Nueva SA"}).json()
    assert cuerpo["admin_password"] == "generada-por-el-motor"
    assert cuerpo["admin_user"] == "admin"


def test_la_respuesta_del_alta_no_expone_la_ruta_del_host(admin):
    """`crear_cliente` devuelve también el directorio en el VPS. El navegador
    no tiene nada que hacer con eso; el `response_model` lo deja afuera."""
    assert "dir" not in admin.post("/api/instancias", json={"nombre": "Nueva SA"}).json()


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
    resp = admin.post("/api/instancias/acme/baja",
                      json={"confirmar_slug": "acmee", "hacer_backup": False})
    assert resp.status_code == 422


def test_baja_con_confirmacion_correcta(admin, servicios_falsos):
    resp = admin.post("/api/instancias/acme/baja",
                      json={"confirmar_slug": "acme", "hacer_backup": False})
    assert resp.json()["slug"] == "acme"
    assert ("baja", "acme", False) in servicios_falsos.llamadas


def test_la_baja_respalda_por_defecto(admin, servicios_falsos):
    """Sin `hacer_backup` explícito se respalda. El default vive en el modelo:
    si alguien lo invierte, borrar un cliente deja de dejar copia."""
    admin.post("/api/instancias/acme/baja", json={"confirmar_slug": "acme"})
    assert ("baja", "acme", True) in servicios_falsos.llamadas


def test_planes(admin):
    assert [p["key"] for p in admin.get("/api/planes").json()] == ["basico", "pro"]


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
