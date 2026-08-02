"""
Configuración **de una instancia**: correo saliente y usuarios.

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
