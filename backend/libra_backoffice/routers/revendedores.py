"""
La consola de revendedores (feature `revendedores`): quiénes son, qué productos venden, qué instancias son suyas, y el
bloqueo. Diseño en el wiki: `consola-de-revendedores-diseno`.

La marca, los planes y el alta siguen en el backoffice de cada producto: acá no se duplican.

🔴 **Desbloquear reactiva sólo lo que suspendió la consola.** Una instancia que ya estaba suspendida (por falta de
pago, por ejemplo) no se anota en `suspendidas`, y por eso no vuelve. Bloquear y desbloquear son reintentables: si un
backoffice no contesta se informa, y repetir sigue desde donde quedó.

Un solo `asyncio.Lock` ordena todo lo que escribe: bloquear espera a los backoffices entre leer y guardar, y dos
pedidos cruzados perderían lo que anotó el otro.
"""
import asyncio
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..almacen_revendedores import AlmacenIlegible
from ..cliente_consola import BackofficeInalcanzable
from ..deps import admin_actual, requiere_feature

router = APIRouter(
    prefix="/api/revendedores",
    tags=["revendedores"],
    dependencies=[Depends(requiere_feature("revendedores")), Depends(admin_actual)],
)

MAXIMO_DE_HISTORIAL = 200
_cerrojo = asyncio.Lock()


class RevendedorIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    contacto: str = Field("", max_length=200)
    notas: str = Field("", max_length=2000)
    productos: list[str] = Field(default_factory=list, max_length=20)


class InstanciaIn(BaseModel):
    producto: str = Field(min_length=1, max_length=50)
    slug: str = Field(min_length=1, max_length=100)


class BloqueoIn(BaseModel):
    # Pide el nombre escrito: esto les corta el servicio a clientes reales.
    confirmar: str = Field(max_length=120)
    mensaje: str = Field(min_length=1, max_length=500)


def _leer(request: Request) -> list[dict]:
    try:
        return request.app.state.almacen_revendedores.leer()
    except AlmacenIlegible as exc:
        raise HTTPException(503, str(exc))


def _buscar(revendedores: list[dict], identificador: str) -> dict:
    for revendedor in revendedores:
        if revendedor["id"] == identificador:
            return revendedor
    raise HTTPException(404, "No hay ningún revendedor con ese identificador.")


def _ahora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _anotar(revendedor: dict, quien: str, accion: str, detalle: str = "") -> None:
    revendedor["historial"] = [
        {"cuando": _ahora(), "quien": quien, "accion": accion, "detalle": detalle},
        *revendedor["historial"],
    ][:MAXIMO_DE_HISTORIAL]


def _validar_productos(request: Request, productos: list[str]) -> list[str]:
    consola = request.app.state.cliente_consola
    desconocidos = [p for p in productos if not consola.conoce(p)]
    if desconocidos:
        raise HTTPException(422, f"Productos desconocidos: {', '.join(desconocidos)}.")
    return sorted(set(productos))


def _misma(a: dict, b: dict) -> bool:
    return a["producto"] == b["producto"] and a["slug"] == b["slug"]


async def _estados(request: Request, productos: set[str]) -> dict[str, dict[str, str] | str]:
    """Por producto, `{slug: servicio_estado}`; o el motivo, si ese backoffice no contestó."""
    consola = request.app.state.cliente_consola

    async def uno(producto: str):
        try:
            return producto, {i["slug"]: i["servicio_estado"] for i in await consola.instancias(producto)}
        except BackofficeInalcanzable as exc:
            return producto, exc.detalle

    return dict(await asyncio.gather(*(uno(p) for p in sorted(productos))))


async def _intentar(paso: Callable[[], Awaitable[None]]) -> str | None:
    """`None` si salió; si no, el motivo."""
    try:
        await paso()
    except BackofficeInalcanzable as exc:
        return exc.detalle
    return None


@router.get("")
def listar(request: Request):
    return {"revendedores": _leer(request)}


@router.get("/catalogo")
async def catalogo(request: Request):
    """Los productos que conoce la consola con sus instancias y de quién es cada una. Un backoffice caído no tira la
    pantalla: figura como que no contestó."""
    consola = request.app.state.cliente_consola
    revendedores = _leer(request)
    duenos = {(i["producto"], i["slug"]): r["nombre"] for r in revendedores for i in r["instancias"]}

    async def uno(producto):
        try:
            instancias = await consola.instancias(producto.slug)
        except BackofficeInalcanzable as exc:
            return {"slug": producto.slug, "nombre": producto.nombre, "alcanzable": False, "detalle": exc.detalle,
                    "instancias": []}
        return {
            "slug": producto.slug, "nombre": producto.nombre, "alcanzable": True, "detalle": "",
            "instancias": [{**i, "revendedor": duenos.get((producto.slug, i["slug"]), "")} for i in instancias],
        }

    return {"productos": await asyncio.gather(*(uno(p) for p in consola.productos))}


@router.post("", status_code=201)
async def crear(datos: RevendedorIn, request: Request, admin: str = Depends(admin_actual)):
    productos = _validar_productos(request, datos.productos)
    async with _cerrojo:
        revendedores = _leer(request)
        nuevo = {
            "id": secrets.token_hex(6), "nombre": datos.nombre.strip(), "contacto": datos.contacto.strip(),
            "notas": datos.notas, "productos": productos, "instancias": [], "suspendidas": [],
            "estado": "activo", "mensaje": "", "historial": [], "creado": _ahora(),
        }
        _anotar(nuevo, admin, "alta")
        request.app.state.almacen_revendedores.guardar([*revendedores, nuevo])
    return nuevo


@router.get("/{identificador}")
def detalle(identificador: str, request: Request):
    return _buscar(_leer(request), identificador)


@router.put("/{identificador}")
async def editar(identificador: str, datos: RevendedorIn, request: Request, admin: str = Depends(admin_actual)):
    productos = _validar_productos(request, datos.productos)
    async with _cerrojo:
        revendedores = _leer(request)
        revendedor = _buscar(revendedores, identificador)
        con_instancias = sorted({i["producto"] for i in revendedor["instancias"]} - set(productos))
        if con_instancias:
            raise HTTPException(409, f"Tiene instancias de {', '.join(con_instancias)}: hay que quitarlas primero.")
        revendedor.update(nombre=datos.nombre.strip(), contacto=datos.contacto.strip(), notas=datos.notas,
                          productos=productos)
        _anotar(revendedor, admin, "edición", f"productos: {', '.join(productos) or 'ninguno'}")
        request.app.state.almacen_revendedores.guardar(revendedores)
    return revendedor


@router.post("/{identificador}/instancias")
async def asignar(identificador: str, datos: InstanciaIn, request: Request, admin: str = Depends(admin_actual)):
    async with _cerrojo:
        revendedores = _leer(request)
        revendedor = _buscar(revendedores, identificador)
        if revendedor["estado"] == "bloqueado":
            raise HTTPException(409, "Está bloqueado: una instancia nueva quedaría sin suspender.")
        if datos.producto not in revendedor["productos"]:
            raise HTTPException(409, f"No tiene habilitado {datos.producto}.")
        pedida = datos.model_dump()
        for otro in revendedores:
            if any(_misma(i, pedida) for i in otro["instancias"]):
                raise HTTPException(409, f"Esa instancia ya es de {otro['nombre']}.")
        estados = (await _estados(request, {datos.producto}))[datos.producto]
        if isinstance(estados, str):
            raise HTTPException(502, f"El backoffice de {datos.producto} {estados}.")
        if datos.slug not in estados:
            raise HTTPException(404, f"{datos.producto} no tiene ninguna instancia '{datos.slug}'.")
        revendedor["instancias"].append(pedida)
        _anotar(revendedor, admin, "instancia asignada", f"{datos.producto}/{datos.slug}")
        request.app.state.almacen_revendedores.guardar(revendedores)
    return revendedor


@router.delete("/{identificador}/instancias/{producto}/{slug}")
async def quitar(identificador: str, producto: str, slug: str, request: Request, admin: str = Depends(admin_actual)):
    pedida = {"producto": producto, "slug": slug}
    async with _cerrojo:
        revendedores = _leer(request)
        revendedor = _buscar(revendedores, identificador)
        if not any(_misma(i, pedida) for i in revendedor["instancias"]):
            raise HTTPException(404, "Esa instancia no es de este revendedor.")
        if any(_misma(i, pedida) for i in revendedor["suspendidas"]):
            raise HTTPException(409, "La suspendió la consola: quitarla la dejaría suspendida sin que nadie lo recuerde.")
        revendedor["instancias"] = [i for i in revendedor["instancias"] if not _misma(i, pedida)]
        _anotar(revendedor, admin, "instancia quitada", f"{producto}/{slug}")
        request.app.state.almacen_revendedores.guardar(revendedores)
    return revendedor


@router.post("/{identificador}/bloquear")
async def bloquear(identificador: str, datos: BloqueoIn, request: Request, admin: str = Depends(admin_actual)):
    consola = request.app.state.cliente_consola
    async with _cerrojo:
        revendedores = _leer(request)
        revendedor = _buscar(revendedores, identificador)
        if datos.confirmar.strip() != revendedor["nombre"]:
            raise HTTPException(422, "Para bloquearlo hay que escribir el nombre del revendedor.")
        estados = await _estados(request, {i["producto"] for i in revendedor["instancias"]})
        resultados = []
        for instancia in revendedor["instancias"]:
            producto, slug = instancia["producto"], instancia["slug"]
            de_producto = estados[producto]
            fila = {"producto": producto, "slug": slug, "resultado": "suspendida", "detalle": ""}
            resultados.append(fila)
            if isinstance(de_producto, str):
                fila.update(resultado="fallo", detalle=de_producto)
            elif any(_misma(s, instancia) for s in revendedor["suspendidas"]):
                # Un reintento: se la vuelve a mandar con el mensaje de ahora, y ya está anotada.
                motivo = await _intentar(lambda: consola.cambiar_estado(producto, slug, "suspender", datos.mensaje))
                if motivo:
                    fila.update(resultado="fallo", detalle=motivo)
            elif de_producto.get(slug) == "suspendido":
                # Ya estaba cortada por otra razón: no se anota, y por eso desbloquear no la devuelve.
                fila.update(resultado="ya_estaba_suspendida")
            else:
                motivo = await _intentar(lambda: consola.cambiar_estado(producto, slug, "suspender", datos.mensaje))
                if motivo:
                    fila.update(resultado="fallo", detalle=motivo)
                else:
                    revendedor["suspendidas"].append(dict(instancia))
                    # Se guarda en cada paso: si el proceso se cae a mitad, no se pierde qué se suspendió.
                    request.app.state.almacen_revendedores.guardar(revendedores)
        revendedor.update(estado="bloqueado", mensaje=datos.mensaje)
        fallidas = sum(1 for f in resultados if f["resultado"] == "fallo")
        _anotar(revendedor, admin, "bloqueo", f"{len(resultados)} instancias, {fallidas} con error. {datos.mensaje}")
        request.app.state.almacen_revendedores.guardar(revendedores)
    return {"revendedor": revendedor, "resultados": resultados}


@router.post("/{identificador}/desbloquear")
async def desbloquear(identificador: str, request: Request, admin: str = Depends(admin_actual)):
    consola = request.app.state.cliente_consola
    async with _cerrojo:
        revendedores = _leer(request)
        revendedor = _buscar(revendedores, identificador)
        resultados = []
        for instancia in list(revendedor["suspendidas"]):
            producto, slug = instancia["producto"], instancia["slug"]
            motivo = await _intentar(lambda: consola.cambiar_estado(producto, slug, "activar"))
            if motivo:
                resultados.append({"producto": producto, "slug": slug, "resultado": "fallo", "detalle": motivo})
            else:
                resultados.append({"producto": producto, "slug": slug, "resultado": "activada", "detalle": ""})
                revendedor["suspendidas"] = [s for s in revendedor["suspendidas"] if not _misma(s, instancia)]
                request.app.state.almacen_revendedores.guardar(revendedores)
        for instancia in revendedor["instancias"]:
            if not any(f["producto"] == instancia["producto"] and f["slug"] == instancia["slug"] for f in resultados):
                resultados.append({**instancia, "resultado": "sin_cambios", "detalle": ""})
        fallidas = sum(1 for f in resultados if f["resultado"] == "fallo")
        if not revendedor["suspendidas"]:
            revendedor.update(estado="activo", mensaje="")
        _anotar(revendedor, admin, "desbloqueo", f"{len(resultados)} instancias, {fallidas} con error.")
        request.app.state.almacen_revendedores.guardar(revendedores)
    return {"revendedor": revendedor, "resultados": resultados}
