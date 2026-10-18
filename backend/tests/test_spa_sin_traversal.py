"""El catch-all de la SPA no sirve nada que esté fuera de `dist` (path traversal).

Medido el 2026-10-18 contra `libraclub-admin` y `contalibra-panel`, desde adentro del VPS: `curl --path-as-is
http://127.0.0.1:<puerto>/../../../../etc/hostname` (y la variante `/%2e%2e/...`) daba 200 con el archivo de afuera del
`dist`. El catch-all hacía `dist / ruta` y `is_file()` sin resolver ni verificar que quedara adentro. NPM lo corta con
400, pero con esto se habría podido leer `/proc/self/environ` (tokens y claves) de quien llegue al puerto sin pasar por NPM.

El `TestClient` (httpx) normaliza los `..` antes de mandar, así que acá se le habla al ASGI crudo: lo que llega a la app
es lo que decodifica uvicorn (`path` ya con los `..`; `raw_path` con el `%2e%2e` tal cual vino).
"""
import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from libra_backoffice.app import create_app

from .conftest import construir_settings

SECRETO = "SECRETO-DE-AFUERA-DEL-DIST"


@pytest.fixture
def mundo(tmp_path):
    """`tmp_path/secreto.txt` está afuera; `tmp_path/dist` es lo único que se sirve."""
    (tmp_path / "secreto.txt").write_text(SECRETO)
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "sub").mkdir()  # un subdirectorio que existe: ahí el `..` sí resuelve a nivel de filesystem
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (dist / "favicon.ico").write_bytes(b"\x00ico")
    return tmp_path


@pytest.fixture
def app(mundo, inventario):
    return create_app(
        construir_settings(mundo), inventario=inventario, frontend_dist=str(mundo / "dist")
    )


def pedir(app, path, raw_path=None):
    """Una llamada ASGI cruda: devuelve (status, cuerpo)."""
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
        "scheme": "https", "path": path, "raw_path": (raw_path or path).encode(),
        "query_string": b"", "root_path": "", "headers": [(b"host", b"testserver")],
        "server": ("testserver", 443), "client": ("127.0.0.1", 50000),
    }
    mensajes = []

    async def recibir():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def enviar(mensaje):
        mensajes.append(mensaje)

    asyncio.run(app(scope, recibir, enviar))
    status = next(m["status"] for m in mensajes if m["type"] == "http.response.start")
    cuerpo = b"".join(m.get("body", b"") for m in mensajes if m["type"] == "http.response.body")
    return status, cuerpo.decode(errors="replace")


def test_control_positivo_el_helper_llega_a_lo_que_si_se_sirve(app):
    """Sin esto, un helper que no llega a nada daría verde por la razón equivocada."""
    assert pedir(app, "/favicon.ico")[0] == 200
    assert pedir(app, "/assets/app.js") == (200, "console.log(1)")


@pytest.mark.parametrize(
    ("path", "raw_path"),
    [
        ("/../secreto.txt", None),
        ("/" + "../" * 20 + "etc/hostname", None),
        ("/../secreto.txt", "/%2e%2e/secreto.txt"),
        ("/assets/../../secreto.txt", None),
        ("/assets/../../secreto.txt", "/assets/%2e%2e/%2e%2e/secreto.txt"),
        ("/sub/../../secreto.txt", None),
        ("/sub/../../secreto.txt", "/sub/%2e%2e/%2e%2e/secreto.txt"),
        ("/..\\secreto.txt", None),
        ("/%2e%2e/secreto.txt", None),  # el literal: no es un `..` para el filesystem
    ],
)
def test_un_dotdot_no_saca_nada_de_afuera_del_dist(app, path, raw_path):
    status, cuerpo = pedir(app, path, raw_path)
    assert SECRETO not in cuerpo
    assert cuerpo != Path("/etc/hostname").read_text(errors="replace")
    assert status in (200, 404)
    if status == 200:
        assert "<div id=root>" in cuerpo  # cayó en la SPA, como cualquier ruta de React


def test_una_ruta_con_doble_barra_no_se_vuelve_absoluta(app, mundo):
    """`//ruta/absoluta`: Starlette captura `/ruta/absoluta` y `dist / "/ruta/absoluta"` es ESA ruta, no una de dist."""
    absoluta = str(mundo / "secreto.txt")
    status, cuerpo = pedir(app, "/" + absoluta)
    assert SECRETO not in cuerpo


def test_un_symlink_del_dist_que_apunta_afuera_no_se_sigue(app, mundo):
    os.symlink(mundo / "secreto.txt", mundo / "dist" / "enlace.txt")
    os.symlink(mundo, mundo / "dist" / "carpeta")
    for path in ("/enlace.txt", "/carpeta/secreto.txt"):
        _, cuerpo = pedir(app, path)
        assert SECRETO not in cuerpo, path


def test_un_symlink_que_queda_adentro_del_dist_si_se_sirve(app, mundo):
    os.symlink(mundo / "dist" / "favicon.ico", mundo / "dist" / "icono.ico")
    assert pedir(app, "/icono.ico") == (200, "\x00ico")


@pytest.mark.parametrize("ruta", ["/", "/instancias/acme/smtp", "/index.html", "/favicon.ico", "/health"])
def test_head_responde_igual_que_get(app, ruta):
    """Un monitor que hace HEAD (uptime-kuma, curl -I) no puede recibir 405."""
    c = TestClient(app, base_url="https://testserver")
    r = c.head(ruta)
    assert r.status_code == c.get(ruta).status_code == 200
    assert r.content == b""
