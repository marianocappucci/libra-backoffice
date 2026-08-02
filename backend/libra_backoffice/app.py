"""
Factory del backoffice compartido de la familia Libra.

**Una imagen, seis contenedores.** No hay un módulo por producto: `create_app`
lee el entorno (ver `settings.py`), enciende las features que ese producto
tiene declaradas y monta el frontend ya construido. Lo que cambia entre el
backoffice de Gestiolibra y el de Contalibra es un `.env`.

Qué sale de dónde:

- `AdminAuth` (sesión del superadmin) — `libraauth.admin_auth`, sin cambios.
- Config SMTP cifrada — `libraauth.smtp_settings.SmtpSettingsRepository`.
- ABM de usuarios — `libraauth.repository.UserRepository`.
- Gestión de instancias — `libracore.admin.services`.
- Cabeceras de seguridad — `libracore.security_headers`.
"""
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from libraauth.admin_auth import AdminAuth
from libraauth.repository import UserRepository
from libraauth.smtp_settings import SmtpSettingsRepository
from libracore.security_headers import SecurityHeadersMiddleware
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from .routers import auth, clientes, salud, smtp, usuarios
from .settings import Settings, cargar_settings

# Fallback de desarrollo para el `SECRET_KEY` de la cookie. `_resolve_secret_key`
# de libraauth sólo lo acepta con `ENV=development`, así que un despliegue real
# sin secreto no levanta — que es lo que se quiere.
_DEV_SECRET = "libra-backoffice-dev-secret-no-usar-en-produccion"


def create_app(settings: Settings | None = None, frontend_dist: str | None = None) -> FastAPI:
    settings = settings or cargar_settings()

    app = FastAPI(title=f"{settings.product_name} — Backoffice", docs_url=None, redoc_url=None)
    app.add_middleware(SecurityHeadersMiddleware)

    app.state.settings = settings
    app.state.admin_auth = AdminAuth(dev_secret_fallback=_DEV_SECRET)

    # Base de la instancia del producto. **No se hace `create_all`**: el schema
    # lo owna el producto, y crear tablas desde acá enmascararía el caso real de
    # apuntar a una base equivocada o a una instancia que nunca arrancó. Si
    # falta, el handler de `OperationalError` de más abajo lo dice con todas las
    # letras en vez de tirar un 500 pelado.
    if settings.auth_db_path is not None:
        engine = create_engine(
            f"sqlite:///{settings.auth_db_path}", connect_args={"check_same_thread": False}
        )
        sesiones = sessionmaker(bind=engine)
        app.state.smtp_settings = SmtpSettingsRepository(sesiones)
        app.state.usuarios = UserRepository(sesiones)

    if settings.tiene("clientes"):
        from libracore.admin import services

        services.configure(repo_root=settings.repo_root, db_filename=settings.db_filename)

    @app.exception_handler(OperationalError)
    def _base_no_disponible(request: Request, exc: OperationalError):
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "No se puede leer la base de la instancia "
                    f"({settings.auth_db_path}). Suele ser que el contenedor del "
                    "producto todavía no arrancó nunca, o que AUTH_DB_PATH apunta "
                    "a un archivo que no es el de esta instancia."
                )
            },
        )

    @app.get("/health", include_in_schema=False)
    def health():
        """Sin auth: la usan el healthcheck de Docker y el proxy."""
        return {"ok": True, "producto": settings.product_slug}

    app.include_router(auth.router)
    app.include_router(smtp.router)
    app.include_router(usuarios.router)
    app.include_router(salud.router)
    app.include_router(clientes.router)

    _montar_frontend(app, frontend_dist)
    return app


def _montar_frontend(app: FastAPI, frontend_dist: str | None) -> None:
    """Sirve la SPA construida, con fallback a `index.html`.

    El fallback es lo que hace que recargar el navegador en `/smtp` no dé 404:
    el ruteo lo resuelve React, el servidor sólo tiene que devolver el mismo
    HTML para cualquier ruta que no sea un archivo ni la API.
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
