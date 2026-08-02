"""
Los feature flags son lo que hace que una sola imagen sirva a seis productos,
así que su comportamiento es parte del contrato: en un producto que no es
multi-instancia, `/api/clientes` **no existe**.
"""
import pytest
from fastapi.testclient import TestClient

from libra_backoffice.app import create_app
from libra_backoffice.settings import ConfiguracionInvalida, cargar_settings

from .conftest import PASSWORD, USUARIO, construir_settings


def test_clientes_no_existe_sin_la_feature(logueado):
    assert logueado.get("/api/clientes").status_code == 404


def test_smtp_no_existe_si_la_feature_esta_apagada(db_instancia):
    app = create_app(construir_settings(db_instancia, {"usuarios", "salud"}))
    with TestClient(app, base_url="https://testserver") as c:
        c.post("/api/login", json={"username": USUARIO, "password": PASSWORD})
        assert c.get("/api/smtp").status_code == 404
        assert c.get("/api/usuarios").status_code == 200


def test_la_feature_gana_al_401(db_instancia):
    """Sin sesión y sin la feature, contesta 404.

    Es deliberado: contestar 401 le confirmaría a alguien sin credenciales que
    ese producto tiene habilitada la gestión de instancias.
    """
    app = create_app(construir_settings(db_instancia, {"usuarios"}))
    with TestClient(app, base_url="https://testserver") as c:
        assert c.get("/api/clientes").status_code == 404


def test_salud_reporta_features_y_arranque(logueado):
    cuerpo = logueado.get("/api/salud").json()
    assert cuerpo["producto"]["slug"] == "gestiolibra"
    assert cuerpo["features"] == ["salud", "smtp", "usuarios"]
    assert cuerpo["backoffice"]["uptime_segundos"] >= 0
    # Sin PRODUCT_HEALTH_URL no se inventa un estado.
    assert cuerpo["instancia"]["estado"] == "no configurado"


# ── settings ────────────────────────────────────────────────────────────────

def test_falta_product_slug(monkeypatch):
    with pytest.raises(ConfiguracionInvalida, match="PRODUCT_SLUG"):
        cargar_settings({"FEATURES": "salud"})


def test_features_vacio(monkeypatch):
    with pytest.raises(ConfiguracionInvalida, match="vacío"):
        cargar_settings({"PRODUCT_SLUG": "x", "FEATURES": ""})


def test_feature_mal_escrita_no_pasa_en_silencio():
    """`FEATURES=smpt` dejaría el backoffice sin la pantalla de correo y sin
    ninguna señal de por qué."""
    with pytest.raises(ConfiguracionInvalida, match="smpt"):
        cargar_settings({"PRODUCT_SLUG": "x", "FEATURES": "smpt,salud"})


def test_smtp_sin_auth_db_path():
    with pytest.raises(ConfiguracionInvalida, match="AUTH_DB_PATH"):
        cargar_settings({"PRODUCT_SLUG": "x", "FEATURES": "smtp"})


def test_clientes_sin_repo_root():
    with pytest.raises(ConfiguracionInvalida, match="REPO_ROOT"):
        cargar_settings({"PRODUCT_SLUG": "x", "FEATURES": "clientes"})


def test_settings_completo():
    s = cargar_settings({
        "PRODUCT_SLUG": "contalibra", "PRODUCT_NAME": "Contalibra",
        "FEATURES": "smtp,usuarios,salud,clientes",
        "AUTH_DB_PATH": "/data/contalibra_libracore.db",
        "REPO_ROOT": "/root/contalibra", "DB_FILENAME": "contalibra.db",
        "PRODUCT_HEALTH_URL": "http://contalibra:8000/health",
    })
    assert s.product_name == "Contalibra"
    assert s.tiene("clientes")
    assert s.db_filename == "contalibra.db"
