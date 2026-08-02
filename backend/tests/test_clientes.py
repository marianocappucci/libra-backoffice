"""
Gestión de instancias — la feature de Contalibra y Restolibra.

`libracore.admin.services` resuelve `panel_admin` / `nuevo_cliente` / `plans`
con imports diferidos contra el `sys.path` del repo del producto, así que acá
se inyectan tres módulos falsos en `sys.modules`. Es el mismo patrón con el que
LibraCore testea su propio backoffice, y sirve para lo que importa probar en
este repo: que el router traduce a JSON, valida y mapea los errores del motor a
códigos HTTP. La lógica real de Docker/NPM/planes tiene su suite en LibraCore.
"""
import sys
import types

import pytest
from fastapi.testclient import TestClient

from libra_backoffice.app import create_app
from libra_backoffice.settings import Settings

from .conftest import PASSWORD, USUARIO


class ClienteErrorFalso(Exception):
    pass


def _clientes_iniciales(tmp_path):
    return [
        {
            "slug": "acme", "nombre": "ACME SA", "domain": "acme.contalibra.com.ar",
            "port": 8081, "container": "contalibra-acme", "admin_user": "admin",
            "plan": "pro", "dir": tmp_path / "clientes" / "acme",
        },
    ]


@pytest.fixture
def motor_falso(tmp_path, monkeypatch):
    """Los tres módulos del producto que `libracore.admin.services` importa."""
    estado = {"clientes": _clientes_iniciales(tmp_path), "acciones": []}
    for c in estado["clientes"]:
        (c["dir"] / "data").mkdir(parents=True)
        (c["dir"] / "cliente.json").write_text(
            '{"nombre": "ACME SA", "domain": "acme.contalibra.com.ar", "port": 8081}',
            encoding="utf-8",
        )
        (c["dir"] / "data" / "contalibra.db").touch()

    panel_admin = types.ModuleType("panel_admin")
    panel_admin.CLIENTES_DIR = tmp_path / "clientes"
    panel_admin._NPM_AVAILABLE = False
    panel_admin.load_clients = lambda: list(estado["clientes"])
    panel_admin.find_client = lambda slug: next(
        (c for c in estado["clientes"] if c["slug"] == slug), None
    )
    panel_admin.container_status = lambda nombre: {"status": "running", "started": "hace 2 días"}
    panel_admin.compose = lambda slug, *args: estado["acciones"].append((slug, args))
    panel_admin._set_servicio_estado = lambda slug, valor: True

    nuevo_cliente = types.ModuleType("nuevo_cliente")
    nuevo_cliente.ClienteError = ClienteErrorFalso

    def crear(nombre, slug="", **kwargs):
        if slug == "acme":
            raise ClienteErrorFalso("Ya existe un cliente con ese slug.")
        return {"slug": slug or "nuevo", "nombre": nombre}

    nuevo_cliente.crear_cliente = crear

    plans = types.ModuleType("plans")
    plans.PLANES = ("basico", "pro")
    plans.PLAN_LABELS = {"basico": "Básico", "pro": "Pro"}
    plans.PLAN_PRECIOS = {"basico": 0, "pro": 100}
    plans.modulos_de_plan = lambda p: {"ventas"} if p == "basico" else {"ventas", "stock"}
    plans.aplicar_plan_en_db = lambda db, plan: None

    for nombre, modulo in (("panel_admin", panel_admin), ("nuevo_cliente", nuevo_cliente), ("plans", plans)):
        monkeypatch.setitem(sys.modules, nombre, modulo)

    return estado


@pytest.fixture
def admin(db_instancia, tmp_path, motor_falso):
    settings = Settings(
        product_slug="contalibra", product_name="Contalibra",
        features=frozenset({"smtp", "usuarios", "salud", "clientes"}),
        auth_db_path=db_instancia, repo_root=tmp_path, db_filename="contalibra.db",
    )
    app = create_app(settings)
    with TestClient(app, base_url="https://testserver") as c:
        c.post("/api/login", json={"username": USUARIO, "password": PASSWORD})
        yield c


def test_clientes_pide_sesion(db_instancia, tmp_path, motor_falso):
    settings = Settings(
        product_slug="contalibra", product_name="Contalibra",
        features=frozenset({"clientes"}), repo_root=tmp_path, db_filename="contalibra.db",
    )
    with TestClient(create_app(settings), base_url="https://testserver") as c:
        assert c.get("/api/clientes").status_code == 401


def test_listar_enriquece_con_estado_del_contenedor(admin):
    clientes = admin.get("/api/clientes").json()
    assert len(clientes) == 1
    assert clientes[0]["slug"] == "acme"
    assert clientes[0]["estado"] == "running"


def test_detalle_y_404(admin):
    assert admin.get("/api/clientes/acme").json()["nombre"] == "ACME SA"
    assert admin.get("/api/clientes/fantasma").status_code == 404


def test_alta(admin):
    resp = admin.post("/api/clientes", json={"nombre": "Nueva SA", "slug": "nueva"})
    assert resp.status_code == 201
    assert resp.json()["slug"] == "nueva"


def test_alta_duplicada_mapea_a_422(admin):
    resp = admin.post("/api/clientes", json={"nombre": "ACME", "slug": "acme"})
    assert resp.status_code == 422
    assert "slug" in resp.json()["detail"]


def test_editar(admin):
    resp = admin.put("/api/clientes/acme", json={"nombre": "ACME SRL", "domain": "acme.contalibra.com.ar"})
    assert resp.status_code == 200
    assert resp.json()["nombre"] == "ACME SRL"


def test_cambiar_plan_invalido(admin):
    assert admin.put("/api/clientes/acme/plan", json={"plan": "enterprise"}).status_code == 422


def test_cambiar_plan_valido(admin):
    assert admin.put("/api/clientes/acme/plan", json={"plan": "basico"}).status_code == 200


def test_accion_de_estado(admin, motor_falso):
    assert admin.post("/api/clientes/acme/estado", json={"accion": "restart"}).status_code == 200
    assert ("acme", ("restart",)) in motor_falso["acciones"]


def test_accion_invalida(admin):
    assert admin.post("/api/clientes/acme/estado", json={"accion": "formatear"}).status_code == 422


def test_backup_devuelve_la_ruta(admin):
    archivo = admin.post("/api/clientes/acme/backup").json()["archivo"]
    assert archivo.endswith(".tar.gz")


def test_la_baja_exige_repetir_el_slug(admin):
    """La confirmación no es ceremonia: la baja borra contenedor, volumen y datos."""
    resp = admin.request(
        "DELETE", "/api/clientes/acme", json={"confirmar_slug": "acmee", "hacer_backup": False}
    )
    assert resp.status_code == 422
    # Y no tocó nada.
    assert admin.get("/api/clientes/acme").status_code == 200


def test_baja_con_confirmacion_correcta(admin):
    resp = admin.request(
        "DELETE", "/api/clientes/acme", json={"confirmar_slug": "acme", "hacer_backup": False}
    )
    assert resp.status_code == 200
    assert resp.json()["slug"] == "acme"


def test_planes(admin):
    planes = admin.get("/api/planes").json()
    assert [p["key"] for p in planes] == ["basico", "pro"]
    assert planes[1]["modulos"] == ["stock", "ventas"]
