"""«Apariencia»: el tema de la suite (los colores), elegido acá y empujado a todas las instancias del producto.

Una suite es un producto: lo que se guarda es UN tema para todas sus instancias (ADR-007 de `libra-ui`). Cada instancia guarda su copia en
su propio `config.json` y la sirve ella misma en `GET /api/tema` (ADR-012 de `libracore`): la SPA lee de su instancia, no de este
plano de control, así que una instancia sigue con sus colores aunque el backoffice esté caído. Este router es el camino por el que el
tema llega a ellas, con el token de servicio, igual que ya pasa con el correo y los usuarios.

## Qué le pasa a cada instancia (`estado` de cada resultado)

- `aplicada`: la instancia aceptó el tema.
- `detenida`: el contenedor no corre; no se intenta (y no se espera un timeout por cada una).
- `inalcanzable`: corre pero no contesta. Es información, no una falla del backoffice.
- `sin_soporte`: contesta, pero todavía no tiene el endpoint (una versión de libracore anterior a `v1.118.0`): hay que actualizarla.
- `rechazada`: la instancia contestó 422 al tema.
- `error`: cualquier otro fallo de la instancia.

El tema se guarda ANTES de empujarlo y un fallo parcial no lo deshace: la fuente de verdad es esta, y «Reaplicar» (o el próximo guardado)
vuelve a intentarlo con las que quedaron atrás.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..cliente_instancia import InstanciaInalcanzable, RespuestaDeInstancia
from ..deps import admin_actual, requiere_feature
from ..tema_suite import TemaInvalido, validar_forma

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/apariencia",
    tags=["apariencia"],
    dependencies=[Depends(requiere_feature("apariencia")), Depends(admin_actual)],
)

#: Cuántas instancias se atienden a la vez: alcanza para decenas sin abrir un abanico de conexiones contra el host.
SIMULTANEAS = 8

_SIN_SOPORTE = (
    "La instancia todavía no tiene el endpoint del tema (libracore anterior a v1.118.0): hay que actualizarla."
)


class TemaIn(BaseModel):
    tema: dict[str, str]


def _almacen(request: Request):
    return request.app.state.almacen_tema


def _sin_soporte(exc: RespuestaDeInstancia) -> bool:
    # 404/405: la ruta no existe (el fallback de la SPA sólo sirve GET). "no es JSON": el fallback contestó 200 con HTML.
    return exc.status_code in (404, 405) or "no es JSON" in exc.detalle


def _resultado(i, estado: str, detalle: str = "") -> dict:
    return {"slug": i.slug, "nombre": i.nombre or i.slug, "estado": estado, "detalle": detalle}


async def _una(request: Request, i, metodo: str, cuerpo, comparar_con: dict | None = None) -> dict:
    """Le habla a UNA instancia y traduce el resultado. Nunca lanza: una caída no puede tumbar a las demás."""
    if i.estado != "running":
        return _resultado(i, "detenida", "El contenedor no está corriendo.")
    path = request.app.state.settings.tema_instancia_path
    try:
        respuesta = await request.app.state.cliente_instancia.pedir(metodo, i, path, json=cuerpo)
    except InstanciaInalcanzable as exc:
        return _resultado(i, "inalcanzable", exc.detalle)
    except RespuestaDeInstancia as exc:
        if _sin_soporte(exc):
            return _resultado(i, "sin_soporte", _SIN_SOPORTE)
        return _resultado(i, "rechazada" if exc.status_code == 422 else "error", exc.detalle)
    except Exception as exc:  # pragma: no cover - defensivo: ninguna instancia puede tumbar el recorrido
        logger.warning("Tema: falló %s de forma inesperada", i.slug, exc_info=True)
        return _resultado(i, "error", f"{type(exc).__name__}: {exc}")
    if comparar_con is None:
        return _resultado(i, "aplicada")
    de_la_instancia = respuesta.get("tema") if isinstance(respuesta, dict) else None
    return _resultado(i, "al_dia" if de_la_instancia == comparar_con else "desfasada")


async def _en_todas(request: Request, instancias: list, metodo: str, cuerpo, comparar_con=None) -> list[dict]:
    cupo = asyncio.Semaphore(SIMULTANEAS)

    async def con_cupo(i):
        async with cupo:
            return await _una(request, i, metodo, cuerpo, comparar_con)

    return list(await asyncio.gather(*(con_cupo(i) for i in instancias)))


async def empujar_tema(request: Request, tema: dict[str, str], instancias: list | None = None) -> list[dict]:
    """Empuja el tema a las instancias (por defecto, todas las del producto). Un resultado por instancia, en el orden del inventario."""
    todas = request.app.state.inventario.listar() if instancias is None else instancias
    return await _en_todas(request, todas, "PUT", {"tema": tema})


@router.get("")
def leer(request: Request):
    return {"tema": _almacen(request).leer()}


@router.put("")
async def guardar(datos: TemaIn, request: Request):
    try:
        tema = validar_forma(datos.tema)
    except TemaInvalido as exc:
        raise HTTPException(422, str(exc))
    _almacen(request).guardar(tema)
    return {"tema": tema, "resultados": await empujar_tema(request, tema)}


@router.post("/aplicar")
async def reaplicar(request: Request):
    """Vuelve a empujar el tema guardado a todas: el botón para las que quedaron atrás."""
    tema = _almacen(request).leer()
    return {"tema": tema, "resultados": await empujar_tema(request, tema)}


@router.get("/estado")
async def estado(request: Request):
    """Para cada instancia: ¿tiene el tema de la suite? (`al_dia` / `desfasada` / o por qué no se pudo saber)."""
    tema = _almacen(request).leer()
    todas = request.app.state.inventario.listar()
    return {"tema": tema, "instancias": await _en_todas(request, todas, "GET", None, comparar_con=tema)}


def empujar_a_una_instancia_nueva(request: Request, slug: str) -> None:
    """El alta de una instancia le aplica el tema de la suite. **Mejor esfuerzo y sin ruido**: si la instancia todavía no contesta, el alta
    ya salió bien y la pantalla «Apariencia» la va a mostrar como `desfasada` para reaplicar. Nunca lanza."""
    try:
        if not request.app.state.settings.tiene("apariencia"):
            return
        tema = _almacen(request).leer()
        if not tema:
            return
        instancia = request.app.state.inventario.obtener(slug)
        resultado = asyncio.run(empujar_tema(request, tema, [instancia]))[0]
        if resultado["estado"] != "aplicada":
            logger.info("Tema: la instancia nueva %s quedó %s (%s)", slug, resultado["estado"], resultado["detalle"])
    except Exception:
        logger.warning("Tema: no se pudo aplicar a la instancia nueva %s", slug, exc_info=True)
