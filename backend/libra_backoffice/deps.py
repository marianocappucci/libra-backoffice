"""
Dependencias compartidas de los routers.

`AdminAuth.require_login` de libraauth existe, pero **no sirve tal cual acá**:
lanza un `307` con `Location: /login`, que es lo correcto para el backoffice
Jinja2 que redirige el navegador y lo equivocado para una SPA, donde el
`fetch` seguiría el redirect y le devolvería HTML al `api-client` de libra-ui.
Este módulo lo envuelve para que la API conteste `401` y el frontend pueda
mandar al login por su cuenta.
"""
from fastapi import HTTPException, Request, Response


def admin_actual(request: Request, response: Response) -> str:
    """El superadmin logueado, o `401`.

    `response` no se usa acá adentro: se le pasa a `current_user` para que
    herede la renovación deslizante de la sesión (8 h sin uso, ADR-017 de
    libraauth v0.43.0). `AdminAuth.current_user` la declara opcional
    justamente para esto — un consumidor que la envuelve en su propia
    dependencia, como este módulo, tiene que agregarle el parámetro a mano
    para heredarla; FastAPI la inyecta sola por `Depends`, la declare o no
    cada endpoint. Sin este parámetro el backoffice loguea a todos afuera a
    las 8 h en punto, las usen o no en el medio."""
    user = request.app.state.admin_auth.current_user(request, response)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado.")
    return user


def requiere_feature(feature: str):
    """Guarda de feature flag.

    Devuelve `404` y no `403` a propósito: en un producto donde la feature no
    está habilitada, el endpoint sencillamente no existe. Un `403` sugeriría
    que existe y que al superadmin le falta permiso, que es otra cosa.
    """

    def _dependencia(request: Request) -> None:
        if not request.app.state.settings.tiene(feature):
            raise HTTPException(status_code=404, detail="Not Found")

    return _dependencia
