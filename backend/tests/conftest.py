"""
Fixtures de la suite.

La decisión que vale la pena explicar: **la "instancia" de los tests es una app
FastAPI de verdad**, con el router real de `libraauth` y su guard real de token
de servicio, alcanzada por un `ASGITransport`. Un doble que devolviera JSON
plausible estaría de acuerdo con cualquier contrato, incluido uno equivocado —
y el contrato entre el backoffice y las instancias es justamente lo que este
proyecto está estrenando. Así, si el guard de libraauth cambia, esta suite se
entera.
"""
from dataclasses import replace

import httpx
import pytest
from altcha import Challenge, Payload, solve_challenge
from fastapi import FastAPI
from fastapi.testclient import TestClient
from libraauth.captcha import Captcha
from libraauth.demo_codigos import DemoCodigoRepository
from libraauth.models import Base as AuthBase
from libraauth.repository import UserRepository
from libraauth.session_auth import (
    SERVICE_TOKEN_ENV,
    build_demo_codigos_router,
    build_smtp_settings_router,
    json_api_require_admin_o_servicio,
)
from libraauth.smtp_settings import SmtpSettingsRepository
from libraauth.usuarios import build_users_router
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from libra_backoffice.app import create_app
from libra_backoffice.cliente_instancia import ClienteInstancia
from libra_backoffice.inventario import Instancia, InstanciaDesconocida
from libra_backoffice.settings import Settings

USUARIO = "superadmin"
PASSWORD = "una-password-de-prueba"
TOKEN = "token-de-servicio-de-prueba"


def captcha_barato(secret_key: str) -> Captcha:
    """El mismo mecanismo con un costo que no gasta CPU en cada login.

    El de producción tarda del orden de un segundo por desafío, y la suite
    loguea decenas de veces. Lo que cambia es sólo cuánto trabajo pide: firma,
    vencimiento y anti-replay son los mismos. Que la app de verdad arme el caro
    lo cuida `test_la_app_emite_desafios_con_el_costo_de_produccion`.
    """
    return Captcha(secret_key, costo=1, contador_min=1, contador_rango=5)


def resolver_captcha(cliente) -> str:
    """Lo que hace el widget en el navegador: pedir un desafío y resolverlo."""
    ch = Challenge.from_dict(cliente.get("/api/captcha").json())
    return Payload(ch, solve_challenge(ch)).to_base64()


def login(cliente, datos: dict, **kwargs):
    """El login como llega desde la pantalla: con un captcha resuelto."""
    return cliente.post("/api/login", json={**datos, "captcha": resolver_captcha(cliente)}, **kwargs)


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setattr("libra_backoffice.app.Captcha", captcha_barato)
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("ADMIN_PANEL_USER", USUARIO)
    monkeypatch.setenv("ADMIN_PANEL_PASSWORD", PASSWORD)
    monkeypatch.setenv("SECRET_KEY", "0" * 64)
    # La instancia falsa corre en el mismo proceso, así que este es el token que
    # su guard va a validar.
    monkeypatch.setenv(SERVICE_TOKEN_ENV, TOKEN)


# ── La "instancia" ──────────────────────────────────────────────────────────

def construir_instancia_falsa(db_path, *, es_demo=False, roles=("staff", "admin")):
    """Una instancia de producto: los routers de `libraauth` (SMTP, demo y
    ahora usuarios).

    `es_demo=True` monta además el ABM de códigos de acceso, igual que hace el
    producto cuando tiene `DEMO_MODE` y `DEMO_USERNAME`. **Las dos variantes
    hacen falta**: sin la que NO es demo, un proxy que devolviera lo mismo para
    cualquier instancia pasaría en verde, y ahí es donde se le muestran los
    códigos de la demo a quien abrió la ficha de un cliente.

    `roles` es el vocabulario de ESTA instancia (`("admin", "operador",
    "cajero")` en Contalibra, por ejemplo) — lo valida `build_users_router`,
    no el backoffice. Antes de libraauth v0.43.0 (ADR-018) el router de
    usuarios NO era de libraauth: cada producto tenía el propio, y este doble
    reproducía uno de los cuatro FastAPI (sin `DELETE`, sin
    `PUT /{id}/password`, sin `GET /{id}`). Con el contrato único, la
    instancia de la suite pasa a ser la real —el mismo motivo por el que ya
    usa el router real de SMTP—: si la factory cambia, esta suite se entera.
    """
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    AuthBase.metadata.create_all(engine)
    sesiones = sessionmaker(bind=engine)

    app = FastAPI()
    app.state.smtp_settings = SmtpSettingsRepository(sesiones)
    app.state.users = UserRepository(sesiones, roles=roles)
    app.state.session_auth = None  # nadie con cookie: sólo se entra por token

    @app.get("/health")
    def health():
        return {"ok": True}

    app.include_router(build_smtp_settings_router())
    if es_demo:
        app.state.demo_codigos = DemoCodigoRepository(sesiones)
        app.include_router(build_demo_codigos_router())

    app.include_router(
        build_users_router(roles=roles, admin_guard=json_api_require_admin_o_servicio)
    )
    return app


class InventarioFalso:
    """Dos instancias, y una tercera que existe en el inventario pero no
    responde — el caso que hay que poder mirar sin que se caiga la pantalla."""

    def __init__(self):
        self._instancias = {
            "acme": Instancia(slug="acme", nombre="ACME SA", container="producto-acme",
                              domain="acme.test", port=8081, plan="pro", estado="running"),
            # `beta` corre **y** está pausada: los dos ejes a la vez, que es el
            # caso que una pantalla que sólo mira `estado` reporta como "todo
            # bien".
            "beta": Instancia(slug="beta", nombre="Beta SRL", container="producto-beta",
                              domain="beta.test", port=8082, plan="basico", estado="running",
                              servicio_estado="pausado", servicio_mensaje="Corte programado"),
            "caida": Instancia(slug="caida", nombre="Caída SA", container="producto-caida",
                               estado="exited"),
        }

    def verificar_scripts(self):
        """El producto de mentira importa siempre.

        Que este doble diga que si no prueba nada del mecanismo real — eso
        lo cubre test_salud_scripts.py contra scripts de verdad. Aca esta
        para que el /health nuevo no de 503 en toda la suite.
        """

    def listar(self):
        return list(self._instancias.values())

    def obtener(self, slug):
        if slug not in self._instancias:
            raise InstanciaDesconocida(slug)
        return self._instancias[slug]

    def reemplazar(self, slug, **campos):
        """Refleja lo que el motor escribió en el `config.json` de la instancia.

        Sin esto el inventario devuelve siempre la misma foto y un test de
        «suspender» pasaría aunque el router no leyera nada de vuelta: estaría
        asertando sobre el valor inicial, no sobre el efecto de la acción.
        """
        self._instancias[slug] = replace(self._instancias[slug], **campos)


class _TransporteDeInstancias(httpx.AsyncBaseTransport):
    """Rutea por nombre de contenedor a la app de esa instancia.

    Es lo que hace Docker en producción: `http://producto-acme:8000` resuelve
    por DNS interno de la red compartida. Un contenedor sin app registrada
    levanta `ConnectError`, igual que una instancia apagada.
    """

    def __init__(self, apps: dict):
        self._transportes = {
            host: httpx.ASGITransport(app=app) for host, app in apps.items()
        }

    async def handle_async_request(self, request):
        transporte = self._transportes.get(request.url.host)
        if transporte is None:
            raise httpx.ConnectError(f"Name or service not known: {request.url.host}")
        return await transporte.handle_async_request(request)


# ── El backoffice ───────────────────────────────────────────────────────────

def construir_settings(tmp_path, features=("instancias", "smtp", "usuarios", "salud", "demos"), **extra):
    base = dict(
        product_slug="gestiolibra", product_name="Gestiolibra",
        features=frozenset(features), repo_root=tmp_path,
        db_filename="gestiolibra.db", service_token=TOKEN,
    )
    return Settings(**{**base, **extra})


@pytest.fixture
def instancias_falsas(tmp_path):
    """Las dos instancias que sí responden. `caida` queda sin app a propósito."""
    return {
        # `acme` hace de instancia demo y `beta` de instancia de cliente: son
        # los dos lados del par que hace falta para que el proxy de códigos
        # pruebe algo.
        "producto-acme": construir_instancia_falsa(tmp_path / "acme.db", es_demo=True),
        "producto-beta": construir_instancia_falsa(tmp_path / "beta.db"),
    }


@pytest.fixture
def inventario():
    return InventarioFalso()


@pytest.fixture
def cliente(tmp_path, instancias_falsas, inventario):
    """Backoffice sin loguear.

    `base_url` en **https**: `AdminAuth` marca la cookie como `secure` y el
    cookie jar de httpx —correctamente— no la manda por una conexión insegura.
    Con `http://testserver` el login daría 200 y todo lo demás 401, que parece
    un bug de auth y es el navegador haciendo lo suyo. En producción NPM
    termina el TLS, así que no aparece.
    """
    app = create_app(construir_settings(tmp_path), inventario=inventario)
    app.state.cliente_instancia = ClienteInstancia(
        token=TOKEN, transport=_TransporteDeInstancias(instancias_falsas)
    )
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def logueado(cliente):
    resp = login(cliente, {"username": USUARIO, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return cliente
