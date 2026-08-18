"""
Configuración **de una instancia**: correo saliente, usuarios y los códigos de
acceso a su demo.

Todo lo de acá es proxy contra la API de la instancia, nunca acceso a su base.
Ver `cliente_instancia.py` para el porqué; en corto: cada instancia cifra su
contraseña SMTP con una clave derivada de su propio `SECRET_KEY`, y un proceso
no puede sostener N secretos en su entorno.

Las rutas cuelgan de `/api/instancias/{slug}/` y no de `/api/smtp` **a
propósito**: en un producto multi-instancia una pantalla de "correo saliente"
sin instancia es ambigua, y la ambigüedad acá se paga configurándole el
servidor de correo al cliente equivocado.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..cliente_instancia import InstanciaInalcanzable, RespuestaDeInstancia
from ..deps import admin_actual, requiere_feature
from ..inventario import InstanciaDesconocida

# Dos routers y no uno con guardas por ruta: FastAPI evalúa las dependencias
# del router **antes** que las de la ruta, así que con `admin_actual` arriba el
# 401 le ganaría al 404 de feature y una request sin credenciales podría
# deducir qué features tiene habilitadas este producto. Con un router por
# feature, el orden es el mismo que en `instancias.py`: primero la feature.
router_smtp = APIRouter(
    prefix="/api/instancias/{slug}/smtp", tags=["config"],
    dependencies=[Depends(requiere_feature("smtp")), Depends(admin_actual)],
)
router_usuarios = APIRouter(
    prefix="/api/instancias/{slug}/usuarios", tags=["config"],
    dependencies=[Depends(requiere_feature("usuarios")), Depends(admin_actual)],
)
router_demos = APIRouter(
    prefix="/api/instancias/{slug}/demo-codigos", tags=["config"],
    dependencies=[Depends(requiere_feature("demos")), Depends(admin_actual)],
)


class SmtpIn(BaseModel):
    host: str = ""
    port: int = 587
    user: str = ""
    # Ausente = dejarla como está; `null` o `""` = borrarla. La distinción es
    # por PRESENCIA de la clave, y se propaga tal cual a la instancia — ver
    # `cuerpoAGuardar` en el componente de libra-ui.
    password: str | None = None
    from_email: str = ""
    from_name: str = ""


class UsuarioIn(BaseModel):
    username: str
    name: str
    password: str
    role: str = "staff"


class UsuarioUpdate(BaseModel):
    name: str
    role: str
    active: bool


class DemoCodigoIn(BaseModel):
    """Alta de un código de acceso a la demo.

    Los defaults son los del motor y están repetidos acá **a propósito**: es lo
    que se manda si la pantalla no los toca, y dejarlos implícitos haría que un
    cambio de default del motor moviera en silencio lo que emite el
    backoffice.
    """
    etiqueta: str = ""
    dias: int = 7
    usos_max: int = 10


#: Lo que contesta una instancia que **no** es demo. No es un 404: los seis
#: productos sirven su SPA con un fallback, así que una ruta no montada
#: devuelve `200` con el `index.html` —y, medido contra `dev.libradesk.com.ar`
#: el 2026-08-18, con `Content-Type: application/json` encima—. El cliente ya
#: detecta el cuerpo que no es JSON; acá se le da el significado que tiene en
#: **esta** ruta.
NO_ES_UNA_DEMO = (
    "Esta instancia no es una demo: no monta el ABM de códigos de acceso."
)


async def _proxy_demo(request: Request, slug: str, metodo: str, path: str,
                      cuerpo=None):
    """`_proxy`, más la traducción del catch-all.

    Sin esto la pantalla recibe un `200` con `{"detail": "…el cuerpo no es
    JSON…"}` y termina mostrando un error de parseo donde la respuesta correcta
    es "esta instancia no tiene demo".
    """
    try:
        return await _proxy(request, slug, metodo, path, cuerpo)
    except HTTPException as exc:
        # `RespuestaDeInstancia` por cuerpo no-JSON llega acá con el status de
        # la instancia, que en este caso es 200. Un `HTTPException(200)` no es
        # un error para nadie: ni el navegador ni la pantalla lo tratan como
        # tal.
        if exc.status_code == 200 and "no es JSON" in str(exc.detail):
            raise HTTPException(404, NO_ES_UNA_DEMO) from exc
        # Y el 405: el fallback de la SPA sirve GET y nada mas, asi que un POST
        # o un DELETE contra una instancia que no monta el router se estrella
        # ahi. Medido contra dev.libradesk.com.ar. En ESTA ruta un 405 de la
        # instancia no puede significar otra cosa.
        if exc.status_code == 405:
            raise HTTPException(404, NO_ES_UNA_DEMO) from exc
        raise


async def _proxy(request: Request, slug: str, metodo: str, path: str, cuerpo=None):
    try:
        instancia = request.app.state.inventario.obtener(slug)
    except InstanciaDesconocida:
        raise HTTPException(404, f"No hay ninguna instancia '{slug}'.")

    try:
        return await request.app.state.cliente_instancia.pedir(metodo, instancia, path, json=cuerpo)
    except InstanciaInalcanzable as exc:
        # 502 y no 500: el backoffice está bien, la instancia no contesta. La
        # pantalla necesita poder decir cuál y por qué.
        raise HTTPException(502, str(exc))
    except RespuestaDeInstancia as exc:
        # Se propaga el código de la instancia: un 422 suyo tiene que llegar
        # como 422 al formulario, no convertido en un error genérico.
        raise HTTPException(exc.status_code, exc.detalle)


def _cuerpo_smtp(datos: SmtpIn) -> dict:
    """Reenvía sólo los campos que vinieron, para no convertir un 'no toqués la
    contraseña' en un 'borrala' en el camino."""
    return datos.model_dump(include=datos.model_fields_set or None)


# ── SMTP ────────────────────────────────────────────────────────────────────

@router_smtp.get("")
async def leer_smtp(slug: str, request: Request):
    return await _proxy(request, slug, "GET", request.app.state.settings.smtp_path)


@router_smtp.put("")
async def guardar_smtp(slug: str, datos: SmtpIn, request: Request):
    return await _proxy(
        request, slug, "PUT", request.app.state.settings.smtp_path, _cuerpo_smtp(datos)
    )


@router_smtp.delete("")
async def borrar_smtp(slug: str, request: Request):
    return await _proxy(request, slug, "DELETE", request.app.state.settings.smtp_path)


# ── Usuarios ────────────────────────────────────────────────────────────────

@router_usuarios.get("")
async def listar_usuarios(slug: str, request: Request):
    return await _proxy(request, slug, "GET", request.app.state.settings.users_path)


@router_usuarios.post("", status_code=201)
async def crear_usuario(slug: str, datos: UsuarioIn, request: Request):
    return await _proxy(
        request, slug, "POST", request.app.state.settings.users_path, datos.model_dump()
    )


@router_usuarios.put("/{user_id}")
async def editar_usuario(slug: str, user_id: str, datos: UsuarioUpdate, request: Request):
    path = f"{request.app.state.settings.users_path}/{user_id}"
    return await _proxy(request, slug, "PUT", path, datos.model_dump())


# ── Códigos de acceso a la demo ─────────────────────────────────────────────
#
# 🔴 **La instancia es la que sabe si es una demo, no el backoffice.** Estas
# rutas existen para todas y la instancia contesta 404 en las que no montan el
# router — que es lo correcto: el backoffice no tiene forma de saber cuál de
# las N es la demo sin preguntárselo, y guardarlo en su propia config sería un
# segundo lugar donde el dato puede quedar viejo.

@router_demos.get("")
async def listar_codigos(slug: str, request: Request):
    """Los códigos emitidos. **Ninguno trae el código en sí**: el motor guarda
    el sha256 y devuelve sólo el prefijo de 4 caracteres."""
    return await _proxy_demo(
        request, slug, "GET", request.app.state.settings.demo_codigos_path
    )


@router_demos.post("", status_code=201)
async def emitir_codigo(slug: str, datos: DemoCodigoIn, request: Request):
    """Emite un código y lo devuelve **en claro por única vez**.

    La pantalla tiene que mostrarlo en ese momento: no hay forma de
    recuperarlo después, y volver a pedirlo es emitir otro. Es el precio de
    guardar sólo el hash, y se paga a cambio de que un backup de la instancia
    no contenga códigos usables.
    """
    return await _proxy_demo(
        request, slug, "POST", request.app.state.settings.demo_codigos_path,
        datos.model_dump(),
    )


@router_demos.delete("/{codigo_id}")
async def revocar_codigo(slug: str, codigo_id: int, request: Request):
    path = f"{request.app.state.settings.demo_codigos_path}/{codigo_id}"
    return await _proxy_demo(request, slug, "DELETE", path)
