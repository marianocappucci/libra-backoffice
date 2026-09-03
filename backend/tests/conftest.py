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
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from libraauth.demo_codigos import DemoCodigoRepository
from libraauth.models import Base as AuthBase
from libraauth.repository import UsernameTaken, UserRepository
from libraauth.session_auth import (
    SERVICE_TOKEN_ENV,
    build_demo_codigos_router,
    build_smtp_settings_router,
    json_api_require_admin_o_servicio,
)
from libraauth.smtp_settings import SmtpSettingsRepository
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from libra_backoffice.app import create_app
from libra_backoffice.cliente_instancia import ClienteInstancia
from libra_backoffice.inventario import Instancia, InstanciaDesconocida
from libra_backoffice.settings import Settings

USUARIO = "superadmin"
PASSWORD = "una-password-de-prueba"
TOKEN = "token-de-servicio-de-prueba"


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("ADMIN_PANEL_USER", USUARIO)
    monkeypatch.setenv("ADMIN_PANEL_PASSWORD", PASSWORD)
    monkeypatch.setenv("SECRET_KEY", "0" * 64)
    # La instancia falsa corre en el mismo proceso, así que este es el token que
    # su guard va a validar.
    monkeypatch.setenv(SERVICE_TOKEN_ENV, TOKEN)


# ── La "instancia" ──────────────────────────────────────────────────────────

class _UsuarioIn(BaseModel):
    username: str
    name: str
    password: str
    role: str = "staff"


class _UsuarioUpdate(BaseModel):
    name: str
    role: str
    active: bool


def construir_instancia_falsa(db_path, *, es_demo=False):
    """Una instancia de producto: router de SMTP de libraauth + router de
    usuarios propio, que es exactamente cómo están los seis.

    `es_demo=True` monta además el ABM de códigos de acceso, igual que hace el
    producto cuando tiene `DEMO_MODE` y `DEMO_USERNAME`. **Las dos variantes
    hacen falta**: sin la que NO es demo, un proxy que devolviera lo mismo para
    cualquier instancia pasaría en verde, y ahí es donde se le muestran los
    códigos de la demo a quien abrió la ficha de un cliente.
    """
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    AuthBase.metadata.create_all(engine)
    sesiones = sessionmaker(bind=engine)

    app = FastAPI()
    app.state.smtp_settings = SmtpSettingsRepository(sesiones)
    app.state.users = UserRepository(sesiones)
    app.state.session_auth = None  # nadie con cookie: sólo se entra por token

    @app.get("/health")
    def health():
        return {"ok": True}

    app.include_router(build_smtp_settings_router())
    if es_demo:
        app.state.demo_codigos = DemoCodigoRepository(sesiones)
        app.include_router(build_demo_codigos_router())

    # El router de usuarios NO es de libraauth: cada producto tiene el suyo.
    # Este reproduce el de los cuatro FastAPI, guard de servicio incluido.
    from fastapi import APIRouter, Depends

    usuarios = APIRouter(prefix="/users", dependencies=[Depends(json_api_require_admin_o_servicio)])

    @usuarios.get("")
    def listar():
        return app.state.users.list()

    @usuarios.post("", status_code=201)
    def crear(datos: _UsuarioIn):
        try:
            return app.state.users.create(**datos.model_dump())
        except UsernameTaken:
            raise HTTPException(409, f"Ya existe un usuario '{datos.username}'.")
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @usuarios.put("/{user_id}")
    def editar(user_id: str, datos: _UsuarioUpdate):
        try:
            return app.state.users.update(user_id, **datos.model_dump())
        except KeyError:
            raise HTTPException(404, "Usuario no encontrado.")

    app.include_router(usuarios)
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
    resp = cliente.post("/api/login", json={"username": USUARIO, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return cliente
