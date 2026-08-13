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


class AltaIncompletaFalso(ServiceErrorFalso):
    """Como en libracore: subclase de `ServiceError`, no un tipo aparte.

    La herencia es lo que hace que el orden de los `except` del router importe,
    y por eso el falso la reproduce."""


@pytest.fixture
def servicios_falsos(inventario):
    """`libracore.admin.services` visto por el router."""
    llamadas = []
    servicios = types.SimpleNamespace()
    servicios.ServiceError = ServiceErrorFalso
    servicios.AltaIncompletaError = AltaIncompletaFalso

    def crear_cliente(**kwargs):
        if kwargs.get("slug") == "acme":
            raise ServiceErrorFalso("Ya existe una instancia con ese slug.")
        if kwargs.get("slug") == "sin-base":
            raise AltaIncompletaFalso(
                "La instancia 'sin-base' se creó pero su base nunca se armó."
            )
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
        # El motor devuelve el `cliente.json` entero, con la contraseña adentro.
        return {"slug": slug, "nombre": nombre, "domain": domain,
                "admin_user": "admin", "admin_password": "la-de-la-instancia",
                "plan": "pro", "port": 8081}

    def set_plan(slug, plan):
        if plan not in ("basico", "pro"):
            raise ServiceErrorFalso(f"Plan inválido: {plan!r}.")
        llamadas.append(("plan", slug, plan))

    ESTADOS_DE_SERVICIO = {"pausar": "pausado", "suspender": "suspendido", "activar": "activo"}

    def accion_estado(slug, accion, mensaje=""):
        if accion not in ("start", "stop", "restart") and accion not in ESTADOS_DE_SERVICIO:
            raise ServiceErrorFalso(f"Acción inválida: {accion!r}.")
        llamadas.append(("estado", slug, accion, mensaje))
        if accion in ESTADOS_DE_SERVICIO:
            # El motor escribe el `config.json` de la instancia; acá se refleja
            # en el inventario para que la respuesta del router lo devuelva. Es
            # lo que hace que estos tests midan el ida y vuelta y no el valor
            # con el que arrancó la instancia falsa.
            inventario.reemplazar(
                slug,
                servicio_estado=ESTADOS_DE_SERVICIO[accion],
                servicio_mensaje="" if accion == "activar" else mensaje,
            )

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


def test_un_alta_incompleta_es_409_y_no_422(admin):
    """La instancia SÍ se creó, sólo que no quedó entregable.

    El frontend lee un 422 como "el motor rechazó el alta, no se creó nada" y
    deja el formulario listo para reintentar — pero el slug ya está tomado, así
    que el reintento choca. Cualquier estado que no sea 422 cae en el camino que
    ya existe: relee el inventario, encuentra la instancia nueva y avisa que no
    se reintente.

    Es lo que le faltó al alta de `lagrace` el 2026-08-13, que devolvió un 504
    del proxy y por casualidad cayó en el camino correcto."""
    r = admin.post("/api/instancias", json={"nombre": "Sin Base", "slug": "sin-base"})
    assert r.status_code == 409, r.text
    assert "sin-base" in r.json()["detail"]


def test_el_409_no_se_lleva_puesto_al_422(admin):
    """Contraprueba del ORDEN de los `except`. `AltaIncompletaError` es una
    subclase de `ServiceError`: si el `except` genérico fuera primero se comería
    al específico y todo volvería a ser 422 — con el test de arriba en rojo pero
    éste en verde, que es lo que distingue "se rompió el orden" de "se rompió el
    mapeo"."""
    r = admin.post("/api/instancias", json={"nombre": "ACME", "slug": "acme"})
    assert r.status_code == 422, r.text


def test_editar(admin):
    resp = admin.put("/api/instancias/acme", json={"nombre": "ACME SRL", "domain": "acme.test"})
    assert resp.json()["nombre"] == "ACME SRL"


def test_la_edicion_no_devuelve_la_password_de_la_instancia(admin):
    """`editar_cliente` devuelve el `cliente.json` entero y ahí viaja
    `admin_password` en claro. Guardar un formulario que sólo cambia el nombre
    no puede mandarle la contraseña del admin al navegador.

    No es hipotético: el 2026-08-02 esa respuesta quedó impresa en un
    transcript durante la verificación en el VPS y hubo que rotar la
    contraseña de la instancia."""
    cuerpo = admin.put(
        "/api/instancias/acme", json={"nombre": "ACME SRL", "domain": "acme.test"}
    ).json()
    assert "admin_password" not in cuerpo
    assert cuerpo["admin_user"] == "admin"


def test_plan_invalido(admin):
    assert admin.put("/api/instancias/acme/plan", json={"plan": "enterprise"}).status_code == 422


def test_plan_valido(admin, servicios_falsos):
    assert admin.put("/api/instancias/acme/plan", json={"plan": "basico"}).status_code == 200
    assert ("plan", "acme", "basico") in servicios_falsos.llamadas


def test_accion_de_estado(admin, servicios_falsos):
    assert admin.post("/api/instancias/acme/estado", json={"accion": "restart"}).status_code == 200
    assert ("estado", "acme", "restart", "") in servicios_falsos.llamadas


def test_accion_invalida(admin):
    assert admin.post("/api/instancias/acme/estado", json={"accion": "formatear"}).status_code == 422


# ── corte de servicio ────────────────────────────────────────────────────────
#
# Es la palanca comercial, y hasta ahora vivía en la pantalla de Configuración
# del propio producto: el cliente al que se le corta el servicio era quien la
# tenía a mano.

def test_el_inventario_expone_el_corte_de_servicio(admin):
    """`estado` y `servicio_estado` son dos ejes, y los dos tienen que salir.

    `beta` corre (`running`) y está pausada. Una respuesta que sólo trajera
    `estado` deja al backoffice sin forma de mostrar que ese cliente está
    cortado.
    """
    instancias = {i["slug"]: i for i in admin.get("/api/instancias").json()["instancias"]}
    assert instancias["beta"]["estado"] == "running"
    assert instancias["beta"]["servicio_estado"] == "pausado"
    assert instancias["beta"]["servicio_mensaje"] == "Corte programado"
    assert instancias["acme"]["servicio_estado"] == "activo"


def test_suspender_lleva_el_mensaje_al_motor(admin, servicios_falsos):
    resp = admin.post("/api/instancias/acme/estado",
                      json={"accion": "suspender", "mensaje": "Factura de agosto impaga"})
    assert resp.status_code == 200
    assert ("estado", "acme", "suspender", "Factura de agosto impaga") in servicios_falsos.llamadas
    # Y la respuesta trae el estado ya aplicado: la pantalla se refresca con
    # esto, no con lo que tenía cargado el formulario.
    assert resp.json()["servicio_estado"] == "suspendido"
    assert resp.json()["servicio_mensaje"] == "Factura de agosto impaga"


def test_activar_borra_el_mensaje(admin):
    """El cliente que ya pagó no puede seguir viendo «falta de pago»."""
    admin.post("/api/instancias/acme/estado",
               json={"accion": "suspender", "mensaje": "Falta de pago"})
    cuerpo = admin.post("/api/instancias/acme/estado", json={"accion": "activar"}).json()
    assert cuerpo["servicio_estado"] == "activo"
    assert cuerpo["servicio_mensaje"] == ""


def test_pausar_sin_mensaje_es_valido(admin, servicios_falsos):
    """El mensaje es opcional: pausar sin texto tiene que seguir funcionando."""
    assert admin.post("/api/instancias/acme/estado",
                      json={"accion": "pausar"}).status_code == 200
    assert ("estado", "acme", "pausar", "") in servicios_falsos.llamadas


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


def test_la_libracore_instalada_entiende_el_mensaje_del_corte():
    """El pin de LibraCore de este repo tiene que soportar lo que el router usa.

    Todo lo de arriba corre contra `servicios_falsos`, así que un pin viejo da
    la suite entera en verde y falla recién en producción, con un `TypeError`
    dentro del panel. **Ya pasó**: el 2026-08-12 los seis paneles devolvían 500
    porque el pin de acá (v1.3.0) no entendía el `configure(backup_zip=True)`
    que los productos empezaron a pasar. Este test es el mismo acoplamiento
    mirado desde el otro lado.
    """
    import inspect

    from libracore.admin import services

    firma = inspect.signature(services.accion_estado)
    assert "mensaje" in firma.parameters, (
        "La libracore instalada no acepta `mensaje` en accion_estado: el corte "
        "de servicio del backoffice le borraría el texto al cliente. Hace falta "
        "subir el pin de libracore en backend/pyproject.toml."
    )
