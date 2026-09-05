"""
Login del backoffice, en JSON.

Reusa `AdminAuth` de libraauth entero —credenciales por entorno, cookie propia
`cladmin_session`, rate limiting por IP— y sólo cambia la forma de la
respuesta: `200`/`401` con cuerpo JSON en vez del `303` a `/login` que
esperaba la versión Jinja2.

Desde la F2 (2026-09-05, libraauth v0.36.0) hay dos cosas más, las dos
configuradas por entorno y las dos opcionales:

- **Segundo factor TOTP.** Con `ADMIN_PANEL_TOTP_SECRET`, `GET /api/login/opciones`
  contesta `{"totp": true}` y el login exige `codigo`. Clave o código
  incorrectos dan **el mismo 401**: distinguirlos le diría a quien prueba
  contraseñas cuál de las dos acertó.
- **Lockout que sobrevive al reinicio.** Con `ADMIN_PANEL_ESTADO_PATH`, los
  intentos fallidos por IP viven en un archivo (el compose lo monta en un
  volumen) y no en la memoria del proceso.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..deps import admin_actual

router = APIRouter(prefix="/api", tags=["auth"])


class Credenciales(BaseModel):
    username: str = ""
    password: str = ""
    # El código del autenticador. Vacío cuando el backoffice no tiene segundo
    # factor; ahí se ignora.
    codigo: str = ""


class UsuarioOut(BaseModel):
    username: str


class OpcionesLogin(BaseModel):
    totp: bool


def _ip(request: Request) -> str:
    # Detrás de NPM el `client.host` es el del proxy, así que el
    # `x-forwarded-for` es el único valor que distingue a un atacante de otro.
    return request.headers.get("x-forwarded-for", request.client.host if request.client else "")


@router.get("/login/opciones", response_model=OpcionesLogin)
def opciones_login(request: Request):
    """Sin auth: la pantalla de login lo consulta antes de dibujarse, para
    saber si mostrar el campo del código. Decir que hay segundo factor no
    regala nada — quien pruebe contraseñas lo descubre en el primer intento."""
    return {"totp": request.app.state.admin_auth.totp_habilitado}


@router.post("/login", response_model=UsuarioOut)
def login(datos: Credenciales, request: Request, response: Response):
    auth = request.app.state.admin_auth
    ip = _ip(request)
    if auth.rate_limit_excedido(ip):
        raise HTTPException(429, "Demasiados intentos fallidos. Probá de nuevo en unos minutos.")
    if not auth.check_credentials(datos.username, datos.password, codigo=datos.codigo):
        auth.registrar_intento_fallido(ip)
        raise HTTPException(
            401,
            "Usuario, contraseña o código incorrectos."
            if auth.totp_habilitado else "Usuario o contraseña incorrectos.",
        )
    auth.create_session_cookie(response, datos.username)
    return {"username": datos.username}


@router.post("/logout")
def logout(request: Request, response: Response):
    request.app.state.admin_auth.clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UsuarioOut)
def me(username: str = Depends(admin_actual)):
    return {"username": username}
