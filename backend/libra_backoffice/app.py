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
- Captcha del login — `libraauth.captcha` (v0.40.0).
- Token de servicio contra las instancias — `libraauth v0.7.0`.
- Inventario y ciclo de vida — `libracore.admin.services`.
- Cabeceras de seguridad — `libracore.security_headers`.
"""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from libraauth.admin_auth import AdminAuth
from libraauth.captcha import Captcha
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
    # El captcha del login. **Uno por proceso** y no uno por request: la lista
    # de desafíos ya usados vive adentro, y dos la partirían en dos — un desafío
    # resuelto serviría una vez en cada una. Alcanza porque el contenedor corre
    # un solo uvicorn (el CMD del Dockerfile no pasa `--workers`); con varios
    # habría que mover esa lista a algo compartido. Las claves salen del mismo
    # `SECRET_KEY` que la cookie, por HKDF y con un `info` propio.
    app.state.captcha = Captcha(app.state.admin_auth.secret_key)
    app.state.inventario = inventario if inventario is not None else construir_inventario(settings)
    app.state.cliente_instancia = ClienteInstancia(
        token=settings.service_token,
        puerto=settings.instancia_puerto,
        timeout=settings.timeout_instancia,
    )

    @app.get("/health", include_in_schema=False)
    def health():
        """Sin auth: la usan el healthcheck de Docker y el proxy.

        🔴 **Toca el camino de los scripts a proposito.** Devolver `{"ok": true}`
        con mirar solo el proceso es lo que hizo que tres caidas del panel
        —`backup_zip` el 2026-08-12, `migraciones` el 2026-08-24— pasaran con
        el contenedor en `healthy`: el import de `panel_admin.py` es diferido,
        asi que el proceso levanta perfecto y revienta recien en el primer
        request. Ver `verificar_scripts()` en `inventario.py`.

        El 503 es deliberado y no un 200 con un campo de estado: lo que lee
        Docker es el codigo, y un panel que no puede importar los scripts de su
        producto no puede listar, dar de alta ni administrar usuarios. No queda
        nada que servir.
        """
        try:
            app.state.inventario.verificar_scripts()
        except Exception as exc:
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "producto": settings.product_slug,
                    "error": f"{type(exc).__name__}: {exc}",
                    "detalle": (
                        "No se pudieron importar los scripts del producto desde "
                        f"{settings.repo_root}. Suele ser el pin de libracore de "
                        "este contenedor contra un `configure()` mas nuevo en el "
                        "repo del producto — ver backend/pyproject.toml."
                    ),
                },
            )
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

    app.mount("/assets", AssetsInmutables(directory=dist / "assets"), name="assets")

    @app.get("/{ruta:path}", include_in_schema=False)
    def spa(ruta: str):
        archivo = dist / ruta
        if ruta and archivo.is_file():
            # Los sueltos del dist (favicon, manifest) tampoco llevan hash en
            # el nombre: mismo criterio que el index.
            return FileResponse(archivo, headers={"Cache-Control": SIN_CACHE})
        return FileResponse(index, headers={"Cache-Control": SIN_CACHE})


#: El estándar de la familia (`estandares-desarrollo`, «Cabeceras de caché del
#: frontend»). El `index.html` es el único archivo del build que conserva el
#: nombre y el que dice cuál es el bundle de ahora: sin cabecera, el navegador
#: aplica caché heurística y después de un deploy sigue pidiendo el bundle
#: viejo —que existe y viene con 200—, así que no se ve el cambio y no falla
#: nada en ninguna capa. Medido acá el 2026-09-12.
#:
#: `no-cache` **no** es "no guardes": es "guardá, pero revalidá siempre". Ojo:
#: `FileResponse` manda `ETag` pero no atiende pedidos condicionales, así que
#: la revalidación trae el index completo (unos cientos de bytes).
SIN_CACHE = "no-cache, must-revalidate"

#: Los assets, al revés: el nombre lleva el hash del contenido y nunca cambia
#: de contenido. Cachearlos para siempre es seguro **porque** el index
#: revalida: cuando el contenido cambia, cambia el nombre.
PARA_SIEMPRE = "public, max-age=31536000, immutable"


class AssetsInmutables(StaticFiles):
    """`StaticFiles` con la cabecera de caché larga."""

    def file_response(self, *args, **kwargs):
        respuesta = super().file_response(*args, **kwargs)
        respuesta.headers["Cache-Control"] = PARA_SIEMPRE
        return respuesta
