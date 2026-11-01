"""
La consola de revendedores, de punta a punta: la consola real le habla a backoffices reales por `ASGITransport`, con el
token real. Un doble del backoffice estaría de acuerdo con cualquier contrato.

🔴 El caso que justifica el diseño: desbloquear a un revendedor no le devuelve el servicio a un cliente que estaba
suspendido por otra razón.
"""
import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from libra_backoffice.almacen_revendedores import AlmacenDeRevendedores, AlmacenIlegible
from libra_backoffice.app import create_app
from libra_backoffice.cliente_consola import ClienteConsola
from libra_backoffice.inventario import Instancia, InstanciaDesconocida, InventarioDeConsola
from libra_backoffice.settings import ConfiguracionInvalida, ProductoDeConsola, cargar_settings

from .conftest import PASSWORD, USUARIO, construir_settings, login

TOKEN_CONSOLA = "token-de-consola-de-prueba"
MENSAJE = "Servicio suspendido. Comunicate con tu proveedor."


class ErrorDeServicio(Exception):
    pass


class ServiciosFalsos:
    """Lo que hace `accion_estado` del motor: cambiar el estado de servicio en el disco de la instancia."""

    ServiceError = ErrorDeServicio

    def __init__(self, inventario):
        self._inventario = inventario
        self.llamadas: list[tuple[str, str, str]] = []
        self.fallar_en: set[str] = set()

    def accion_estado(self, slug, accion, mensaje=""):
        self.llamadas.append((slug, accion, mensaje))
        if slug in self.fallar_en:
            raise ErrorDeServicio("La instancia todavía no creó su configuración.")
        estado = {"suspender": "suspendido", "activar": "activo"}[accion]
        self._inventario.reemplazar(slug, servicio_estado=estado, servicio_mensaje=mensaje)


class InventarioDeProducto:
    def __init__(self, *instancias):
        self._instancias = {i.slug: i for i in instancias}
        self.servicios = ServiciosFalsos(self)

    def verificar_scripts(self):
        """Sin scripts: alcanza para `/health`."""

    def listar(self):
        return list(self._instancias.values())

    def obtener(self, slug):
        if slug not in self._instancias:
            raise InstanciaDesconocida(slug)
        return self._instancias[slug]

    def reemplazar(self, slug, **campos):
        self._instancias[slug] = replace(self._instancias[slug], **campos)


def _instancia(slug, **campos):
    return Instancia(slug=slug, nombre=slug.title(), container=f"p-{slug}", domain=f"{slug}.test", estado="running",
                     **campos)


class Transporte(httpx.AsyncBaseTransport):
    """`http://ventalibra-admin:8000` por DNS interno de Docker. Sin app registrada, `ConnectError`: un backoffice caído."""

    def __init__(self, apps):
        self.transportes = {host: httpx.ASGITransport(app=app) for host, app in apps.items()}

    async def handle_async_request(self, request):
        transporte = self.transportes.get(request.url.host)
        if transporte is None:
            raise httpx.ConnectError(f"Name or service not known: {request.url.host}")
        return await transporte.handle_async_request(request)


@pytest.fixture
def venta():
    return InventarioDeProducto(_instancia("acme"), _instancia("beta"), _instancia("moroso", servicio_estado="suspendido"))


@pytest.fixture
def cargo():
    return InventarioDeProducto(_instancia("flete"))


@pytest.fixture
def transporte(tmp_path, venta, cargo):
    apps = {
        "ventalibra-admin": create_app(
            construir_settings(tmp_path, product_slug="ventalibra", consola_token=TOKEN_CONSOLA), inventario=venta),
        "libracargo-admin": create_app(
            construir_settings(tmp_path, product_slug="libracargo", consola_token=TOKEN_CONSOLA), inventario=cargo),
    }
    return Transporte(apps)


PRODUCTOS = (ProductoDeConsola("ventalibra", "VentaLibra", "http://ventalibra-admin:8000"),
             ProductoDeConsola("libracargo", "LibraCargo", "http://libracargo-admin:8000"))


@pytest.fixture
def consola(tmp_path, transporte):
    settings = construir_settings(
        tmp_path, product_slug="librasuite", product_name="LibraSuite", features=("revendedores",), repo_root=None,
        db_filename="", consola_token=TOKEN_CONSOLA, consola_productos=PRODUCTOS,
        revendedores_path=tmp_path / "revendedores.json")
    app = create_app(settings, inventario=InventarioDeConsola())
    app.state.cliente_consola = ClienteConsola(PRODUCTOS, TOKEN_CONSOLA, transport=transporte)
    with TestClient(app, base_url="https://testserver") as c:
        assert login(c, {"username": USUARIO, "password": PASSWORD}).status_code == 200
        yield c


def _alta(consola, nombre="Distribuidora Sur", productos=("ventalibra", "libracargo")):
    respuesta = consola.post("/api/revendedores", json={"nombre": nombre, "productos": list(productos)})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _asignar(consola, identificador, producto, slug):
    respuesta = consola.post(f"/api/revendedores/{identificador}/instancias", json={"producto": producto, "slug": slug})
    assert respuesta.status_code == 200, respuesta.text


def _bloquear(consola, identificador, nombre="Distribuidora Sur"):
    return consola.post(f"/api/revendedores/{identificador}/bloquear", json={"confirmar": nombre, "mensaje": MENSAJE})


def _resultados(respuesta):
    return {f"{f['producto']}/{f['slug']}": f["resultado"] for f in respuesta.json()["resultados"]}


# ── /api/consola, en un backoffice de producto ─────────────────────────────


def _cliente_de_producto(tmp_path, inventario, **extra):
    return TestClient(create_app(construir_settings(tmp_path, **extra), inventario=inventario),
                      base_url="https://testserver")


def test_sin_token_configurado_la_ruta_no_existe(tmp_path, venta):
    with _cliente_de_producto(tmp_path, venta) as c:
        assert c.get("/api/consola/instancias", headers={"X-Consola-Token": ""}).status_code == 404
        assert c.get("/api/consola/instancias", headers={"X-Consola-Token": "cualquiera"}).status_code == 404


def test_con_token_equivocado_no_entra(tmp_path, venta):
    with _cliente_de_producto(tmp_path, venta, consola_token=TOKEN_CONSOLA) as c:
        assert c.get("/api/consola/instancias").status_code == 401
        assert c.get("/api/consola/instancias", headers={"X-Consola-Token": "otro"}).status_code == 401


def test_el_token_sirve_solo_para_listar_y_cortar(tmp_path, venta):
    cabecera = {"X-Consola-Token": TOKEN_CONSOLA}
    with _cliente_de_producto(tmp_path, venta, consola_token=TOKEN_CONSOLA) as c:
        fila = c.get("/api/consola/instancias", headers=cabecera).json()["instancias"][0]
        assert set(fila) == {"slug", "nombre", "domain", "plan", "estado", "servicio_estado"}
        # El resto de la API sigue pidiendo la sesión del superadmin.
        assert c.get("/api/instancias", headers=cabecera).status_code == 401
        assert c.post("/api/instancias/acme/baja", headers=cabecera, json={}).status_code == 401
        for accion in ("start", "stop", "restart", "pausar"):
            rechazo = c.post("/api/consola/instancias/acme/estado", headers=cabecera, json={"accion": accion})
            assert rechazo.status_code == 422
    assert venta.servicios.llamadas == []


def test_una_instancia_desconocida_da_404(tmp_path, venta):
    with _cliente_de_producto(tmp_path, venta, consola_token=TOKEN_CONSOLA) as c:
        respuesta = c.post("/api/consola/instancias/nadie/estado", headers={"X-Consola-Token": TOKEN_CONSOLA},
                           json={"accion": "suspender"})
    assert respuesta.status_code == 404


# ── la consola ──────────────────────────────────────────────────────────────


def test_sin_sesion_no_hay_consola(tmp_path, transporte):
    settings = construir_settings(tmp_path, product_slug="librasuite", features=("revendedores",), repo_root=None,
                                  consola_token=TOKEN_CONSOLA, consola_productos=PRODUCTOS)
    with TestClient(create_app(settings, inventario=InventarioDeConsola()), base_url="https://testserver") as c:
        assert c.get("/api/revendedores").status_code == 401
        assert c.get("/health").json()["ok"] is True


def test_un_backoffice_de_producto_no_tiene_revendedores(tmp_path, venta):
    with _cliente_de_producto(tmp_path, venta, consola_token=TOKEN_CONSOLA) as c:
        assert login(c, {"username": USUARIO, "password": PASSWORD}).status_code == 200
        assert c.get("/api/revendedores").status_code == 404


def test_el_catalogo_muestra_las_instancias_de_todos_y_de_quien_son(consola):
    identificador = _alta(consola)
    _asignar(consola, identificador, "ventalibra", "acme")
    productos = {p["slug"]: p for p in consola.get("/api/revendedores/catalogo").json()["productos"]}
    assert productos["libracargo"]["alcanzable"] is True
    filas = {i["slug"]: i for i in productos["ventalibra"]["instancias"]}
    assert filas["acme"]["revendedor"] == "Distribuidora Sur" and filas["beta"]["revendedor"] == ""


def test_un_backoffice_caido_no_tira_el_catalogo(consola, transporte):
    del transporte.transportes["libracargo-admin"]
    productos = {p["slug"]: p for p in consola.get("/api/revendedores/catalogo").json()["productos"]}
    assert productos["libracargo"]["alcanzable"] is False and productos["ventalibra"]["alcanzable"] is True


def test_un_producto_desconocido_se_rechaza(consola):
    assert consola.post("/api/revendedores", json={"nombre": "X", "productos": ["inventado"]}).status_code == 422


def test_solo_se_asignan_instancias_de_productos_habilitados(consola):
    identificador = _alta(consola, productos=("ventalibra",))
    respuesta = consola.post(f"/api/revendedores/{identificador}/instancias",
                             json={"producto": "libracargo", "slug": "flete"})
    assert respuesta.status_code == 409


def test_una_instancia_es_de_un_solo_revendedor(consola):
    primero = _alta(consola)
    segundo = _alta(consola, nombre="Otro")
    _asignar(consola, primero, "ventalibra", "acme")
    respuesta = consola.post(f"/api/revendedores/{segundo}/instancias", json={"producto": "ventalibra", "slug": "acme"})
    assert respuesta.status_code == 409 and "Distribuidora Sur" in respuesta.json()["detail"]


def test_una_instancia_que_no_existe_no_se_asigna(consola):
    identificador = _alta(consola)
    respuesta = consola.post(f"/api/revendedores/{identificador}/instancias",
                             json={"producto": "ventalibra", "slug": "nadie"})
    assert respuesta.status_code == 404


def test_no_se_deshabilita_un_producto_con_instancias(consola):
    identificador = _alta(consola)
    _asignar(consola, identificador, "ventalibra", "acme")
    respuesta = consola.put(f"/api/revendedores/{identificador}",
                            json={"nombre": "Distribuidora Sur", "productos": ["libracargo"]})
    assert respuesta.status_code == 409


# ── bloquear y desbloquear ─────────────────────────────────────────────────


def test_bloquear_pide_el_nombre_escrito(consola, venta):
    identificador = _alta(consola)
    _asignar(consola, identificador, "ventalibra", "acme")
    assert _bloquear(consola, identificador, nombre="otra cosa").status_code == 422
    assert venta.servicios.llamadas == []


def test_bloquear_suspende_en_todos_los_productos_con_el_mensaje(consola, venta, cargo):
    identificador = _alta(consola)
    _asignar(consola, identificador, "ventalibra", "acme")
    _asignar(consola, identificador, "libracargo", "flete")
    respuesta = _bloquear(consola, identificador)
    assert respuesta.status_code == 200
    assert _resultados(respuesta) == {"ventalibra/acme": "suspendida", "libracargo/flete": "suspendida"}
    assert venta.obtener("acme").servicio_estado == "suspendido" and venta.obtener("acme").servicio_mensaje == MENSAJE
    assert cargo.obtener("flete").servicio_estado == "suspendido"
    assert venta.obtener("beta").servicio_estado == "activo"
    assert respuesta.json()["revendedor"]["estado"] == "bloqueado"


def test_desbloquear_no_devuelve_lo_que_ya_estaba_suspendido(consola, venta):
    """🔴 `moroso` estaba cortada antes del bloqueo: no la suspendió la consola y no vuelve."""
    identificador = _alta(consola)
    _asignar(consola, identificador, "ventalibra", "acme")
    _asignar(consola, identificador, "ventalibra", "moroso")
    assert _resultados(_bloquear(consola, identificador))["ventalibra/moroso"] == "ya_estaba_suspendida"
    respuesta = consola.post(f"/api/revendedores/{identificador}/desbloquear")
    assert _resultados(respuesta) == {"ventalibra/acme": "activada", "ventalibra/moroso": "sin_cambios"}
    assert venta.obtener("acme").servicio_estado == "activo"
    assert venta.obtener("moroso").servicio_estado == "suspendido"
    assert ("moroso", "activar", "") not in venta.servicios.llamadas
    assert respuesta.json()["revendedor"]["estado"] == "activo"


def test_un_reintento_de_bloqueo_no_pierde_lo_que_suspendio_la_consola(consola, venta):
    """Bloquear dos veces no convierte lo suspendido por la consola en «ya estaba suspendida»."""
    identificador = _alta(consola)
    _asignar(consola, identificador, "ventalibra", "acme")
    _bloquear(consola, identificador)
    assert _resultados(_bloquear(consola, identificador))["ventalibra/acme"] == "suspendida"
    consola.post(f"/api/revendedores/{identificador}/desbloquear")
    assert venta.obtener("acme").servicio_estado == "activo"


def test_un_backoffice_caido_se_informa_y_el_reintento_sigue(consola, transporte, venta, cargo):
    identificador = _alta(consola)
    _asignar(consola, identificador, "ventalibra", "acme")
    _asignar(consola, identificador, "libracargo", "flete")
    guardado = transporte.transportes.pop("libracargo-admin")

    respuesta = _bloquear(consola, identificador)
    assert _resultados(respuesta) == {"ventalibra/acme": "suspendida", "libracargo/flete": "fallo"}
    assert respuesta.json()["revendedor"]["estado"] == "bloqueado"

    transporte.transportes["libracargo-admin"] = guardado
    assert _resultados(_bloquear(consola, identificador))["libracargo/flete"] == "suspendida"
    assert cargo.obtener("flete").servicio_estado == "suspendido"


def test_si_una_instancia_rechaza_el_corte_las_demas_siguen(consola, venta):
    identificador = _alta(consola)
    _asignar(consola, identificador, "ventalibra", "acme")
    _asignar(consola, identificador, "ventalibra", "beta")
    venta.servicios.fallar_en.add("acme")
    assert _resultados(_bloquear(consola, identificador)) == {"ventalibra/acme": "fallo", "ventalibra/beta": "suspendida"}


def test_si_no_se_pudo_reactivar_todo_sigue_bloqueado(consola, transporte, venta):
    identificador = _alta(consola)
    _asignar(consola, identificador, "ventalibra", "acme")
    _bloquear(consola, identificador)
    guardado = transporte.transportes.pop("ventalibra-admin")

    respuesta = consola.post(f"/api/revendedores/{identificador}/desbloquear")
    assert _resultados(respuesta) == {"ventalibra/acme": "fallo"}
    assert respuesta.json()["revendedor"]["estado"] == "bloqueado"

    transporte.transportes["ventalibra-admin"] = guardado
    respuesta = consola.post(f"/api/revendedores/{identificador}/desbloquear")
    assert respuesta.json()["revendedor"]["estado"] == "activo"
    assert venta.obtener("acme").servicio_estado == "activo"


def test_bloqueado_no_recibe_instancias_ni_suelta_las_suspendidas(consola):
    identificador = _alta(consola)
    _asignar(consola, identificador, "ventalibra", "acme")
    _bloquear(consola, identificador)
    nueva = consola.post(f"/api/revendedores/{identificador}/instancias", json={"producto": "ventalibra", "slug": "beta"})
    assert nueva.status_code == 409
    assert consola.delete(f"/api/revendedores/{identificador}/instancias/ventalibra/acme").status_code == 409


def test_cada_accion_queda_en_el_historial_con_quien_la_hizo(consola):
    identificador = _alta(consola)
    _asignar(consola, identificador, "ventalibra", "acme")
    _bloquear(consola, identificador)
    historial = consola.get(f"/api/revendedores/{identificador}").json()["historial"]
    assert [h["accion"] for h in historial] == ["bloqueo", "instancia asignada", "alta"]
    assert {h["quien"] for h in historial} == {USUARIO}


# ── el almacén y el arranque ───────────────────────────────────────────────


def test_el_token_no_viaja_al_navegador(consola):
    identificador = _alta(consola)
    assert TOKEN_CONSOLA not in consola.get(f"/api/revendedores/{identificador}").text
    assert TOKEN_CONSOLA not in consola.get("/api/revendedores/catalogo").text


@pytest.mark.parametrize("contenido", ["{no es json", "[]", '{"otra": 1}'])
def test_un_archivo_ilegible_no_se_lee_como_vacio(tmp_path, contenido):
    """Leer vacío y guardar borraría a todos los revendedores."""
    ruta = tmp_path / "revendedores.json"
    ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(AlmacenIlegible):
        AlmacenDeRevendedores(ruta).leer()


def test_con_el_archivo_roto_la_consola_avisa_y_no_escribe(consola, tmp_path):
    ruta = tmp_path / "revendedores.json"
    ruta.write_text("{roto", encoding="utf-8")
    assert consola.get("/api/revendedores").status_code == 503
    assert consola.post("/api/revendedores", json={"nombre": "X"}).status_code == 503
    assert ruta.read_text(encoding="utf-8") == "{roto"


def test_el_almacen_persiste(tmp_path):
    almacen = AlmacenDeRevendedores(tmp_path / "sub" / "revendedores.json")
    assert almacen.leer() == []
    almacen.guardar([{"id": "1", "nombre": "Ñandú"}])
    assert json.loads((tmp_path / "sub" / "revendedores.json").read_text(encoding="utf-8"))["revendedores"][0]["id"] == "1"
    assert almacen.leer()[0]["nombre"] == "Ñandú"


ENTORNO = {"PRODUCT_SLUG": "librasuite", "FEATURES": "revendedores", "CONSOLA_TOKEN": "t",
           "CONSOLA_PRODUCTOS": "ventalibra:VentaLibra,libracargo:LibraCargo",
           "ADMIN_PANEL_ESTADO_PATH": "/var/lib/libra-backoffice/login.json"}


def test_la_consola_arranca_sin_repo_de_producto():
    settings = cargar_settings(ENTORNO)
    assert settings.repo_root is None
    assert [p.url for p in settings.consola_productos] == ["http://ventalibra-admin:8000", "http://libracargo-admin:8000"]
    assert str(settings.revendedores_path) == "/var/lib/libra-backoffice/revendedores.json"


def test_un_producto_sin_backoffice_declara_su_url():
    settings = cargar_settings({**ENTORNO, "CONSOLA_PRODUCTOS": "ventalibra:VentaLibra,librabot:LibraBot:http://librabot-librabot-1:8790"})
    assert [p.url for p in settings.consola_productos] == ["http://ventalibra-admin:8000", "http://librabot-librabot-1:8790"]


@pytest.mark.parametrize("cambio", [
    {"CONSOLA_TOKEN": ""}, {"CONSOLA_PRODUCTOS": ""}, {"CONSOLA_PRODUCTOS": "sin-nombre"},
    {"FEATURES": "revendedores,instancias"},
])
def test_una_consola_mal_configurada_no_arranca(cambio):
    with pytest.raises(ConfiguracionInvalida):
        cargar_settings({**ENTORNO, **cambio})
