"""
Un token de servicio por instancia (ADR-071 de libracore, libracore v1.183.0).

El backoffice lee el `LIBRA_SERVICE_TOKEN` de cada instancia de su compose en
cada request; el global (`settings.service_token`) queda de respaldo para las
que todavía no tienen uno propio y para la ventana de una rotación. Lo que se
prueba:

- qué token sale para cada instancia, y que se relee en cada request;
- los reintentos: sólo ante un 401 con el propio, primero con el
  `LIBRA_SERVICE_TOKEN_ANTERIOR` de la instancia y después con el global, sin
  repetir un valor (dos como máximo);
- que nada más se reintenta;
- que sin propio ni global la instancia contesta su error y el backoffice sigue;
- el estado `propio` / `compartido` / `ausente` en `/api/salud`, sin valores.

Todos los tokens son ficticios.
"""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from libra_backoffice.app import create_app
from libra_backoffice.cliente_instancia import (
    AUSENTE,
    COMPARTIDO,
    PROPIO,
    ClienteInstancia,
    RespuestaDeInstancia,
    SinCredencial,
)
from libra_backoffice.inventario import Instancia, Inventario

from .conftest import (
    PASSWORD,
    TOKEN,
    USUARIO,
    InventarioFalso,
    _TransporteDeInstancias,
    construir_settings,
    login,
)

PROPIO_ACME = "token-propio-de-acme-ficticio"
ACME = Instancia(slug="acme", nombre="ACME SA", container="producto-acme")


class _Grabadora:
    """Un transporte que anota el token de cada request y contesta lo que se le pida."""

    def __init__(self, *codigos):
        self.tokens: list[str] = []
        self._codigos = list(codigos)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.tokens.append(request.headers.get("x-internal-auth", ""))
        codigo = self._codigos.pop(0) if len(self._codigos) > 1 else self._codigos[0]
        return httpx.Response(codigo, json={"ok": codigo < 400, "detail": f"HTTP {codigo}"})


def _cliente(grabadora, *, token=TOKEN, propios=None, anteriores=None):
    propios = {} if propios is None else propios
    anteriores = {} if anteriores is None else anteriores
    return ClienteInstancia(
        token=token, token_de_instancia=propios.get, anterior_de_instancia=anteriores.get,
        transport=httpx.MockTransport(grabadora),
    )


def _pedir(cliente, metodo="GET"):
    return asyncio.run(cliente.pedir(metodo, ACME, "/health"))


# ── Qué token se manda ──────────────────────────────────────────────────────

def test_manda_el_token_propio_de_la_instancia():
    g = _Grabadora(200)
    _pedir(_cliente(g, propios={"acme": PROPIO_ACME}))
    assert g.tokens == [PROPIO_ACME]


def test_sin_propio_manda_el_global():
    g = _Grabadora(200)
    _pedir(_cliente(g))
    assert g.tokens == [TOKEN]


def test_sin_lector_de_instancia_manda_el_global():
    """Un inventario sin `token_de_servicio` (o un ClienteInstancia armado como antes) usa el global."""
    g = _Grabadora(200)
    _pedir(ClienteInstancia(token=TOKEN, transport=httpx.MockTransport(g)))
    assert g.tokens == [TOKEN]


def test_el_token_se_relee_en_cada_request():
    """Sin caché: una rotación se ve en la request siguiente, sin reiniciar el backoffice."""
    g = _Grabadora(200)
    propios = {"acme": PROPIO_ACME}
    cliente = _cliente(g, propios=propios)
    _pedir(cliente)
    propios["acme"] = "token-rotado-de-acme-ficticio"
    _pedir(cliente)
    assert g.tokens == [PROPIO_ACME, "token-rotado-de-acme-ficticio"]


# ── La ventana de rotación ──────────────────────────────────────────────────

def test_un_401_con_el_propio_reintenta_una_vez_con_el_global():
    """Entre que `--rotar` escribe el valor nuevo y que el `up -d` recrea la
    instancia, ésta todavía conoce el viejo (en la primera rotación, el global)."""
    g = _Grabadora(401, 200)
    assert _pedir(_cliente(g, propios={"acme": PROPIO_ACME}), metodo="PUT") == {"ok": True, "detail": "HTTP 200"}
    assert g.tokens == [PROPIO_ACME, TOKEN]


def test_sin_anterior_el_reintento_es_uno_solo():
    g = _Grabadora(401)
    with pytest.raises(RespuestaDeInstancia) as exc:
        _pedir(_cliente(g, propios={"acme": PROPIO_ACME}))
    assert exc.value.status_code == 401
    assert g.tokens == [PROPIO_ACME, TOKEN]


@pytest.mark.parametrize("codigo", [403, 404, 422, 500, 503])
def test_ningun_otro_codigo_se_reintenta(codigo):
    g = _Grabadora(codigo)
    with pytest.raises(RespuestaDeInstancia):
        _pedir(_cliente(g, propios={"acme": PROPIO_ACME}))
    assert g.tokens == [PROPIO_ACME]


def test_un_401_con_el_global_no_se_reintenta():
    g = _Grabadora(401)
    with pytest.raises(RespuestaDeInstancia):
        _pedir(_cliente(g))
    assert g.tokens == [TOKEN]


def test_un_401_con_un_propio_igual_al_global_no_se_reintenta():
    g = _Grabadora(401)
    with pytest.raises(RespuestaDeInstancia):
        _pedir(_cliente(g, propios={"acme": TOKEN}))
    assert g.tokens == [TOKEN]


def test_un_401_sin_global_no_se_reintenta():
    g = _Grabadora(401)
    with pytest.raises(RespuestaDeInstancia):
        _pedir(_cliente(g, token="", propios={"acme": PROPIO_ACME}))
    assert g.tokens == [PROPIO_ACME]


ANTERIOR_ACME = "token-anterior-de-acme-ficticio"


def test_un_401_con_el_propio_reintenta_primero_con_el_anterior():
    """Rotaciones siguientes: el viejo ya no es el global sino el `_ANTERIOR` que dejó `--rotar`."""
    g = _Grabadora(401, 200)
    _pedir(_cliente(g, propios={"acme": PROPIO_ACME}, anteriores={"acme": ANTERIOR_ACME}), metodo="POST")
    assert g.tokens == [PROPIO_ACME, ANTERIOR_ACME]


def test_si_el_anterior_tambien_da_401_prueba_el_global():
    g = _Grabadora(401, 401, 200)
    _pedir(_cliente(g, propios={"acme": PROPIO_ACME}, anteriores={"acme": ANTERIOR_ACME}))
    assert g.tokens == [PROPIO_ACME, ANTERIOR_ACME, TOKEN]


def test_dos_reintentos_como_maximo():
    g = _Grabadora(401)
    with pytest.raises(RespuestaDeInstancia) as exc:
        _pedir(_cliente(g, propios={"acme": PROPIO_ACME}, anteriores={"acme": ANTERIOR_ACME}))
    assert exc.value.status_code == 401
    assert g.tokens == [PROPIO_ACME, ANTERIOR_ACME, TOKEN]


def test_un_codigo_que_no_es_401_con_el_anterior_corta_los_reintentos():
    g = _Grabadora(401, 403)
    with pytest.raises(RespuestaDeInstancia) as exc:
        _pedir(_cliente(g, propios={"acme": PROPIO_ACME}, anteriores={"acme": ANTERIOR_ACME}))
    assert exc.value.status_code == 403
    assert g.tokens == [PROPIO_ACME, ANTERIOR_ACME]


def test_no_se_repite_un_valor_ya_probado():
    # El anterior igual al propio se saltea; el global igual al anterior, también.
    g = _Grabadora(401)
    with pytest.raises(RespuestaDeInstancia):
        _pedir(_cliente(g, propios={"acme": PROPIO_ACME}, anteriores={"acme": PROPIO_ACME}))
    assert g.tokens == [PROPIO_ACME, TOKEN]

    g = _Grabadora(401)
    with pytest.raises(RespuestaDeInstancia):
        _pedir(_cliente(g, propios={"acme": PROPIO_ACME}, anteriores={"acme": TOKEN}))
    assert g.tokens == [PROPIO_ACME, TOKEN]


def test_sin_global_el_anterior_es_el_unico_reintento():
    g = _Grabadora(401)
    with pytest.raises(RespuestaDeInstancia):
        _pedir(_cliente(g, token="", propios={"acme": PROPIO_ACME}, anteriores={"acme": ANTERIOR_ACME}))
    assert g.tokens == [PROPIO_ACME, ANTERIOR_ACME]


def test_con_el_global_no_se_prueba_el_anterior():
    """Sin token propio no hay rotación en curso del lado del backoffice: un 401 con el global es definitivo."""
    g = _Grabadora(401)
    with pytest.raises(RespuestaDeInstancia):
        _pedir(_cliente(g, anteriores={"acme": ANTERIOR_ACME}))
    assert g.tokens == [TOKEN]


def test_el_anterior_se_lee_solo_ante_un_401():
    leidos = []

    def anterior(slug):
        leidos.append(slug)
        return ANTERIOR_ACME

    g = _Grabadora(200)
    cliente = ClienteInstancia(
        token=TOKEN, token_de_instancia={"acme": PROPIO_ACME}.get, anterior_de_instancia=anterior,
        transport=httpx.MockTransport(g),
    )
    _pedir(cliente)
    assert leidos == []


# ── Sin propio ni global ────────────────────────────────────────────────────

def test_sin_propio_ni_global_es_un_error_de_esa_instancia():
    g = _Grabadora(200)
    with pytest.raises(SinCredencial) as exc:
        _pedir(_cliente(g, token=""))
    assert exc.value.status_code == 503
    assert "acme" in exc.value.detalle
    assert g.tokens == []  # no se le pegó sin credencial


# ── Estado del token ────────────────────────────────────────────────────────

def test_estado_del_token():
    cliente = ClienteInstancia(token=TOKEN, token_de_instancia={"a": PROPIO_ACME, "b": TOKEN}.get)
    assert cliente.estado_token("a") == PROPIO
    assert cliente.estado_token("b") == COMPARTIDO
    assert cliente.estado_token("c") == AUSENTE
    sin_global = ClienteInstancia(token="", token_de_instancia={"a": PROPIO_ACME}.get)
    assert sin_global.estado_token("a") == PROPIO
    assert sin_global.estado_token("c") == AUSENTE


def test_el_inventario_delega_en_libracore():
    """`Inventario.token_de_servicio` es `libracore.admin.services.token_de_servicio` (sin cachear)."""

    class _Servicios:
        def token_de_servicio(self, slug):
            return {"acme": PROPIO_ACME}.get(slug)

    inv = Inventario.__new__(Inventario)
    inv.servicios = _Servicios()
    assert inv.token_de_servicio("acme") == PROPIO_ACME
    assert inv.token_de_servicio("beta") is None


def test_el_inventario_lee_el_anterior_del_compose(tmp_path):
    """`Inventario.token_anterior_de_servicio`: `tokens_instancia.leer` del motor sobre el directorio
    de la instancia, con la misma validación de slug que `token_de_servicio`."""
    (tmp_path / "acme").mkdir()
    (tmp_path / "acme" / "docker-compose.yml").write_text(
        "services:\n"
        "  app:\n"
        "    image: producto:x\n"
        "    environment:\n"
        f"      - LIBRA_SERVICE_TOKEN={PROPIO_ACME}\n"
        f"      - LIBRA_SERVICE_TOKEN_ANTERIOR={ANTERIOR_ACME}\n",
        encoding="utf-8",
    )
    (tmp_path / "beta").mkdir()
    (tmp_path / "beta" / "docker-compose.yml").write_text(
        "services:\n  app:\n    image: producto:x\n    environment:\n"
        f"      - LIBRA_SERVICE_TOKEN={PROPIO_ACME}\n",
        encoding="utf-8",
    )

    class _Servicios:
        def clientes_dir(self):
            return tmp_path

    inv = Inventario.__new__(Inventario)
    inv.servicios = _Servicios()
    assert inv.token_anterior_de_servicio("acme") == ANTERIOR_ACME
    assert inv.token_anterior_de_servicio("beta") is None
    assert inv.token_anterior_de_servicio("no-existe") is None
    for malo in ("", ".", "..", "../acme", "acme/../acme"):
        assert inv.token_anterior_de_servicio(malo) is None


# ── De punta a punta, contra instancias con el guard real de libraauth ──────

class _InventarioConTokens(InventarioFalso):
    """`acme` ya tiene token propio pero su contenedor todavía conoce el global
    (la ventana de rotación); `beta` tiene en el compose el mismo valor que el
    global; `caida` no tiene ninguno."""

    def __init__(self, propios):
        super().__init__()
        self.propios = propios

    def token_de_servicio(self, slug):
        return self.propios.get(slug)

    def token_anterior_de_servicio(self, slug):
        return None


def _backoffice(tmp_path, instancias_falsas, inventario, token=TOKEN):
    app = create_app(construir_settings(tmp_path, service_token=token), inventario=inventario)
    app.state.cliente_instancia = ClienteInstancia(
        token=token, token_de_instancia=inventario.token_de_servicio,
        anterior_de_instancia=inventario.token_anterior_de_servicio,
        transport=_TransporteDeInstancias(instancias_falsas),
    )
    c = TestClient(app, base_url="https://testserver")
    assert login(c, {"username": USUARIO, "password": PASSWORD}).status_code == 200
    return c


def test_create_app_le_pasa_el_lector_del_inventario(tmp_path):
    inventario = _InventarioConTokens({"acme": PROPIO_ACME})
    app = create_app(construir_settings(tmp_path), inventario=inventario)
    assert app.state.cliente_instancia.estado_token("acme") == PROPIO
    assert app.state.cliente_instancia._anterior_de_instancia == inventario.token_anterior_de_servicio


def test_salud_informa_el_token_de_cada_instancia_sin_valores(tmp_path, instancias_falsas):
    inventario = _InventarioConTokens({"acme": PROPIO_ACME, "beta": TOKEN})
    resp = _backoffice(tmp_path, instancias_falsas, inventario).get("/api/salud")
    assert resp.status_code == 200
    estados = {i["slug"]: i for i in resp.json()["instancias"]}
    assert estados["acme"]["token"] == "propio"
    assert estados["beta"]["token"] == "compartido"
    assert estados["caida"]["token"] == "ausente"
    # `acme` contesta en la ventana de rotación gracias al reintento con el global.
    assert estados["acme"]["estado"] == "ok"
    assert estados["beta"]["estado"] == "ok"
    assert PROPIO_ACME not in resp.text and TOKEN not in resp.text


def test_sin_global_la_instancia_sin_token_contesta_su_error(tmp_path, instancias_falsas):
    """Sin propio ni global, la pantalla de esa instancia dice por qué; las demás andan."""
    inventario = _InventarioConTokens({"beta": TOKEN})
    c = _backoffice(tmp_path, instancias_falsas, inventario, token="")

    resp = c.get("/api/instancias/acme/smtp")
    assert resp.status_code == 503
    assert "acme" in resp.json()["detail"] and "token-servicio" in resp.json()["detail"]
    assert c.get("/api/instancias/beta/smtp").status_code == 200

    estados = {i["slug"]: i for i in c.get("/api/salud").json()["instancias"]}
    assert estados["acme"]["estado"] == "sin credencial"
    assert estados["beta"]["estado"] == "ok"
