"""
Factory del backoffice compartido de la familia Libra.

**Una imagen, seis contenedores.** No hay un módulo por producto: `create_app`
lee el entorno (ver `settings.py`), enciende las features declaradas y monta el
frontend ya construido. Lo que cambia entre el backoffice de Gestiolibra y el
de Contalibra es un `.env`.

**Es un control plane, no un cliente de bases de datos.** El inventario y el
ciclo de vida de las instancias salen del host (filesystem + Docker); la
configuración de cada instancia se resuelve hablándole por HTTP. Esa separación
es lo que hace posible administrar N instancias desde un solo proceso — ver
`cliente_instancia.py`.

Qué sale de dónde:

- `AdminAuth` (sesión del superadmin) — `libraauth.admin_auth`, sin cambios.
- Token de servicio contra las instancias — `libraauth v0.7.0`.
- Inventario y ciclo de vida — `libracore.admin.services`.
- Cabeceras de seguridad — `libracore.security_headers`.
"""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from libraauth.admin_auth import AdminAuth
from libracore.security_headers import SecurityHeadersMiddleware

from .cliente_instancia import ClienteInstancia
from .inventario import construir_inventario
from .routers import auth, config_instancia, instancias, salud
from .settings import Settings, cargar_settings

# Fallback de desarrollo para el `SECRET_KEY` de la cookie. `_resolve_secret_key`
# de libraauth sólo lo acepta con `ENV=development`, así que un despliegue real
# sin secreto no levanta — que es lo que se quiere.
_DEV_SECRET = "libra-backoffice-dev-secret-no-usar-en-produccion"


def create_app(
    settings: Settings | None = None,
    frontend_dist: str | None = None,
    inventario=None,
) -> FastAPI:
    """`inventario` se puede inyectar; en producción lo arma `construir_inventario`."""
    settings = settings or cargar_settings()

    app = FastAPI(title=f"{settings.product_name} — Backoffice", docs_url=None, redoc_url=None)
    app.add_middleware(SecurityHeadersMiddleware)

    app.state.settings = settings
    app.state.admin_auth = AdminAuth(dev_secret_fallback=_DEV_SECRET)
    app.state.inventario = inventario if inventario is not None else construir_inventario(settings)
    app.state.cliente_instancia = ClienteInstancia(
        token=settings.service_token,
        puerto=settings.instancia_puerto,
        timeout=settings.timeout_instancia,
    )

    @app.get("/health", include_in_schema=False)
    def health():
        """Sin auth: la usan el healthcheck de Docker y el proxy."""
        return {"ok": True, "producto": settings.product_slug}

    app.include_router(auth.router)
    app.include_router(instancias.router)
    app.include_router(config_instancia.router_smtp)
    app.include_router(config_instancia.router_usuarios)
    app.include_router(config_instancia.router_demos)
    app.include_router(salud.router)

    _montar_frontend(app, frontend_dist)
    return app


def _montar_frontend(app: FastAPI, frontend_dist: str | None) -> None:
    """Sirve la SPA construida, con fallback a `index.html`.

    El fallback es lo que hace que recargar el navegador en una ruta interna no
    dé 404: el ruteo lo resuelve React y el servidor devuelve siempre el mismo
    HTML.
    """
    dist = Path(frontend_dist or os.environ.get("FRONTEND_DIST", "/opt/frontend-dist"))
    index = dist / "index.html"
    if not index.exists():
        # En desarrollo el frontend lo sirve Vite en otro puerto. Levantar sin
        # estáticos es legítimo; fallar acá rompería la suite de tests.
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{ruta:path}", include_in_schema=False)
    def spa(ruta: str):
        archivo = dist / ruta
        if ruta and archivo.is_file():
            return FileResponse(archivo)
        return FileResponse(index)
