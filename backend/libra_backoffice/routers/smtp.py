"""
Configuración del correo saliente de la instancia del producto.

**Por qué no se monta `libraauth.session_auth.build_smtp_settings_router()`
directamente**, que es el router que ya usan los 4 productos: ese exige rol
`admin` vía `json_api_require_admin`, o sea una sesión de `SessionAuth` contra
la tabla `usuarios` del producto. Acá el que está logueado es el superadmin del
backoffice (`AdminAuth`), que no es un usuario del producto y no tiene fila en
esa tabla. Lo que sí se reusa —y es lo que importa— es
`SmtpSettingsRepository`: el cifrado, la precedencia base-sobre-entorno y la
semántica de `SIN_CAMBIOS` salen del motor, no se reescriben.

La forma de la respuesta es la de `estado()`, que es exactamente el
`EstadoSmtp` que espera `ConfiguracionSmtp` de libra-ui v0.10.0.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from libraauth.crypto import ClaveDeCifradoAusente
from libraauth.smtp_settings import SIN_CAMBIOS
from pydantic import BaseModel

from ..deps import admin_actual, requiere_feature

router = APIRouter(
    prefix="/api/smtp",
    tags=["smtp"],
    dependencies=[Depends(requiere_feature("smtp")), Depends(admin_actual)],
)


class SmtpIn(BaseModel):
    host: str = ""
    port: int = 587
    user: str = ""
    # `password` ausente = dejarla como está; `null` o `""` = borrarla; un
    # string = reemplazarla. La distinción es por PRESENCIA de la clave, no por
    # su valor — ver `cuerpoAGuardar` en el componente de libra-ui, que arma el
    # cuerpo respetando esto. Un `password: ""` mandado por costumbre borraría
    # en silencio la contraseña guardada cada vez que alguien edita el remitente.
    password: str | None = None
    from_email: str = ""
    from_name: str = ""


@router.get("")
def leer(request: Request):
    return request.app.state.smtp_settings.estado()


@router.put("")
def guardar(datos: SmtpIn, request: Request):
    repo = request.app.state.smtp_settings
    if "password" in datos.model_fields_set:
        password = datos.password if datos.password is not None else ""
    else:
        password = SIN_CAMBIOS
    try:
        repo.save(
            host=datos.host, port=datos.port, user=datos.user, password=password,
            from_email=datos.from_email, from_name=datos.from_name,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except ClaveDeCifradoAusente as exc:
        # 500 y no 422: no falló el formulario, le falta el secreto al
        # despliegue. Y no se guarda nada — antes que persistir la contraseña
        # en claro, falla.
        raise HTTPException(500, str(exc))
    return repo.estado()


@router.delete("")
def borrar(request: Request):
    """Vuelve a la configuración del entorno de la instancia."""
    repo = request.app.state.smtp_settings
    repo.delete()
    return repo.estado()
