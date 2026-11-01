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
- Token de servicio contra las instancias — `libraauth v0.7.0`; uno por
  instancia desde libracore v1.183.0 (ADR-071), ver `cliente_instancia.py`.
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
from libracore.docs_api import cerrar_docs_de_la_api
from libracore.errores import instalar_registro_de_errores
from libracore.security_headers import CSP_SPA, SecurityHeadersMiddleware
from libracore.spa import archivo_publico

from .cliente_instancia import ClienteInstancia
from .inventario import construir_inventario
from .almacen_revendedores import AlmacenDeRevendedores
from .cliente_consola import ClienteConsola
from .routers import apariencia, auth, config_instancia, consola, instancias, marca, revendedores, salud, seguridad
from .settings import Settings, cargar_settings
from .tema_suite import AlmacenDeTema

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

    app = FastAPI(title=f"{settings.product_name} — Backoffice")
    # `/docs`, `/redoc` y `/openapi.json` sólo en desarrollo (ADR-053 de libracore). Antes se apagaban `/docs` y `/redoc` con
    # `docs_url=None`, pero faltaba `openapi_url`: `/openapi.json` publicaba, sin sesión, el mapa de todas las rutas del backoffice
    # —y las tres rutas apagadas caían en el fallback de la SPA, que contesta `index.html` con 200—. Acá dan 404.
    cerrar_docs_de_la_api(app)
    # `CSP_SPA` y no la CSP por defecto: esa es la de las apps Jinja2, y le
    # habilita a esta SPA `'unsafe-inline'` en `script-src` y `cdn.jsdelivr.net`,
    # que no usa. Vite emite el JS como archivos del propio origen, y el worker
    # del captcha (libra-ui) también: sale de `/assets/`, no de `blob:`. Es la
    # misma política que los ocho productos desde libracore v1.89.0.
    app.add_middleware(SecurityHeadersMiddleware, csp=CSP_SPA)
    # El registro de errores de la familia (ADR-045 de libracore): un 500 deja una linea JSON en
    # `$LIBRA_ERRORES_DIR/errores.jsonl` con un `ref` que el usuario puede dictar, y se monta
    # `POST /api/errores-cliente` para los errores del navegador. Al construir la app, antes del primer pedido.
    # `LIBRA_INSTANCIA` (el contenedor, p. ej. `gestiolibra-admin`) distingue a los ocho backoffices entre si.
    instalar_registro_de_errores(app, "libra-backoffice")

    app.state.settings = settings
    app.state.admin_auth = AdminAuth(dev_secret_fallback=_DEV_SECRET)
    # El captcha del login. **Uno por proceso** y no uno por request: la lista
    # de desafíos ya usados vive adentro, y dos la partirían en dos — un desafío
    # resuelto serviría una vez en cada una. Alcanza porque el contenedor corre
    # un solo uvicorn (el CMD del Dockerfile pasa `--workers ${WEB_CONCURRENCY:-1}`,
    # o sea 1). 🔴 Con varios la lista se partiría por proceso: un desafío resuelto
    # serviría una vez por worker. Este backoffice NO tiene base propia donde
    # ponerla (`UsadosEnBase` de libraauth v0.50.0, ADR-023, la necesita), así que
    # antes de subir `WEB_CONCURRENCY` hay que darle una (ver "Varios procesos" en
    # el README); el estado del login, en cambio, ya es seguro entre procesos con
    # `ADMIN_PANEL_ESTADO_PATH`. Las claves salen del mismo `SECRET_KEY` que la
    # cookie, por HKDF y con un `info` propio.
    app.state.captcha = Captcha(app.state.admin_auth.secret_key)
    app.state.inventario = inventario if inventario is not None else construir_inventario(settings)
    # El tema de la suite (feature `apariencia`): la fuente de verdad vive acá y se empuja a las instancias.
    app.state.almacen_tema = AlmacenDeTema(settings.tema_path)
    # El token de cada instancia sale de su compose en cada request (ADR-071 de libracore); el global
    # (`LIBRA_SERVICE_TOKEN` del backoffice) queda de respaldo. Un inventario inyectado sin
    # `token_de_servicio` (los tests) usa sólo el global; el anterior es el primer respaldo ante un 401.
    app.state.cliente_instancia = ClienteInstancia(
        token=settings.service_token,
        token_de_instancia=getattr(app.state.inventario, "token_de_servicio", None),
        anterior_de_instancia=getattr(app.state.inventario, "token_anterior_de_servicio", None),
        puerto=settings.instancia_puerto,
        timeout=settings.timeout_instancia,
    )

    # La consola de revendedores (feature `revendedores`): de quién es cada instancia, y el corte del servicio. Le habla
    # a los backoffices porque un proceso no puede atender a varios productos (`revendedores.py`).
    app.state.almacen_revendedores = AlmacenDeRevendedores(settings.revendedores_path)
    app.state.cliente_consola = ClienteConsola(
        settings.consola_productos, settings.consola_token, timeout=settings.timeout_instancia)

    @app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
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
    app.include_router(seguridad.router)
    app.include_router(instancias.router)
    app.include_router(config_instancia.router_smtp)
    app.include_router(config_instancia.router_usuarios)
    app.include_router(config_instancia.router_demos)
    app.include_router(config_instancia.router_reenvio_correo)
    app.include_router(apariencia.router)
    app.include_router(marca.router)
    app.include_router(salud.router)
    app.include_router(consola.router)
    app.include_router(revendedores.router)

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

    # HEAD además de GET: un monitor que hace `curl -I` no puede recibir 405.
    @app.api_route("/{ruta:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(ruta: str):
        # 🔴 `archivo_publico` (libracore.spa) y no `dist / ruta`: ese `ruta` es
        # lo que el cliente mandó, con sus `..` y hasta con una barra inicial
        # (`//etc/hostname` → `dist / "/etc/hostname"` es `/etc/hostname`). Sin
        # resolverlo y verificar que quede adentro de `dist`, el fallback
        # servía cualquier archivo del contenedor, `/proc/self/environ`
        # incluido. Medido el 2026-10-18 desde adentro del VPS.
        archivo = archivo_publico(dist, ruta)
        if archivo is not None:
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
