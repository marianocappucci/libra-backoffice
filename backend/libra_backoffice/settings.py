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

FEATURES_VALIDAS = frozenset({"instancias", "smtp", "usuarios", "salud"})

# Cómo se enumeran las instancias de este producto.
#   libracore → `clientes/<slug>/cliente.json` + planes, vía
#               `libracore.admin.services`. Lo usan cinco.
#   compose   → sólo `clientes/<slug>/docker-compose.yml`. Lo usa LibraDesk,
#               que despliega con `deploy_cliente.sh` y no tiene ni planes ni
#               `libracore.provisioning`.
BACKENDS_VALIDOS = frozenset({"libracore", "compose"})


class ConfiguracionInvalida(RuntimeError):
    """El entorno no alcanza para levantar el backoffice."""


@dataclass(frozen=True)
class Settings:
    product_slug: str
    product_name: str
    features: frozenset[str]

    # Inventario de instancias.
    instancias_backend: str = "libracore"
    repo_root: Path | None = None
    db_filename: str = ""

    # Cómo se le habla a una instancia. El host es su nombre de contenedor en
    # `stack_stack-net`: el tráfico de control nunca sale a internet.
    instancia_puerto: int = 8000
    smtp_path: str = "/admin/smtp"
    users_path: str = "/users"
    service_token: str = ""
    timeout_instancia: float = 5.0

    extra: dict = field(default_factory=dict)

    def tiene(self, feature: str) -> bool:
        return feature in self.features

    @property
    def features_por_instancia(self) -> list[str]:
        """Las que se resuelven hablándole a una instancia, no al host."""
        return [f for f in ("smtp", "usuarios") if f in self.features]


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

    backend = (env.get("INSTANCIAS_BACKEND") or "libracore").strip()
    if backend not in BACKENDS_VALIDOS:
        raise ConfiguracionInvalida(
            f"INSTANCIAS_BACKEND inválido: {backend!r}. Válidos: {sorted(BACKENDS_VALIDOS)}."
        )

    # El inventario hace falta aunque sólo esté `smtp`: sin lista de instancias
    # no hay a cuál configurarle el correo.
    repo_root_crudo = (env.get("REPO_ROOT") or "").strip()
    if not repo_root_crudo:
        raise ConfiguracionInvalida(
            "Falta REPO_ROOT: el checkout del producto en el host, donde vive `clientes/`."
        )

    db_filename = (env.get("DB_FILENAME") or "").strip()
    if backend == "libracore" and not db_filename:
        raise ConfiguracionInvalida(
            "El backend 'libracore' necesita DB_FILENAME (el nombre del archivo de "
            "base de cada instancia, ej. `contalibra.db`)."
        )

    token = (env.get("LIBRA_SERVICE_TOKEN") or "").strip()
    if features & {"smtp", "usuarios"} and not token:
        raise ConfiguracionInvalida(
            "Las features 'smtp' y 'usuarios' se resuelven hablándole a la API de cada "
            "instancia y necesitan LIBRA_SERVICE_TOKEN — el mismo valor que tienen "
            "seteado las instancias de este producto."
        )

    return Settings(
        product_slug=slug,
        product_name=(env.get("PRODUCT_NAME") or slug.title()).strip(),
        features=features,
        instancias_backend=backend,
        repo_root=Path(repo_root_crudo),
        db_filename=db_filename,
        instancia_puerto=int(env.get("INSTANCIA_PUERTO") or 8000),
        smtp_path=(env.get("SMTP_PATH") or "/admin/smtp").strip(),
        users_path=(env.get("USERS_PATH") or "/users").strip(),
        service_token=token,
        timeout_instancia=float(env.get("TIMEOUT_INSTANCIA") or 5.0),
    )
