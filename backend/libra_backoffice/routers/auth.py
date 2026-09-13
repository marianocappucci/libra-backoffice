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

Desde la F4 (2026-09-13, libraauth v0.42.0) el login con segundo factor se
hace en **dos pasos**, y son dos endpoints:

- **Paso 1 — `POST /api/login`** (este mismo, sin cambios en la forma de la
  request). Con `codigo` en el cuerpo se comporta exactamente como antes: es
  el camino de un solo paso, y sigue siendo válido (`check_credentials`, un
  solo 401 para clave o código). Sin `codigo`:
  - sin segundo factor, es el login de siempre: `200` + cookie, o `401`.
  - con segundo factor, valida SÓLO la clave (`verificar_clave`) y, si es
    correcta, contesta `200` **sin cookie** con
    `{"requiere_codigo": true, "desafio": "..."}` — el desafío que el paso 2
    necesita. Clave incorrecta: `401` de siempre, y cuenta como intento
    fallido igual que cualquier otro.
- **Paso 2 — `POST /api/login/codigo`** `{desafio, codigo}`, sin sesión, con
  el mismo rate limiting y el mismo 429 que el paso 1. Verifica el desafío
  (`validar_desafio_totp`) y el código (`verificar_codigo_totp`) contra el
  TOTP activo; si los dos valen, recién ahí pone la cookie de sesión.

🔴 **Consecuencia asumida (ADR-016 de libraauth): con 2FA encendido, el paso 1
le confirma a quien prueba contraseñas que la clave es correcta** — antes,
con el camino de un paso, clave y código mal daban el mismo 401 y no se podía
distinguir cuál de los dos falló. Se mitiga con lo que ya protegía el login
entero: el captcha (ADR-014) encarece cada contraseña probada, el bloqueo por
IP (ADR-009) sigue cortando antes de agotar los cinco intentos, y una sesión
de verdad exige además el código — superar el paso 1 no abre nada por sí
solo. El desafío no sirve como cookie de sesión (ni al revés): están firmados
con salts distintos.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from libraauth.auth_events import ip_del_request
from libraauth.session_auth import CAPTCHA_INVALIDO
from pydantic import BaseModel

from ..deps import admin_actual

router = APIRouter(prefix="/api", tags=["auth"])

#: Mismo mensaje en el paso 1 y el paso 2: los dos son la misma IP contra el
#: mismo rate limiting de `AdminAuth`.
DEMASIADOS_INTENTOS = "Demasiados intentos fallidos. Probá de nuevo en unos minutos."


class Credenciales(BaseModel):
    username: str = ""
    password: str = ""
    # El código del autenticador. Vacío cuando el backoffice no tiene segundo
    # factor, o cuando el login en dos pasos todavía no llegó al paso 2; ahí
    # se ignora.
    codigo: str = ""
    # La solución del desafío de `GET /api/captcha`, la que arma el widget.
    captcha: str = ""


class DesafioCodigo(BaseModel):
    """El cuerpo del paso 2: el desafío que devolvió el paso 1 y el código del
    autenticador. Sin sesión, como el login — quien llama todavía no tiene
    cookie."""
    desafio: str = ""
    codigo: str = ""


class UsuarioOut(BaseModel):
    username: str


class RequiereCodigoOut(BaseModel):
    """La respuesta del paso 1 cuando hay segundo factor: `200` sin cookie,
    con el desafío que el paso 2 necesita."""
    requiere_codigo: bool = True
    desafio: str


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


@router.post("/login", response_model=None)
def login(datos: Credenciales, request: Request, response: Response) -> UsuarioOut | RequiereCodigoOut:
    """Paso 1 del login (o el login entero, en el camino de un solo paso).

    Con `codigo` no vacío no cambia nada: es `check_credentials` de siempre,
    para el backoffice que todavía manda los tres datos juntos. Sin `codigo`
    y sin segundo factor tampoco cambia. Sin `codigo` y CON segundo factor,
    valida sólo la clave y devuelve el desafío del paso 2 en vez de loguear
    — ver el docstring del módulo."""
    auth = request.app.state.admin_auth
    ip = ip_del_request(request)
    if auth.rate_limit_excedido(ip):
        raise HTTPException(429, DEMASIADOS_INTENTOS)
    # El captcha va DESPUÉS del bloqueo —una IP bloqueada recibe 429 con o sin
    # captcha— y ANTES de la credencial: cada contraseña probada cuesta un
    # desafío resuelto. Si falta o no vale no se anota como intento fallido: no
    # se llegó a probar ninguna contraseña, y contarlo dejaría bloquear gratis
    # una IP compartida.
    if not request.app.state.captcha.verificar(datos.captcha):
        raise HTTPException(400, CAPTCHA_INVALIDO)
    if datos.codigo or not auth.totp_habilitado:
        # Camino de un paso: con código (ya sea porque el cliente lo mandó de
        # entrada, o porque no hay segundo factor y el campo se ignora).
        if not auth.check_credentials(datos.username, datos.password, codigo=datos.codigo):
            auth.registrar_intento_fallido(ip)
            raise HTTPException(
                401,
                "Usuario, contraseña o código incorrectos."
                if auth.totp_habilitado else "Usuario o contraseña incorrectos.",
            )
        auth.create_session_cookie(response, datos.username)
        return UsuarioOut(username=datos.username)
    # Hay segundo factor y no vino código todavía: sólo el paso 1.
    if not auth.verificar_clave(datos.username, datos.password):
        auth.registrar_intento_fallido(ip)
        raise HTTPException(401, "Usuario o contraseña incorrectos.")
    response.headers["Cache-Control"] = "no-store"
    return RequiereCodigoOut(desafio=auth.emitir_desafio_totp(datos.username))


@router.post("/login/codigo", response_model=UsuarioOut)
def login_codigo(datos: DesafioCodigo, request: Request, response: Response):
    """Paso 2 del login en dos pasos: el desafío del paso 1 más el código del
    autenticador. Sin sesión, con el mismo rate limiting por IP que el paso 1
    — cada intento acá cuenta igual que uno de usuario/contraseña."""
    auth = request.app.state.admin_auth
    ip = ip_del_request(request)
    if auth.rate_limit_excedido(ip):
        raise HTTPException(429, DEMASIADOS_INTENTOS)
    username = auth.validar_desafio_totp(datos.desafio)
    if username is None:
        auth.registrar_intento_fallido(ip)
        raise HTTPException(401, "El código venció: volvé a ingresar.")
    if not auth.verificar_codigo_totp(datos.codigo):
        auth.registrar_intento_fallido(ip)
        raise HTTPException(401, "Código incorrecto.")
    response.headers["Cache-Control"] = "no-store"
    auth.create_session_cookie(response, username)
    return {"username": username}


@router.post("/logout")
def logout(request: Request, response: Response):
    request.app.state.admin_auth.clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UsuarioOut)
def me(username: str = Depends(admin_actual)):
    return {"username": username}
