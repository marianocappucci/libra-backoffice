"""
Salud del despliegue: qué versión está corriendo el backoffice y si la
instancia del producto contesta.

Chico a propósito. La pregunta que resuelve es la que se hace un humano
después de un deploy —"¿esto que estoy mirando es el código nuevo, y el
producto está vivo?"— y esa pregunta ya se contestó mal varias veces en esta
familia mirando un `curl` que devolvía 200 contra un proceso que no se había
reiniciado.
"""
import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Request

from ..deps import admin_actual, requiere_feature

router = APIRouter(
    prefix="/api/salud",
    tags=["salud"],
    dependencies=[Depends(requiere_feature("salud")), Depends(admin_actual)],
)

# Momento de arranque del proceso. Es el dato que delata un servicio que
# "responde 200" pero nunca se reinició después del último deploy.
_ARRANQUE = time.time()


@router.get("")
async def salud(request: Request):
    settings = request.app.state.settings
    producto = {"url": settings.product_health_url, "estado": "no configurado", "detalle": ""}

    if settings.product_health_url:
        try:
            async with httpx.AsyncClient(timeout=5) as cliente:
                resp = await cliente.get(settings.product_health_url)
            producto["estado"] = "ok" if resp.status_code == 200 else "error"
            producto["detalle"] = f"HTTP {resp.status_code}"
        except Exception as exc:
            producto["estado"] = "inalcanzable"
            producto["detalle"] = f"{type(exc).__name__}: {exc}"

    return {
        "producto": {"slug": settings.product_slug, "nombre": settings.product_name},
        "features": sorted(settings.features),
        "backoffice": {
            "version": os.environ.get("APP_VERSION", "desconocida"),
            "commit": os.environ.get("APP_COMMIT", "desconocido"),
            "arrancado": datetime.fromtimestamp(_ARRANQUE, timezone.utc).isoformat(),
            "uptime_segundos": int(time.time() - _ARRANQUE),
        },
        "instancia": producto,
    }
