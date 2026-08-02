"""
ABM de los usuarios de la instancia del producto.

Reusa `UserRepository` de libraauth —el mismo que usan los productos, sobre la
misma tabla `usuarios` y con el mismo hashing— y expone el contrato que espera
el componente `Usuarios` de libra-ui: `GET` lista, `POST` alta,
`PUT /{id}` edición y baja lógica (`active`).

> ⚠️ **Esto escribe en la base de la instancia del producto.** No hay una tabla
> de usuarios propia del backoffice: el superadmin del backoffice se autentica
> por entorno (`AdminAuth`) y no tiene fila en ningún lado. Lo que se administra
> acá son los usuarios que entran al producto.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from libraauth.repository import UsernameTaken
from pydantic import BaseModel

from ..deps import admin_actual, requiere_feature

router = APIRouter(
    prefix="/api/usuarios",
    tags=["usuarios"],
    dependencies=[Depends(requiere_feature("usuarios")), Depends(admin_actual)],
)


class UsuarioIn(BaseModel):
    username: str
    name: str
    password: str
    role: str = "staff"


class UsuarioUpdate(BaseModel):
    name: str
    role: str
    active: bool


@router.get("")
def listar(request: Request):
    return request.app.state.usuarios.list()


@router.post("", status_code=201)
def crear(datos: UsuarioIn, request: Request):
    try:
        return request.app.state.usuarios.create(
            username=datos.username, name=datos.name,
            password=datos.password, role=datos.role,
        )
    except UsernameTaken:
        raise HTTPException(409, f"Ya existe un usuario '{datos.username}'.")
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.put("/{user_id}")
def editar(user_id: str, datos: UsuarioUpdate, request: Request):
    try:
        return request.app.state.usuarios.update(
            user_id, name=datos.name, role=datos.role, active=datos.active,
        )
    except KeyError:
        raise HTTPException(404, "Usuario no encontrado.")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
