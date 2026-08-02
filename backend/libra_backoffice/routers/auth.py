"""
Login del backoffice, en JSON.

Reusa `AdminAuth` de libraauth entero —credenciales por entorno, cookie propia
`cladmin_session`, rate limiting en memoria— y sólo cambia la forma de la
respuesta: `200`/`401` con cuerpo JSON en vez del `303` a `/login` que
esperaba la versión Jinja2.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..deps import admin_actual

router = APIRouter(prefix="/api", tags=["auth"])


class Credenciales(BaseModel):
    username: str = ""
    password: str = ""


class UsuarioOut(BaseModel):
    username: str


def _ip(request: Request) -> str:
    # Detrás de NPM el `client.host` es el del proxy, así que el
    # `x-forwarded-for` es el único valor que distingue a un atacante de otro.
    return request.headers.get("x-forwarded-for", request.client.host if request.client else "")


@router.post("/login", response_model=UsuarioOut)
def login(datos: Credenciales, request: Request, response: Response):
    auth = request.app.state.admin_auth
    ip = _ip(request)
    if auth.rate_limit_excedido(ip):
        raise HTTPException(429, "Demasiados intentos fallidos. Probá de nuevo en unos minutos.")
    if not auth.check_credentials(datos.username, datos.password):
        auth.registrar_intento_fallido(ip)
        raise HTTPException(401, "Usuario o contraseña incorrectos.")
    auth.create_session_cookie(response, datos.username)
    return {"username": datos.username}


@router.post("/logout")
def logout(request: Request, response: Response):
    request.app.state.admin_auth.clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UsuarioOut)
def me(username: str = Depends(admin_actual)):
    return {"username": username}
