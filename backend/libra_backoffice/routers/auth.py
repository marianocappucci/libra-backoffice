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

Y desde la F2.6 (2026-09-11, libraauth v0.39.0 y v0.40.0), dos más, éstas
**sin opción**:

- 🔴 **La IP del bloqueo sale de `ip_del_request`.** Hasta acá la clave era el
  `X-Forwarded-For` **entero**, y NPM no lo reemplaza: le agrega la IP real al
  final. Lo de la izquierda lo escribe el cliente, así que cada request con un
  header distinto contaba como otra IP y rotarlo esquivaba el bloqueo.
  `ip_del_request` lo lee desde la derecha, y sólo si el par directo es un
  proxy de confianza (ADR-013 de libraauth).
- **Captcha ALTCHA, siempre** (ADR-014 de libraauth). `GET /api/captcha` emite
  el desafío y el login exige la solución en `captcha`. Va siempre y no recién
  después de N fallos: lo decidió el humano. El desafío se emite y se verifica
  en este mismo proceso, sin proveedor externo.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from libraauth.auth_events import ip_del_request
from libraauth.session_auth import CAPTCHA_INVALIDO
from pydantic import BaseModel

from ..deps import admin_actual

router = APIRouter(prefix="/api", tags=["auth"])


class Credenciales(BaseModel):
    username: str = ""
    password: str = ""
    # El código del autenticador. Vacío cuando el backoffice no tiene segundo
    # factor; ahí se ignora.
    codigo: str = ""
    # La solución del desafío de `GET /api/captcha`, la que arma el widget.
    captcha: str = ""


class UsuarioOut(BaseModel):
    username: str


class OpcionesLogin(BaseModel):
    totp: bool


@router.get("/login/opciones", response_model=OpcionesLogin)
def opciones_login(request: Request):
    """Sin auth: la pantalla de login lo consulta antes de dibujarse, para
    saber si mostrar el campo del código. Decir que hay segundo factor no
    regala nada — quien pruebe contraseñas lo descubre en el primer intento."""
    return {"totp": request.app.state.admin_auth.totp_habilitado}


@router.get("/captcha")
def captcha_desafio(request: Request, response: Response):
    """El desafío ALTCHA que resuelve el navegador antes de loguear. Sin auth,
    como el login.

    `no-store` porque cada desafío sirve una sola vez: uno cacheado por un
    proxy sería el mismo para todos, y el primero que lo usara se lo gastaría
    al resto. La pantalla lo usa además como sonda: libra-ui sólo dibuja el
    recuadro si esto contesta con la forma de un desafío.
    """
    response.headers["Cache-Control"] = "no-store"
    return request.app.state.captcha.emitir()


@router.post("/login", response_model=UsuarioOut)
def login(datos: Credenciales, request: Request, response: Response):
    auth = request.app.state.admin_auth
    ip = ip_del_request(request)
    if auth.rate_limit_excedido(ip):
        raise HTTPException(429, "Demasiados intentos fallidos. Probá de nuevo en unos minutos.")
    # El captcha va DESPUÉS del bloqueo —una IP bloqueada recibe 429 con o sin
    # captcha— y ANTES de la credencial: cada contraseña probada cuesta un
    # desafío resuelto. Si falta o no vale no se anota como intento fallido: no
    # se llegó a probar ninguna contraseña, y contarlo dejaría bloquear gratis
    # una IP compartida.
    if not request.app.state.captcha.verificar(datos.captcha):
        raise HTTPException(400, CAPTCHA_INVALIDO)
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
