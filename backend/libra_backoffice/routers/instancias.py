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
from pydantic import BaseModel

from ..deps import admin_actual, requiere_feature
from ..inventario import InstanciaDesconocida

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
    try:
        return servicios.crear_cliente(**datos.model_dump())
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
