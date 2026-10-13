"""El registro de errores de la familia, cableado de verdad (ADR-045 de libracore).

Lo que prueba el motor (la limpieza de datos, la firma, la rotacion) lo prueba libracore. Lo que es del BACKOFFICE, y lo
que fija este archivo, es el cableado: que `create_app` instale `instalar_registro_de_errores`, de modo que

1. una ruta que revienta conteste `500` con un `ref` y deje UNA linea en el `errores.jsonl` (el que lee el vigia),
   con el producto `libra-backoffice` y la instancia (el contenedor) que corresponde: los ocho backoffices comparten
   producto y se distinguen por `LIBRA_INSTANCIA`;
2. los 4xx de siempre (sin sesion, login mal) no ensucien el registro;
3. exista `POST /api/errores-cliente`, a donde manda `instalarReporteDeErrores` de libra-ui, sin pedir sesion.

Si alguien sacara la linea de `app.py`, los tres se ponen rojos.
"""
import json

import pytest
from fastapi.testclient import TestClient

from libra_backoffice.app import create_app

from .conftest import PASSWORD, USUARIO, construir_settings


@pytest.fixture
def carpeta_de_errores(tmp_path, monkeypatch):
    """`LIBRA_ERRORES_DIR` a un temporal: la suite nunca escribe en el cwd."""
    carpeta = tmp_path / "errores"
    monkeypatch.setenv("LIBRA_ERRORES_DIR", str(carpeta))
    monkeypatch.setenv("LIBRA_ENTORNO", "cliente")
    monkeypatch.setenv("LIBRA_INSTANCIA", "gestiolibra-admin")
    return carpeta


def _lineas(carpeta) -> list[dict]:
    archivo = carpeta / "errores.jsonl"
    if not archivo.exists():
        return []
    return [json.loads(linea) for linea in archivo.read_text(encoding="utf-8").splitlines() if linea.strip()]


@pytest.fixture
def app_que_explota(tmp_path, inventario):
    app = create_app(construir_settings(tmp_path), inventario=inventario)

    @app.get("/api/_explota/{cosa}")
    def explota(cosa: str):
        raise ValueError(f"se rompio {cosa}")

    return app


def test_un_500_responde_con_ref_y_deja_una_linea(app_que_explota, carpeta_de_errores):
    # `raise_server_exceptions=False`: el TestClient, si no, relanza lo que uvicorn tambien ve.
    c = TestClient(app_que_explota, base_url="https://testserver", raise_server_exceptions=False)
    r = c.get("/api/_explota/42")

    assert r.status_code == 500, r.text
    cuerpo = r.json()
    assert cuerpo["detail"] == "Error interno"
    assert len(cuerpo["ref"]) == 8
    lineas = _lineas(carpeta_de_errores)
    assert len(lineas) == 1, lineas
    linea = lineas[0]
    assert linea["ref"] == cuerpo["ref"]
    assert linea["producto"] == "libra-backoffice"
    assert linea["instancia"] == "gestiolibra-admin"
    assert linea["entorno"] == "cliente"
    assert linea["origen"] == "servidor"
    assert linea["status"] == 500
    assert linea["tipo"] == "ValueError"
    # La plantilla de la ruta, nunca la URL con el id.
    assert linea["ruta"] == "/api/_explota/{cosa}"


def test_los_4xx_no_se_registran(cliente, carpeta_de_errores):
    assert cliente.get("/api/salud").status_code == 401
    assert cliente.get("/api/me").status_code == 401
    assert cliente.post("/api/login", json={"username": USUARIO, "password": PASSWORD}).status_code in (400, 401)
    assert _lineas(carpeta_de_errores) == []


def test_el_navegador_puede_reportar_sin_sesion(cliente, carpeta_de_errores):
    """`POST /api/errores-cliente` es publico a proposito (un error del login tambien importa)."""
    r = cliente.post(
        "/api/errores-cliente",
        json={"tipo": "render", "mensaje": "x is undefined", "stack": "at Instancias (bundle.js:1:2)",
              "pagina": "/instancias/acme", "release": "abc123"},
        headers={"Origin": "https://testserver"},
    )
    assert r.status_code == 204, r.text
    lineas = _lineas(carpeta_de_errores)
    assert len(lineas) == 1
    assert lineas[0]["origen"] == "cliente"
    assert lineas[0]["producto"] == "libra-backoffice"
    assert lineas[0]["ruta"] == "/instancias/acme"
