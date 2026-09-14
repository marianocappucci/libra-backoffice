"""Renovación deslizante de la sesión del superadmin (ADR-017 de libraauth
v0.43.0), tal como llega hasta acá.

`AdminAuth.current_user` ya sabe renovar: firma de nuevo la cookie si pasaron
más de `RENOVACION_MINIMA_SEGUNDOS` desde que se firmó, con tal de que se le
pase el `response` de la request (ver su docstring en libraauth). Lo que este
archivo prueba es que **`deps.admin_actual` se lo pasa** — antes del bump a
v0.43.0 no lo hacía (no podía: el parámetro no existía en v0.42.0), así que
la sesión del backoffice vencía siempre a las 8 h en punto, se hubiera usado
o no en el medio.

Mismo mecanismo que `tests/test_admin_auth.py` de libraauth: reloj falso
parcheando `TimestampSigner.get_timestamp` (no freezegun — ver el comentario
largo en `test_session_auth.py` de libraauth sobre por qué). La ruta que se
ejercita es `/api/me`, que ya existe y cuelga de `admin_actual` vía `Depends`
sin declarar `response` — exactamente el caso que el ADR-017 señala como el
que hay que cuidar a mano.
"""
import itsdangerous.timed
import pytest
from libraauth.session_auth import RENOVACION_MINIMA_SEGUNDOS

from .conftest import login, PASSWORD, USUARIO


class _RelojFalso:
    def __init__(self):
        self.ahora = 1_800_000_000

    def avanzar(self, segundos: float) -> None:
        self.ahora += segundos


@pytest.fixture
def reloj(monkeypatch):
    r = _RelojFalso()
    monkeypatch.setattr(
        itsdangerous.timed.TimestampSigner, "get_timestamp", lambda self: int(r.ahora)
    )
    return r


def _loguear(cliente):
    resp = login(cliente, {"username": USUARIO, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return cliente


def test_sesion_usada_cada_hora_durante_10h_sigue_viva(cliente, reloj):
    _loguear(cliente)

    r = None
    for _ in range(10):
        reloj.avanzar(3600)
        r = cliente.get("/api/me")
        assert r.status_code == 200, r.text
    assert r.json() == {"username": USUARIO}


def test_sesion_sin_uso_8h_mas_1s_se_rechaza(cliente, reloj):
    """Literal `8 * 3600 + 1`, no una constante importada: con la constante
    este test sería tautológico frente a un cambio del valor en libraauth."""
    _loguear(cliente)

    reloj.avanzar(8 * 3600 + 1)
    assert cliente.get("/api/me").status_code == 401


def test_renovacion_reemite_la_cookie(cliente, reloj):
    _loguear(cliente)

    reloj.avanzar(RENOVACION_MINIMA_SEGUNDOS + 1)
    r = cliente.get("/api/me")
    assert r.status_code == 200
    assert "set-cookie" in r.headers


def test_no_renueva_antes_de_la_ventana(cliente, reloj):
    _loguear(cliente)

    reloj.avanzar(RENOVACION_MINIMA_SEGUNDOS - 1)
    r = cliente.get("/api/me")
    assert r.status_code == 200
    assert "set-cookie" not in r.headers


def test_cookie_firmada_hace_9h_se_rechaza(cliente, reloj):
    """El default viejo (sesión de N días fija) habría aceptado esto. Con la
    ventana de inactividad, 9 h sin uso ya no alcanzan."""
    _loguear(cliente)

    reloj.avanzar(9 * 3600)
    assert cliente.get("/api/me").status_code == 401
