"""
Configuración del backoffice, toda por entorno.

**Una imagen, seis despliegues.** El repo produce un único artefacto; lo que
distingue al backoffice de Gestiolibra del de Contalibra es su `.env`, no su
código. De ahí que acá no haya ninguna rama por producto: hay un slug, un
nombre para mostrar y un conjunto de features habilitadas.

> ⚠️ **`LIBRAAUTH_ENCRYPTION_KEY` tiene que valer lo mismo que el `SECRET_KEY`
> de la instancia del producto.** La contraseña SMTP se guarda cifrada con una
> clave derivada de ese secreto (ver `libraauth/crypto.py`), y quien la escribe
> acá es este proceso, no el de la instancia. Si no coinciden, el producto
> guarda bien pero después lee `password_indescifrable` y el envío de correo
> queda roto sin que nada falle a la vista. **No** se reusa el `SECRET_KEY` del
> backoffice para esto: ese firma su propia cookie de sesión y es un secreto
> distinto, con su propio ciclo de rotación.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

# Features conocidas. Una feature desconocida en el .env es un error de
# configuración y se avisa al arrancar: escribir `FEATURES=smpt,usuarios`
# dejaría el backoffice sin la pantalla de correo y sin ninguna señal.
FEATURES_VALIDAS = frozenset({"smtp", "usuarios", "salud", "clientes"})


class ConfiguracionInvalida(RuntimeError):
    """El entorno no alcanza para levantar el backoffice."""


@dataclass(frozen=True)
class Settings:
    product_slug: str
    product_name: str
    features: frozenset[str]

    # Base donde libraauth crea sus tablas en la instancia del producto
    # (`usuarios`, `smtp_settings`). En los 4 productos nuevos es la base de
    # LibraCore de esa instancia — ver el comentario largo en el `create_app`
    # de cada producto sobre por qué `usuarios` vive ahí y no en la del dominio.
    auth_db_path: Path | None = None

    # Sólo para la feature `clientes` (Contalibra/Restolibra): el checkout del
    # producto en el host y el nombre del archivo de base de cada instancia.
    repo_root: Path | None = None
    db_filename: str = ""

    # Sólo para la feature `salud`: a quién preguntarle si el producto está vivo.
    product_health_url: str = ""

    extra: dict = field(default_factory=dict)

    def tiene(self, feature: str) -> bool:
        return feature in self.features


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
    levanta y recién revienta cuando alguien abre la pantalla de correo es un
    despliegue que parece exitoso.
    """
    env = os.environ if env is None else env

    slug = (env.get("PRODUCT_SLUG") or "").strip()
    if not slug:
        raise ConfiguracionInvalida("Falta PRODUCT_SLUG.")

    features = _leer_features(env.get("FEATURES", ""))

    auth_db_path = None
    if features & {"smtp", "usuarios"}:
        crudo = (env.get("AUTH_DB_PATH") or "").strip()
        if not crudo:
            raise ConfiguracionInvalida(
                "Las features 'smtp' y 'usuarios' necesitan AUTH_DB_PATH: la base de "
                "la instancia del producto donde libraauth tiene sus tablas."
            )
        auth_db_path = Path(crudo)

    repo_root, db_filename = None, ""
    if "clientes" in features:
        crudo = (env.get("REPO_ROOT") or "").strip()
        db_filename = (env.get("DB_FILENAME") or "").strip()
        if not crudo or not db_filename:
            raise ConfiguracionInvalida(
                "La feature 'clientes' necesita REPO_ROOT y DB_FILENAME (el checkout "
                "del producto y el nombre del archivo de base de cada instancia)."
            )
        repo_root = Path(crudo)

    return Settings(
        product_slug=slug,
        product_name=(env.get("PRODUCT_NAME") or slug.title()).strip(),
        features=features,
        auth_db_path=auth_db_path,
        repo_root=repo_root,
        db_filename=db_filename,
        product_health_url=(env.get("PRODUCT_HEALTH_URL") or "").strip(),
    )
