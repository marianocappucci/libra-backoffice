"""
Los caminos que se recorren cuando algo ya está roto.

Van juntos y con tests propios a propósito: son exactamente el código que corre
en el peor momento, y un bug ahí convierte un problema diagnosticable en uno
mudo.
"""
import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from libra_backoffice.cliente_instancia import (
    ClienteInstancia,
    InstanciaInalcanzable,
    RespuestaDeInstancia,
    _detalle,
)
from libra_backoffice.inventario import Instancia

from .conftest import TOKEN, _TransporteDeInstancias


def _resp(contenido, status=500, content_type="application/json"):
    return httpx.Response(status, content=contenido, headers={"content-type": content_type})


def test_detalle_prefiere_el_campo_detail(cliente):
    assert _detalle(_resp(b'{"detail": "host vacio"}', 422)) == "host vacio"


def test_detalle_con_json_sin_detail(cliente):
    assert _detalle(_resp(b'{"error": "otra cosa"}', 500)) == "HTTP 500"


def test_detalle_con_cuerpo_que_no_es_json(cliente):
    """Un 502 de nginx delante de la instancia devuelve HTML, no JSON."""
    assert "Bad Gateway" in _detalle(_resp(b"<html>Bad Gateway</html>", 502, "text/html"))


def test_detalle_con_cuerpo_vacio(cliente):
    assert _detalle(_resp(b"", 503, "text/plain")) == "HTTP 503"


@pytest.mark.anyio
async def test_una_instancia_que_devuelve_texto_plano(anyio_backend):
    """La instancia contesta, pero con algo que no es la API esperada."""
    app = FastAPI()

    @app.get("/health")
    def health():
        return PlainTextResponse("me caí", status_code=500)

    cliente = ClienteInstancia(
        token=TOKEN, transport=_TransporteDeInstancias({"prod-x": app})
    )
    instancia = Instancia(slug="x", nombre="X", container="prod-x")

    with pytest.raises(RespuestaDeInstancia) as exc:
        await cliente.pedir("GET", instancia, "/health")
    assert exc.value.status_code == 500


@pytest.mark.anyio
async def test_un_200_que_no_es_json_no_se_lee_como_exito(anyio_backend):
    """El caso que rompio en produccion con LibraDesk.

    Los productos de la familia sirven una SPA con fallback, asi que CUALQUIER
    ruta que no exista devuelve 200 con HTML. Con un `resp.json()` a secas eso
    salia como un 500 del backoffice, y el mensaje no decia nada del path mal
    configurado.
    """
    app = FastAPI()

    @app.get("/{ruta:path}")
    def spa(ruta: str):
        return PlainTextResponse("<!doctype html><div id=root></div>")

    cliente = ClienteInstancia(token=TOKEN, transport=_TransporteDeInstancias({"prod-x": app}))
    instancia = Instancia(slug="x", nombre="X", container="prod-x")

    with pytest.raises(RespuestaDeInstancia) as exc:
        await cliente.pedir("GET", instancia, "/ruta/que/no/existe")
    assert "no es JSON" in exc.value.detalle
    assert "HEALTH_PATH" in exc.value.detalle


@pytest.mark.anyio
async def test_el_chequeo_de_salud_no_exige_json(anyio_backend):
    """`/health` de algunos productos no devuelve JSON, y ahi solo importa el
    codigo de estado."""
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return PlainTextResponse("ok")

    cliente = ClienteInstancia(token=TOKEN, transport=_TransporteDeInstancias({"prod-x": app}))
    instancia = Instancia(slug="x", nombre="X", container="prod-x")

    assert await cliente.pedir("GET", instancia, "/api/health", esperar_json=False) is None


@pytest.mark.anyio
async def test_un_contenedor_que_no_existe(anyio_backend):
    cliente = ClienteInstancia(token=TOKEN, transport=_TransporteDeInstancias({}))
    instancia = Instancia(slug="x", nombre="X", container="no-existe")

    with pytest.raises(InstanciaInalcanzable) as exc:
        await cliente.pedir("GET", instancia, "/health")
    assert exc.value.slug == "x"


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ── Salud con instancias en mal estado ──────────────────────────────────────

def test_salud_reporta_instancia_sin_container_name(logueado, inventario):
    """Una instancia cuyo `cliente.json` quedó sin `container`. No hay a quién
    preguntarle, y decirlo es mejor que reportarla como caída."""
    inventario._instancias["huerfana"] = Instancia(
        slug="huerfana", nombre="Sin contenedor", container=""
    )
    estados = {i["slug"]: i for i in logueado.get("/api/salud").json()["instancias"]}
    assert estados["huerfana"]["estado"] == "sin contenedor"
    assert "container_name" in estados["huerfana"]["detalle"]


def test_salud_reporta_error_http_de_una_instancia(logueado, instancias_falsas):
    """La instancia contesta pero su /health falla: no es lo mismo que estar
    caída, y la pantalla tiene que poder distinguirlo."""
    app = instancias_falsas["producto-acme"]
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/health"]

    @app.get("/health")
    def health_roto():
        return PlainTextResponse("db down", status_code=503)

    estados = {i["slug"]: i["estado"] for i in logueado.get("/api/salud").json()["instancias"]}
    assert estados["acme"] == "error"
