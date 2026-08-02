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
        # `esperar_json=False`: acá sólo importa el código de estado, y el
        # /health de los productos no siempre devuelve JSON.
        await cliente.pedir("GET", instancia, health_path, esperar_json=False)
    except InstanciaInalcanzable as exc:
        return {**base, "estado": "inalcanzable", "detalle": exc.detalle}
    except RespuestaDeInstancia as exc:
        return {**base, "estado": "error", "detalle": f"HTTP {exc.status_code}"}
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
