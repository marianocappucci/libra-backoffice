"""
Inventario y ciclo de vida de las instancias del producto.

**No reimplementa nada.** Toda la lógica real (Docker, NPM, planes, backup,
baja) vive en `libracore.admin.services`, que envuelve los scripts
`panel_admin.py` / `nuevo_cliente.py` / `plans.py` del repo de cada producto.
Acá se traduce a JSON: la versión Jinja2 de este mismo router devolvía
plantillas.

Los seis productos tienen esos scripts y se administran igual, así que este
router no tiene ninguna rama por producto.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from libracore.abono import calcular_abono
from libracore.limites import MAXIMO as MAXIMO_DE_SUCURSALES
from libracore.validacion import sin_booleanos
from pydantic import BaseModel, Field

from ..cliente_instancia import InstanciaInalcanzable, RespuestaDeInstancia
from ..deps import admin_actual, requiere_feature
from ..inventario import InstanciaDesconocida
from . import apariencia

router = APIRouter(
    prefix="/api",
    tags=["instancias"],
    dependencies=[Depends(requiere_feature("instancias")), Depends(admin_actual)],
)


def _inventario(request: Request):
    return request.app.state.inventario


def _servicios(request: Request):
    return _inventario(request).servicios


def _obtener(request: Request, slug: str):
    try:
        return _inventario(request).obtener(slug)
    except InstanciaDesconocida:
        raise HTTPException(404, f"No hay ninguna instancia '{slug}'.")


class InstanciaIn(BaseModel):
    nombre: str
    slug: str = ""
    domain: str = ""
    port: int = 0
    admin_user: str = "admin"
    admin_password: str = ""
    plan: str = "basico"
    # Identidad fiscal. `empresa_nombre` es la razón social —que puede no ser el
    # nombre comercial de `nombre`— y el motor la cae a `nombre` si viene vacía.
    #
    # El CUIT es **obligatorio del lado del motor**, y no se repite la
    # validación acá: duplicarla haría que las dos versiones se separaran y que
    # esta pantalla aceptara altas que el motor después rechaza (o al revés).
    # Un CUIT faltante o mal formado vuelve como 422 con el motivo, que es el
    # camino que el formulario ya sabe mostrar.
    empresa_cuit: str = ""
    empresa_nombre: str = ""
    # Opt-in explícito para las instancias de demo, que no tienen CUIT. Sin él
    # el alta sin CUIT se rechaza: una instancia sin identidad no se puede
    # agrupar por razón social en el panel del dueño.
    sin_identidad: bool = False
    setup_npm: bool = True
    # Sucursales que el cliente contrata (ADR-041 de libracore). Sólo para los planes que cobran sucursales adicionales (los que declaran
    # `adicional` en `GET /api/planes`); la instancia NACE con el tope en su `config.json`. `None` = no cargarlo: queda sin límite.
    sucursales_contratadas: int | None = Field(default=None, ge=1, le=MAXIMO_DE_SUCURSALES)

    _no_son_booleanos = sin_booleanos("sucursales_contratadas")


class SucursalesIn(BaseModel):
    """Las sucursales contratadas de una instancia. `null` quita el dato: la instancia queda sin límite («Sin cargar»)."""

    contratadas: int | None = Field(..., ge=1, le=MAXIMO_DE_SUCURSALES)

    _no_son_booleanos = sin_booleanos("contratadas")


class InstanciaEdit(BaseModel):
    nombre: str
    domain: str = ""


class PlanIn(BaseModel):
    plan: str


class AddonIn(BaseModel):
    habilitado: bool


class EstadoIn(BaseModel):
    accion: str
    # Sólo lo usan `pausar` y `suspender`: es el texto que ve el cliente en el
    # banner de aviso o en la pantalla de suspensión. `activar` lo ignora y el
    # motor lo limpia.
    mensaje: str = ""


class BajaIn(BaseModel):
    # Se pide repetir el slug. No es ceremonia: la baja borra el contenedor, su
    # volumen y el directorio de datos de un cliente real.
    confirmar_slug: str
    hacer_backup: bool = True


class InstanciaEditada(BaseModel):
    """Lo que devuelve la edición: el `cliente.json` **filtrado**.

    `editar_cliente` devuelve la metadata entera, y ahí adentro viaja
    `admin_password` en claro. Sin este `response_model` la contraseña del admin
    de la instancia sale al navegador —y a cualquier log intermedio— en cada
    guardado de un formulario que sólo cambia el nombre y el dominio. Pasó de
    verdad el 2026-08-02: quedó impresa en un transcript y hubo que rotarla.
    """

    slug: str
    nombre: str = ""
    domain: str = ""
    port: int | str = ""
    container: str = ""
    admin_user: str = ""
    plan: str = ""


class InstanciaCreada(InstanciaEditada):
    """Lo que devuelve el alta.

    Es la edición **más** `admin_password`, y esa diferencia es deliberada: si
    el alta se pidió sin contraseña, el motor genera una y esta respuesta es la
    única vez que la UI la ve. Queda también en `clientes/<slug>/cliente.json`
    del host, que es el único lugar donde recuperarla si el navegador nunca
    llegó a ver esta respuesta.
    """

    admin_password: str = ""
    # 🔴 La credencial con la que el panel del dueño le pide los números a esta
    # sucursal (`X-Panel-Auth` contra `LIBRA_PANEL_TOKEN`). Igual que la
    # contraseña: el motor la genera —aleatoria y distinta por instancia— y esta
    # respuesta es la única vez que sale del host por HTTP.
    #
    # No está en `InstanciaEditada`, y esa herencia es la que lo garantiza:
    # cualquier otro endpoint que devuelva una instancia usa aquel modelo y no
    # puede arrastrarla sin que alguien lo escriba a mano. Si el navegador nunca
    # vio esta respuesta, el valor sigue estando en el `docker-compose.yml` de
    # la instancia, en el host.
    panel_token: str = ""
    # `None` = no se intentó (sin dominio, o NPM no configurado). `False` = se
    # intentó y falló: el cliente existe pero su dominio no resuelve todavía.
    proxy_ok: bool | None = None


@router.get("/instancias")
def listar(request: Request):
    return {"instancias": [i.dict() for i in _inventario(request).listar()]}


@router.get("/instancias/{slug}")
def detalle(slug: str, request: Request):
    return _obtener(request, slug).dict()


@router.post("/instancias", status_code=201, response_model=InstanciaCreada)
def crear(datos: InstanciaIn, request: Request):
    servicios = _servicios(request)
    if datos.sucursales_contratadas is not None and not (_plan_de(servicios, datos.plan) or {}).get("adicional"):
        raise HTTPException(
            422, f"El plan {datos.plan!r} no cobra sucursales adicionales: no corresponde cargar sucursales contratadas."
        )
    try:
        creada = servicios.crear_cliente(**datos.model_dump())
        # El tema de la suite (feature `apariencia`) llega a la instancia nueva. Mejor esfuerzo: nunca hace fallar el alta.
        apariencia.empujar_a_una_instancia_nueva(request, creada.get("slug", ""))
        return creada
    # 🔴 409 y no 422: la instancia SÍ se creó, sólo que no quedó entregable
    # (su base no subió, o no se pudo aplicar el plan). El frontend lee un 422
    # como "el motor rechazó el alta, no se creó nada" y deja el formulario
    # listo para reintentar — pero el slug ya está tomado, así que el reintento
    # choca. Con cualquier estado que no sea 422 cae en el camino que ya
    # existe: relee el inventario, encuentra la instancia nueva y avisa que no
    # se reintente.
    #
    # `getattr` porque el atributo lo agrega libracore v1.35.0: contra una
    # versión anterior no existe y esto tiene que seguir compilando. Una tupla
    # vacía nunca matchea, así que degrada al `except` de abajo.
    except getattr(servicios, "AltaIncompletaError", ()) as exc:
        raise HTTPException(409, str(exc))
    except servicios.ServiceError as exc:
        raise HTTPException(422, str(exc))


@router.put("/instancias/{slug}", response_model=InstanciaEditada)
def editar(slug: str, datos: InstanciaEdit, request: Request):
    servicios = _servicios(request)
    try:
        return servicios.editar_cliente(slug, nombre=datos.nombre, domain=datos.domain)
    except servicios.ServiceError as exc:
        raise HTTPException(404, str(exc))


@router.put("/instancias/{slug}/plan")
def cambiar_plan(slug: str, datos: PlanIn, request: Request):
    servicios = _servicios(request)
    try:
        servicios.set_plan(slug, datos.plan)
    except servicios.ServiceError as exc:
        raise HTTPException(422, str(exc))
    return _obtener(request, slug).dict()


# Add-ons (módulos sueltos, fuera de los planes). A diferencia del plan, el
# estado vive en la base viva de la instancia, así que el servicio llega por
# `docker exec` (ver libracore.admin.services.set_addon). El producto sin
# add-ons devuelve `{}` y el frontend no muestra la sección.
#
# 🔑 El valor de cada add-on es `true`, `false` o **`null`**, y `null` significa
# "no se pudo leer": el `docker exec` falló (contenedor caído, o el producto no
# exporta el contrato `app.database.get_modulos`). Se pasa tal cual al frontend
# a propósito — traducirlo a `false` acá sería volver al defecto que esto
# arregla: una pantalla que muestra el add-on apagado cuando en realidad no
# sabe. El motivo concreto queda en el log del proceso.
@router.get("/instancias/{slug}/addons")
def listar_addons(slug: str, request: Request):
    servicios = _servicios(request)
    try:
        return servicios.addons_de_instancia(slug)
    except servicios.ServiceError as exc:
        raise HTTPException(404, str(exc))


@router.put("/instancias/{slug}/addons/{addon}")
def cambiar_addon(slug: str, addon: str, datos: AddonIn, request: Request):
    servicios = _servicios(request)
    try:
        servicios.set_addon(slug, addon, datos.habilitado)
    except servicios.ServiceError as exc:
        raise HTTPException(422, str(exc))
    return servicios.addons_de_instancia(slug)


@router.post("/instancias/{slug}/estado")
def cambiar_estado(slug: str, datos: EstadoIn, request: Request):
    servicios = _servicios(request)
    try:
        servicios.accion_estado(slug, datos.accion, mensaje=datos.mensaje)
    except servicios.ServiceError as exc:
        raise HTTPException(422, str(exc))
    return _obtener(request, slug).dict()


@router.post("/instancias/{slug}/backup")
def backup(slug: str, request: Request):
    servicios = _servicios(request)
    try:
        return {"archivo": servicios.backup_cliente(slug)}
    except servicios.ServiceError as exc:
        raise HTTPException(422, str(exc))


# POST y no DELETE, por dos razones que apuntan al mismo lado. La baja lleva un
# cuerpo obligatorio (la confirmación del slug) y el `api-client` de libra-ui
# —compartido por los seis productos— manda `DELETE` sin cuerpo; hacerlo con
# DELETE obligaría a versionar ese paquete para esta sola ruta. Y las otras dos
# acciones destructivas de este router ya son POST sobre un sub-recurso
# (`/estado`, `/backup`), igual que el `POST /clientes/<slug>/eliminar` del
# backoffice Jinja2 que este reemplaza.
@router.post("/instancias/{slug}/baja")
def baja(slug: str, datos: BajaIn, request: Request):
    servicios = _servicios(request)
    if datos.confirmar_slug != slug:
        raise HTTPException(422, "La confirmación no coincide con el slug de la instancia.")
    try:
        return servicios.eliminar_cliente(slug, hacer_backup=datos.hacer_backup)
    except servicios.ServiceError as exc:
        raise HTTPException(422, str(exc))


@router.get("/planes")
def planes(request: Request):
    return _servicios(request).planes_info()


# ── El abono: precio del plan + sucursales adicionales CONTRATADAS (ADR-041 de libracore, ADR-073 de VentaLibra) ──
#
# La cantidad contratada vive en la INSTANCIA (`libracore.limites`): es lo que le permite bloquear un alta sin salir de su proceso. Este router
# se la pide con el token de servicio y calcula con `calcular_abono`; no guarda nada propio. Sólo para los planes que declaran `adicional` en
# `planes_info()`: en los demás productos todo esto contesta «no aplica» y la pantalla no muestra nada.

_SIN_SOPORTE = (
    "La instancia todavía no expone las sucursales contratadas (libracore anterior a v1.153.0): hay que actualizarla."
)


def _plan_de(servicios, clave: str) -> dict | None:
    """El plan de `planes_info()` que rige para `clave`, que es lo que dice el `cliente.json`: un plan retirado se resuelve a su reemplazo
    (`services.plan_vigente`, de libracore v1.153.0; sin él, el nombre tal cual)."""
    resolver = getattr(servicios, "plan_vigente", None)
    vigente = resolver(clave) if resolver else clave
    return next((p for p in servicios.planes_info() if p.get("key") == vigente), None)


def _sin_soporte(exc: RespuestaDeInstancia) -> bool:
    # 404/405: la ruta no existe (el fallback de la SPA sólo sirve GET). «no es JSON»: el fallback contestó 200 con HTML.
    return exc.status_code in (404, 405) or "no es JSON" in exc.detalle


def _abono_de(instancia, plan: dict, *, contratadas: int | None, activas: int | None) -> dict:
    adicional = plan["adicional"]
    return {
        "slug": instancia.slug, "plan": plan["key"], "plan_label": plan.get("label", plan["key"]), "aplica": True, "estado": "ok", "detalle": "",
        "unidad": adicional["unidad"], "incluidas": adicional["incluidas"],
        "precio_base": plan["precio"], "precio_adicional": adicional["precio"],
        "contratadas": contratadas, "activas": activas,
        "abono": calcular_abono(plan["precio"], adicional["incluidas"], adicional["precio"], contratadas),
    }


def _sin_abono(instancia, plan: dict, estado: str, detalle: str) -> dict:
    """La instancia no pudo contestar: se sabe el precio del plan, no lo contratado. Sin `abono`: calcularlo con `contratadas=None` diría
    «sólo la base», que es un dato que NO tenemos."""
    adicional = plan["adicional"]
    return {
        "slug": instancia.slug, "plan": plan["key"], "plan_label": plan.get("label", plan["key"]), "aplica": True, "estado": estado, "detalle": detalle,
        "unidad": adicional["unidad"], "incluidas": adicional["incluidas"],
        "precio_base": plan["precio"], "precio_adicional": adicional["precio"],
        "contratadas": None, "activas": None, "abono": None,
    }


@router.get("/instancias/{slug}/abono")
async def abono(slug: str, request: Request):
    """Plan, precios, `contratadas` y `activas` de la instancia, y el abono (`calcular_abono`).

    Siempre 200 con un `estado`, para que la pantalla muestre el motivo sin romperse: `ok`; `no_aplica` (el plan no cobra sucursales
    adicionales); `detenida` (el contenedor no corre); `inalcanzable` (corre y no contesta); `sin_soporte` (contesta, pero su libracore no tiene
    el endpoint: hay que actualizarla); `error`. `contratadas: null` en `ok` es «Sin cargar»."""
    instancia = _obtener(request, slug)
    plan = _plan_de(_servicios(request), instancia.plan)
    if not plan or not plan.get("adicional"):
        return {"slug": slug, "plan": instancia.plan, "aplica": False, "estado": "no_aplica", "detalle": ""}
    if instancia.estado != "running":
        return _sin_abono(instancia, plan, "detenida", "El contenedor no está corriendo.")
    try:
        respuesta = await request.app.state.cliente_instancia.pedir(
            "GET", instancia, request.app.state.settings.limites_instancia_path)
    except InstanciaInalcanzable as exc:
        return _sin_abono(instancia, plan, "inalcanzable", exc.detalle)
    except RespuestaDeInstancia as exc:
        if _sin_soporte(exc):
            return _sin_abono(instancia, plan, "sin_soporte", _SIN_SOPORTE)
        return _sin_abono(instancia, plan, "error", exc.detalle)
    return _abono_de(instancia, plan, contratadas=respuesta.get("contratadas"), activas=respuesta.get("activas"))


@router.put("/instancias/{slug}/sucursales")
async def cargar_sucursales(slug: str, datos: SucursalesIn, request: Request):
    """Carga (o quita, con `null`) las sucursales contratadas en la instancia y devuelve el abono resultante, igual que `GET .../abono`.

    A diferencia del `GET`, acá un fallo SÍ es un error HTTP: guardar que no se guardó no puede salir como 200. 502 si la instancia no
    contesta; 409 si no expone el endpoint (hay que actualizarla); el 422 de la instancia llega como 422."""
    instancia = _obtener(request, slug)
    plan = _plan_de(_servicios(request), instancia.plan)
    if not plan or not plan.get("adicional"):
        raise HTTPException(422, f"El plan {instancia.plan!r} no cobra sucursales adicionales: no hay nada que cargar.")
    try:
        respuesta = await request.app.state.cliente_instancia.pedir(
            "PUT", instancia, request.app.state.settings.limites_instancia_path, json={"contratadas": datos.contratadas})
    except InstanciaInalcanzable as exc:
        raise HTTPException(502, str(exc))
    except RespuestaDeInstancia as exc:
        if _sin_soporte(exc):
            raise HTTPException(409, _SIN_SOPORTE)
        raise HTTPException(exc.status_code, exc.detalle)
    return _abono_de(instancia, plan, contratadas=respuesta.get("contratadas"), activas=respuesta.get("activas"))
