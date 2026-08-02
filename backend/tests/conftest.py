"""
Fixtures de la suite.

La app se construye contra una base SQLite real en un tmp_path con las tablas
de libraauth ya creadas — no contra mocks. Es la misma decisión que tomó
LibraCore al testear su backoffice: lo que rompe en estos routers es la
integración con el motor (el cifrado, la precedencia base/entorno, la
semántica de `SIN_CAMBIOS`), y eso un doble no lo ejercita.
"""
import os

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase
from sqlalchemy import create_engine

from libra_backoffice.app import create_app
from libra_backoffice.settings import Settings

USUARIO = "superadmin"
PASSWORD = "una-password-de-prueba"


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    """Credenciales del superadmin y secretos, como los daría el `.env`.

    `ENV=development` es lo que habilita el fallback de `SECRET_KEY` en
    libraauth; sin él la app directamente no levanta, que es el comportamiento
    correcto en producción.
    """
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("ADMIN_PANEL_USER", USUARIO)
    monkeypatch.setenv("ADMIN_PANEL_PASSWORD", PASSWORD)
    monkeypatch.setenv("SECRET_KEY", "0" * 64)
    # La clave con la que se cifra la password SMTP. En un despliegue real vale
    # lo mismo que el SECRET_KEY de la INSTANCIA del producto, no el de acá.
    monkeypatch.setenv("LIBRAAUTH_ENCRYPTION_KEY", "1" * 64)


@pytest.fixture
def db_instancia(tmp_path):
    """Base de la instancia del producto, con el schema de libraauth creado."""
    ruta = tmp_path / "producto_libracore.db"
    AuthBase.metadata.create_all(create_engine(f"sqlite:///{ruta}"))
    return ruta


def construir_settings(db_path, features):
    return Settings(
        product_slug="gestiolibra",
        product_name="Gestiolibra",
        features=frozenset(features),
        auth_db_path=db_path,
    )


@pytest.fixture
def cliente(db_instancia):
    """Cliente HTTP sin loguear, con las tres features de un producto nuevo.

    `base_url` en **https** y no en http: `AdminAuth` marca la cookie de sesión
    como `secure`, y el cookie jar de httpx —correctamente— no la manda de
    vuelta por una conexión insegura. Con `http://testserver` el login
    devolvería 200 y todas las requests siguientes 401, que parece un bug de
    auth y es el navegador haciendo lo suyo. En producción no es un problema
    porque NPM termina el TLS y el navegador siempre habla https.
    """
    app = create_app(construir_settings(db_instancia, {"smtp", "usuarios", "salud"}))
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def logueado(cliente):
    resp = cliente.post("/api/login", json={"username": USUARIO, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return cliente
