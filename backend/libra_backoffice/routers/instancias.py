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
    setup_npm: bool = True


class InstanciaEdit(BaseModel):
    nombre: str
    domain: str = ""


class PlanIn(BaseModel):
    plan: str


class EstadoIn(BaseModel):
    accion: str


class BajaIn(BaseModel):
    # Se pide repetir el slug. No es ceremonia: la baja borra el contenedor, su
    # volumen y el directorio de datos de un cliente real.
    confirmar_slug: str
    hacer_backup: bool = True


@router.get("/instancias")
def listar(request: Request):
    return {"instancias": [i.dict() for i in _inventario(request).listar()]}


@router.get("/instancias/{slug}")
def detalle(slug: str, request: Request):
    return _obtener(request, slug).dict()


@router.post("/instancias", status_code=201)
def crear(datos: InstanciaIn, request: Request):
    servicios = _servicios(request)
    try:
        return servicios.crear_cliente(**datos.model_dump())
    except servicios.ServiceError as exc:
        raise HTTPException(422, str(exc))


@router.put("/instancias/{slug}")
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


@router.post("/instancias/{slug}/estado")
def cambiar_estado(slug: str, datos: EstadoIn, request: Request):
    servicios = _servicios(request)
    try:
        servicios.accion_estado(slug, datos.accion)
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


@router.delete("/instancias/{slug}")
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
