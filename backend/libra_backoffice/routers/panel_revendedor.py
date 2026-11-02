"""
Lo que la consola le contesta al panel público del revendedor. Diseño en el wiki: `panel-del-revendedor-diseno`.

🔴 **El permiso se comprueba acá, no en el panel.** El panel está en internet; la consola no. Cada revendedor tiene su propia
credencial (`X-Revendedor-Credencial`, se guarda el sha256) y de ella sale **quién pregunta**: ninguna ruta recibe un
identificador de revendedor, así que no hay nada que adivinar para ver a otro. Una credencial robada expone a ese revendedor
solo, y generar otra la corta.

Fase 1: sólo lectura. Lo que viaja es lo que el revendedor necesita para ver a sus clientes: ni el historial, ni las notas del
dueño, ni el mensaje con que se lo bloqueó. Un backoffice que no contesta no se esconde: sus clientes figuran sin estado.
"""
import asyncio
import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from ..almacen_revendedores import AlmacenIlegible
from ..cliente_consola import BackofficeInalcanzable
from ..deps import requiere_feature


def huella(credencial: str) -> str:
    # Sha256 y no bcrypt: son 256 bits al azar, no una contraseña que alguien eligió, y esto corre en cada pedido.
    return hashlib.sha256(credencial.encode("utf-8")).hexdigest()


def revendedor_de_la_credencial(request: Request, x_revendedor_credencial: str = Header("")) -> dict:
    almacen = request.app.state.almacen_revendedores
    try:
        credenciales, revendedores = almacen.credenciales(), almacen.leer()
    except AlmacenIlegible as exc:
        raise HTTPException(503, "La consola no puede leer sus datos.") from exc
    pedida = huella(x_revendedor_credencial)
    # Se recorren todas sin cortar: que el tiempo no diga cuántas se probaron ni dónde coincidió.
    encontrado = None
    for identificador, guardada in credenciales.items():
        if hmac.compare_digest(pedida, guardada):
            encontrado = identificador
    revendedor = next((r for r in revendedores if r["id"] == encontrado), None)
    if not x_revendedor_credencial or revendedor is None:
        raise HTTPException(401, "Credencial inválida.")
    return revendedor


router = APIRouter(
    prefix="/api/panel-revendedor", tags=["panel-revendedor"], dependencies=[Depends(requiere_feature("revendedores"))]
)


@router.get("/yo")
def yo(request: Request, revendedor: dict = Depends(revendedor_de_la_credencial)):
    consola = request.app.state.cliente_consola
    nombres = {p.slug: p.nombre for p in consola.productos}
    return {
        "nombre": revendedor["nombre"],
        "estado": revendedor["estado"],
        "productos": [{"slug": p, "nombre": nombres.get(p, p)} for p in revendedor["productos"]],
    }


@router.get("/clientes")
async def clientes(request: Request, revendedor: dict = Depends(revendedor_de_la_credencial)):
    consola = request.app.state.cliente_consola
    nombres = {p.slug: p.nombre for p in consola.productos}

    async def uno(producto: str):
        try:
            return producto, {i["slug"]: i for i in await consola.instancias(producto)}
        except BackofficeInalcanzable:
            return producto, None

    por_producto = dict(await asyncio.gather(*(uno(p) for p in sorted({i["producto"] for i in revendedor["instancias"]}))))
    filas = []
    for asignada in revendedor["instancias"]:
        producto, slug = asignada["producto"], asignada["slug"]
        instancias = por_producto[producto]
        instancia = (instancias or {}).get(slug, {})
        filas.append({
            "producto": producto, "producto_nombre": nombres.get(producto, producto), "slug": slug,
            "nombre": instancia.get("nombre") or slug, "domain": instancia.get("domain", ""), "plan": instancia.get("plan", ""),
            # `None`: no se sabe, porque su backoffice no contestó. No es lo mismo que activa.
            "servicio_estado": instancia.get("servicio_estado"),
        })
    return {"clientes": filas}
