"""
Lo que un backoffice de producto le abre a la consola de revendedores.

**Lo mínimo:** listar las instancias y suspenderlas o activarlas. El resto de la API del backoffice sigue pidiendo la
sesión del superadmin. Sin `CONSOLA_TOKEN` estas rutas dan 404: un backoffice sin configurar queda como estaba.
"""
import hmac
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .instancias import _obtener, _servicios


def _token_de_consola(request: Request, x_consola_token: str = Header("")) -> None:
    settings = request.app.state.settings
    # La consola misma tiene token, pero no es a quien se le pide: no tiene instancias.
    if not settings.consola_token or settings.tiene("revendedores"):
        raise HTTPException(status_code=404, detail="Not Found")
    if not hmac.compare_digest(x_consola_token.encode("utf-8"), settings.consola_token.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Token de consola inválido.")


router = APIRouter(prefix="/api/consola", tags=["consola"], dependencies=[Depends(_token_de_consola)])


class EstadoDeConsolaIn(BaseModel):
    accion: Literal["suspender", "activar"]
    mensaje: str = Field("", max_length=500)


def _vista(instancia) -> dict:
    return {
        "slug": instancia.slug, "nombre": instancia.nombre, "domain": instancia.domain, "plan": instancia.plan,
        "estado": instancia.estado, "servicio_estado": instancia.servicio_estado,
    }


@router.get("/instancias")
def listar(request: Request):
    return {"instancias": [_vista(i) for i in request.app.state.inventario.listar()]}


@router.post("/instancias/{slug}/estado")
def cambiar_estado(slug: str, datos: EstadoDeConsolaIn, request: Request):
    servicios = _servicios(request)
    _obtener(request, slug)
    try:
        servicios.accion_estado(slug, datos.accion, mensaje=datos.mensaje)
    except servicios.ServiceError as exc:
        raise HTTPException(422, str(exc))
    return _vista(_obtener(request, slug))
