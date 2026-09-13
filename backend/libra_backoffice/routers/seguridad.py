"""
Doble factor (TOTP) del superadmin, enrolable en runtime (F3, 2026-09-13).

`AdminAuth.iniciar_totp` / `confirmar_totp` / `desactivar_totp` (libraauth,
ver `admin_auth.py`) hacen todo el trabajo real — generar el secreto, guardarlo
en `totp.json`, validar el código y persistir el paso usado. Este router sólo
traduce eso a HTTP:

- `TotpNoEnrolable` → 409, con el motivo traducido a un mensaje para el
  superadmin (`_detalle_no_enrolable`). El texto de la excepción es interno
  (piensa en el nombre de la variable de entorno); el que ve la pantalla no.
- `RuntimeError` → 500: la escritura o la relectura del archivo no coincidió
  con lo que se pidió guardar.
- Antes de validar un código (`confirmar`/`desactivar`), el mismo rate
  limiting del login (`rate_limit_excedido` / `registrar_intento_fallido` de
  `AdminAuth`, por IP vía `ip_del_request`). Sin esto, una sesión de
  backoffice robada podría probar códigos sin límite: la cookie ya prueba
  quién es, pero no que tenga el teléfono.

Todos los endpoints exigen sesión (`admin_actual`, 401 sin ella) — es la
sesión del backoffice editando SU PROPIO segundo factor, no un flujo público
como el login.
"""
import segno
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from libraauth.admin_auth import TotpNoEnrolable
from libraauth.auth_events import ip_del_request
from pydantic import BaseModel

from ..deps import admin_actual

router = APIRouter(
    prefix="/api/seguridad", tags=["seguridad"], dependencies=[Depends(admin_actual)]
)

#: Cada desafío/secreto sirve una vez o es sensible: nunca cachear estas
#: respuestas (mismo criterio que `GET /api/captcha` en `routers/auth.py`).
NO_STORE = "no-store"

#: El mismo mensaje que el 429 del login (`routers/auth.py`): es el mismo
#: rate limiting por IP, así que es la misma frase.
DEMASIADOS_INTENTOS = "Demasiados intentos fallidos. Probá de nuevo en unos minutos."


class TotpEstadoOut(BaseModel):
    activo: bool
    origen: str | None
    enrolable: bool


class TotpIniciadoOut(BaseModel):
    secreto: str
    uri: str
    qr: str


class CodigoIn(BaseModel):
    codigo: str = ""


class TotpActivoOut(BaseModel):
    activo: bool


def _detalle_no_enrolable(exc: TotpNoEnrolable) -> str:
    """Traduce el motivo de `TotpNoEnrolable` (pensado para leerse en un log)
    a un mensaje para el superadmin que ve la pantalla. Los cuatro `if`
    corresponden uno a uno a los cuatro mensajes de `_exigir_enrolable` /
    `iniciar_totp` en `libraauth.admin_auth` — si esos textos cambian, este
    `str(exc)` de más abajo es el fallback y no un 500 sin explicación."""
    texto = str(exc)
    if "esta seteado" in texto:
        return "El doble factor lo maneja la configuración del servidor."
    if "no hay ruta de archivo" in texto:
        return "Este backoffice no tiene dónde guardar el secreto."
    if "ya hay un segundo factor activo" in texto:
        return "Ya hay un doble factor activo: desactivalo primero."
    if "esta roto" in texto:
        return "El archivo del doble factor está dañado: hay que borrarlo desde el servidor."
    return texto


@router.get("/totp", response_model=TotpEstadoOut)
def estado_totp(request: Request, response: Response):
    response.headers["Cache-Control"] = NO_STORE
    auth = request.app.state.admin_auth
    return {
        "activo": auth.totp_habilitado,
        "origen": auth.totp_origen,
        "enrolable": auth.totp_enrolable,
    }


@router.post("/totp/iniciar", response_model=TotpIniciadoOut)
def iniciar_totp(request: Request, response: Response):
    """Sin cuerpo: el secreto lo genera el backend. `cuenta` es el slug del
    producto, para que el autenticador muestre "Libra Backoffice:<slug>" y no
    algo genérico si el superadmin tiene más de un backoffice enrolado."""
    response.headers["Cache-Control"] = NO_STORE
    auth = request.app.state.admin_auth
    slug = request.app.state.settings.product_slug
    try:
        iniciado = auth.iniciar_totp(slug)
    except TotpNoEnrolable as exc:
        raise HTTPException(409, _detalle_no_enrolable(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from None
    # `error="m"` (15% de corrección) es el default recomendado por segno para
    # un QR chico como este; sirve tanto en pantalla como impreso.
    qr = segno.make(iniciado["uri"], error="m").svg_data_uri(scale=6, border=2)
    return {"secreto": iniciado["secreto"], "uri": iniciado["uri"], "qr": qr}


@router.post("/totp/confirmar", response_model=TotpActivoOut)
def confirmar_totp(datos: CodigoIn, request: Request):
    auth = request.app.state.admin_auth
    ip = ip_del_request(request)
    if auth.rate_limit_excedido(ip):
        raise HTTPException(429, DEMASIADOS_INTENTOS)
    try:
        confirmado = auth.confirmar_totp(datos.codigo)
    except TotpNoEnrolable as exc:
        raise HTTPException(409, _detalle_no_enrolable(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from None
    if not confirmado:
        auth.registrar_intento_fallido(ip)
        raise HTTPException(400, "Código incorrecto o vencido.")
    return {"activo": True}


@router.post("/totp/desactivar", response_model=TotpActivoOut)
def desactivar_totp(datos: CodigoIn, request: Request):
    auth = request.app.state.admin_auth
    ip = ip_del_request(request)
    if auth.rate_limit_excedido(ip):
        raise HTTPException(429, DEMASIADOS_INTENTOS)
    try:
        desactivado = auth.desactivar_totp(datos.codigo)
    except TotpNoEnrolable as exc:
        raise HTTPException(409, _detalle_no_enrolable(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from None
    if not desactivado:
        auth.registrar_intento_fallido(ip)
        raise HTTPException(400, "Código incorrecto.")
    return {"activo": False}
