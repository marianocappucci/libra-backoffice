"""
Salud del despliegue: qué está corriendo el backoffice y cuáles de sus
instancias contestan.

La pregunta que resuelve es la que se hace un humano después de un deploy —"¿lo
que estoy mirando es el código nuevo, y las instancias están vivas?"— y en esta
familia ya se contestó mal varias veces mirando un `curl` que devolvía 200
contra un proceso que nunca se había reiniciado.

Consulta las instancias **en paralelo y con timeout**: con una docena de
clientes, hacerlo en serie convertiría una instancia caída en una pantalla que
tarda un minuto en cargar.

🔴 **Un 200 no alcanza para decir "ok", y por eso el chequeo mira el cuerpo.**
Los seis productos de la familia sirven una SPA con fallback, así que *cualquier*
ruta que no exista devuelve 200 con el `index.html`. Mientras esto pedía sólo el
código de estado (`esperar_json=False`), la pantalla no tenía forma de reportar
una instancia caída: con el frontend horneado en la imagen, el catch-all contesta
200 aunque la API esté muerta. Medido el 2026-08-12 desde adentro de
`libradesk-admin`: una ruta inventada daba 200 con HTML en las tres instancias.

El criterio es el mismo que usa el healthcheck que genera LibraCore: el cuerpo
tiene que parsear como JSON **y** ser un objeto, **sin exigir ninguna clave en
particular**. Las tres formas que la familia devuelve hoy —medidas contra las 18
instancias del VPS el 2026-08-15— pasan igual:

    {"status": "ok"}                                    contalibra, restolibra
    {"ok": true, "product": "gestiolibra"}              gestiolibra, medlibra, ventalibra
    {"status": "ok", "timestamp": "2026-08-15T…"}       libradesk

Pedir una clave concreta habría puesto en rojo a productos sanos, que es el error
opuesto y se nota menos.
"""
import asyncio
import os
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from ..cliente_instancia import InstanciaInalcanzable, RespuestaDeInstancia
from ..deps import admin_actual, requiere_feature

router = APIRouter(
    prefix="/api/salud",
    tags=["salud"],
    dependencies=[Depends(requiere_feature("salud")), Depends(admin_actual)],
)

# Momento de arranque del proceso. Es el dato que delata un servicio que
# "responde 200" pero nunca se reinició después del último deploy.
_ARRANQUE = time.time()


async def _estado_de(cliente, instancia, health_path: str) -> dict:
    base = {"slug": instancia.slug, "nombre": instancia.nombre, "container": instancia.container}
    if not instancia.container:
        return {**base, "estado": "sin contenedor", "detalle": "El compose no declara container_name."}
    try:
        cuerpo = await cliente.pedir("GET", instancia, health_path)
    except InstanciaInalcanzable as exc:
        return {**base, "estado": "inalcanzable", "detalle": exc.detalle}
    except RespuestaDeInstancia as exc:
        # Un 200 con cuerpo que no es JSON llega por acá con el detalle que
        # explica el fallback de la SPA; un 4xx/5xx real, con su código.
        detalle = exc.detalle if exc.status_code < 400 else f"HTTP {exc.status_code}"
        return {**base, "estado": "error", "detalle": detalle}
    if not isinstance(cuerpo, dict):
        return {
            **base,
            "estado": "error",
            "detalle": (
                f"La instancia contestó 200 pero el cuerpo de {health_path!r} no es un "
                f"objeto JSON ({type(cuerpo).__name__}). Un health de esta familia "
                "devuelve siempre un objeto."
            ),
        }
    return {**base, "estado": "ok", "detalle": ""}


@router.get("")
async def salud(request: Request):
    settings = request.app.state.settings
    cliente = request.app.state.cliente_instancia

    instancias = request.app.state.inventario.listar()
    estados = await asyncio.gather(
        *(_estado_de(cliente, i, settings.health_path) for i in instancias)
    )

    return {
        "producto": {"slug": settings.product_slug, "nombre": settings.product_name},
        "features": sorted(settings.features),
        "backoffice": {
            "version": os.environ.get("APP_VERSION", "desconocida"),
            "commit": os.environ.get("APP_COMMIT", "desconocido"),
            "arrancado": datetime.fromtimestamp(_ARRANQUE, timezone.utc).isoformat(),
            "uptime_segundos": int(time.time() - _ARRANQUE),
        },
        "instancias": list(estados),
    }
