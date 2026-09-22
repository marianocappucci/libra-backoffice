"""
Configuración del backoffice, toda por entorno.

**Una imagen, seis despliegues.** El repo produce un único artefacto; lo que
distingue al backoffice de Gestiolibra del de Contalibra es su `.env`. De ahí
que acá no haya ninguna rama por producto: hay un slug, un nombre para mostrar,
un conjunto de features y las rutas de la API de sus instancias.

> **Por qué las rutas son configurables.** Los seis productos no montan sus APIs
> igual: el router de SMTP de libraauth cuelga de `/admin/smtp` en cuatro y de
> `/api/config/smtp` en Contalibra y Restolibra, que escribieron el suyo; el de
> usuarios **no es de libraauth** —cada producto tiene el propio— y está en
> `/users` en cuatro y en `/api/usuarios` en LibraDesk. Es la misma razón por la
> que los componentes `Usuarios` y `ConfiguracionSmtp` de libra-ui tienen una
> prop `basePath`.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

FEATURES_VALIDAS = frozenset(
    {"instancias", "smtp", "usuarios", "salud", "demos", "reenvio-correo"}
)

#: Mismo vocabulario que ya tenía el `Select` de rol de `Usuarios` de
#: libra-ui antes de la prop `roles` (ver `Settings.usuarios_roles`) — para
#: no cambiarle nada a un producto que no setee `USERS_ROLES`.
ROLES_POR_DEFECTO: tuple[str, ...] = ("staff", "admin")


class ConfiguracionInvalida(RuntimeError):
    """El entorno no alcanza para levantar el backoffice."""


@dataclass(frozen=True)
class Settings:
    product_slug: str
    product_name: str
    features: frozenset[str]

    # Inventario de instancias.
    repo_root: Path | None = None
    db_filename: str = ""

    # Cómo se le habla a una instancia. El host es su nombre de contenedor en
    # `stack_stack-net`: el tráfico de control nunca sale a internet.
    instancia_puerto: int = 8000
    smtp_path: str = "/admin/smtp"
    users_path: str = "/users"
    # LibraDesk sirve su health en `/api/health`. Con el default, el chequeo de
    # salud caía en el fallback de la SPA y devolvía 200 con HTML: un "ok" que
    # no había tocado la app.
    health_path: str = "/health"
    # Los codigos de acceso a la demo publica (libraauth v0.26.0). La ruta la
    # monta **solo la instancia demo**, asi que en cualquier otra este proxy
    # recibe un 404 de la instancia — que es la respuesta correcta y la que la
    # pantalla traduce a "esta instancia no es una demo".
    demo_codigos_path: str = "/admin/demo-codigos"
    # El "correo de reenvío" que el cliente carga en SU panel (piloto:
    # Contalibra, endpoint propio del producto — no es de libraauth, igual que
    # `users_path`).
    reenvio_correo_path: str = "/api/config/reenvio-correo"
    service_token: str = ""
    timeout_instancia: float = 5.0
    # Vocabulario de roles de ESTE producto — no es el mismo en toda la
    # familia (`("admin", "staff")` en seis, `("admin", "operador", "cajero")`
    # en Contalibra, con `"mozo"` sumado en Restolibra — ver el docstring de
    # `libraauth.usuarios.build_users_router`). Sólo alimenta la pantalla
    # (el `Select` de rol de `Usuarios` de libra-ui, vía `/api/salud`); la
    # instancia sigue siendo quien valida el rol de verdad.
    usuarios_roles: tuple[str, ...] = ROLES_POR_DEFECTO

    extra: dict = field(default_factory=dict)

    def tiene(self, feature: str) -> bool:
        return feature in self.features

    @property
    def features_por_instancia(self) -> list[str]:
        """Las que se resuelven hablándole a una instancia, no al host."""
        return [
            f for f in ("smtp", "usuarios", "demos", "reenvio-correo")
            if f in self.features
        ]

    @property
    def roles_para_frontend(self) -> list[dict]:
        """`usuarios_roles` en la forma `Rol[]` que espera `Usuarios` de
        libra-ui (`{value, label}`). La etiqueta se deriva del valor —ningún
        producto de la familia pidió hoy una etiqueta distinta al nombre del
        rol capitalizado— así que `USERS_ROLES` no necesita una sintaxis con
        etiqueta propia."""
        return [{"value": r, "label": r.capitalize()} for r in self.usuarios_roles]


def _leer_roles(crudo: str) -> tuple[str, ...]:
    """`USERS_ROLES=admin,operador,cajero` → `("admin", "operador", "cajero")`.

    Sin la variable (o vacía), `ROLES_POR_DEFECTO`. Formato simple a
    propósito: sin etiqueta explícita — `roles_para_frontend` deriva la
    etiqueta del valor, y ningún producto de la familia necesita hoy una
    distinta.
    """
    roles = tuple(r.strip() for r in crudo.split(",") if r.strip())
    return roles or ROLES_POR_DEFECTO


def _leer_features(crudo: str) -> frozenset[str]:
    features = {f.strip() for f in crudo.split(",") if f.strip()}
    desconocidas = features - FEATURES_VALIDAS
    if desconocidas:
        raise ConfiguracionInvalida(
            f"FEATURES tiene valores desconocidos: {sorted(desconocidas)}. "
            f"Válidas: {sorted(FEATURES_VALIDAS)}."
        )
    if not features:
        raise ConfiguracionInvalida("FEATURES está vacío: el backoffice no tendría ninguna pantalla.")
    return frozenset(features)


def cargar_settings(env: dict | None = None) -> Settings:
    """Arma los settings desde el entorno y **falla al arrancar** si falta algo.

    Fallar acá y no en la primera request es deliberado: un backoffice que
    levanta y recién revienta cuando alguien abre una pantalla es un despliegue
    que parece exitoso.
    """
    env = os.environ if env is None else env

    slug = (env.get("PRODUCT_SLUG") or "").strip()
    if not slug:
        raise ConfiguracionInvalida("Falta PRODUCT_SLUG.")

    features = _leer_features(env.get("FEATURES", ""))

    # El inventario hace falta aunque sólo esté `smtp`: sin lista de instancias
    # no hay a cuál configurarle el correo.
    repo_root_crudo = (env.get("REPO_ROOT") or "").strip()
    if not repo_root_crudo:
        raise ConfiguracionInvalida(
            "Falta REPO_ROOT: el checkout del producto en el host, donde vive `clientes/`."
        )

    db_filename = (env.get("DB_FILENAME") or "").strip()
    if not db_filename:
        raise ConfiguracionInvalida(
            "Falta DB_FILENAME: el nombre del archivo de base de cada instancia "
            "(ej. `contalibra.db`)."
        )

    token = (env.get("LIBRA_SERVICE_TOKEN") or "").strip()
    if features & {"smtp", "usuarios", "demos", "reenvio-correo"} and not token:
        raise ConfiguracionInvalida(
            "Las features 'smtp' y 'usuarios' se resuelven hablándole a la API de cada "
            "instancia y necesitan LIBRA_SERVICE_TOKEN — el mismo valor que tienen "
            "seteado las instancias de este producto."
        )

    return Settings(
        product_slug=slug,
        product_name=(env.get("PRODUCT_NAME") or slug.title()).strip(),
        features=features,
        repo_root=Path(repo_root_crudo),
        db_filename=db_filename,
        instancia_puerto=int(env.get("INSTANCIA_PUERTO") or 8000),
        smtp_path=(env.get("SMTP_PATH") or "/admin/smtp").strip(),
        demo_codigos_path=(
            env.get("DEMO_CODIGOS_PATH") or "/admin/demo-codigos").strip(),
        reenvio_correo_path=(
            env.get("REENVIO_CORREO_PATH") or "/api/config/reenvio-correo").strip(),
        users_path=(env.get("USERS_PATH") or "/users").strip(),
        health_path=(env.get("HEALTH_PATH") or "/health").strip(),
        service_token=token,
        timeout_instancia=float(env.get("TIMEOUT_INSTANCIA") or 5.0),
        usuarios_roles=_leer_roles(env.get("USERS_ROLES", "")),
    )
