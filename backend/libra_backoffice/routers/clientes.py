"""
Gestión de instancias de cliente — sólo Contalibra y Restolibra.

**No reimplementa nada.** Toda la lógica real (Docker, NPM, planes, backup,
baja) vive en `libracore.admin.services`, que a su vez envuelve los scripts
`panel_admin.py` / `nuevo_cliente.py` / `plans.py` del repo de cada producto.
Acá sólo se traduce eso a JSON: la versión Jinja2 de este mismo router
devolvía plantillas, y una SPA necesita datos.

`services.configure(repo_root=..., db_filename=...)` lo llama `create_app`
una sola vez al arrancar; los imports de los scripts del producto son
diferidos dentro de cada función del motor, así que el módulo se puede
importar aunque la feature esté apagada.
"""
from libracore.admin import services
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import admin_actual, requiere_feature

router = APIRouter(
    prefix="/api",
    tags=["clientes"],
    dependencies=[Depends(requiere_feature("clientes")), Depends(admin_actual)],
)


class ClienteIn(BaseModel):
    nombre: str
    slug: str = ""
    domain: str = ""
    port: int = 0
    admin_user: str = "admin"
    admin_password: str = ""
    plan: str = "basico"
    setup_npm: bool = True


class ClienteEdit(BaseModel):
    nombre: str
    domain: str = ""


class PlanIn(BaseModel):
    plan: str


class EstadoIn(BaseModel):
    accion: str


class BajaIn(BaseModel):
    # Se pide repetir el slug para dar de baja. Es la misma confirmación que
    # tenía la versión Jinja2 y no es ceremonia: la baja borra el contenedor,
    # el volumen y el directorio de datos de un cliente real.
    confirmar_slug: str
    hacer_backup: bool = True


@router.get("/clientes")
def listar():
    return services.listar_clientes()


@router.get("/clientes/{slug}")
def detalle(slug: str):
    cliente = services.get_cliente(slug)
    if not cliente:
        raise HTTPException(404, f"Cliente '{slug}' no encontrado.")
    return cliente


@router.post("/clientes", status_code=201)
def crear(datos: ClienteIn):
    try:
        return services.crear_cliente(**datos.model_dump())
    except services.ServiceError as exc:
        raise HTTPException(422, str(exc))


@router.put("/clientes/{slug}")
def editar(slug: str, datos: ClienteEdit):
    try:
        return services.editar_cliente(slug, nombre=datos.nombre, domain=datos.domain)
    except services.ServiceError as exc:
        raise HTTPException(404, str(exc))


@router.put("/clientes/{slug}/plan")
def cambiar_plan(slug: str, datos: PlanIn):
    try:
        services.set_plan(slug, datos.plan)
    except services.ServiceError as exc:
        raise HTTPException(422, str(exc))
    return services.get_cliente(slug)


@router.post("/clientes/{slug}/estado")
def cambiar_estado(slug: str, datos: EstadoIn):
    try:
        services.accion_estado(slug, datos.accion)
    except services.ServiceError as exc:
        raise HTTPException(422, str(exc))
    return services.get_cliente(slug)


@router.post("/clientes/{slug}/backup")
def backup(slug: str):
    try:
        return {"archivo": services.backup_cliente(slug)}
    except services.ServiceError as exc:
        raise HTTPException(422, str(exc))


@router.delete("/clientes/{slug}")
def baja(slug: str, datos: BajaIn):
    if datos.confirmar_slug != slug:
        raise HTTPException(422, "La confirmación no coincide con el slug del cliente.")
    try:
        return services.eliminar_cliente(slug, hacer_backup=datos.hacer_backup)
    except services.ServiceError as exc:
        raise HTTPException(422, str(exc))


@router.get("/planes")
def planes():
    return services.planes_info()
