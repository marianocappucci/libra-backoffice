from .conftest import PASSWORD, USUARIO


def test_health_no_pide_auth(cliente):
    resp = cliente.get("/health")
    assert resp.status_code == 200
    assert resp.json()["producto"] == "gestiolibra"


def test_login_con_credenciales_correctas(cliente):
    resp = cliente.post("/api/login", json={"username": USUARIO, "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.json() == {"username": USUARIO}


def test_login_con_password_incorrecta(cliente):
    resp = cliente.post("/api/login", json={"username": USUARIO, "password": "cualquiera"})
    assert resp.status_code == 401


def test_me_sin_sesion_devuelve_401_y_no_un_redirect(cliente):
    """El motivo por el que existe `deps.admin_actual`.

    `AdminAuth.require_login` contesta 307 a `/login`; el `fetch` del
    api-client seguiría ese redirect y recibiría el HTML de la SPA con un 200,
    con lo cual el frontend no tendría forma de saber que la sesión venció.
    """
    resp = cliente.get("/api/me")
    assert resp.status_code == 401


def test_me_con_sesion(logueado):
    resp = logueado.get("/api/me")
    assert resp.status_code == 200
    assert resp.json() == {"username": USUARIO}


def test_logout_corta_la_sesion(logueado):
    assert logueado.post("/api/logout").status_code == 200
    assert logueado.get("/api/me").status_code == 401


def test_rate_limit_de_login(cliente):
    for _ in range(5):
        cliente.post("/api/login", json={"username": USUARIO, "password": "mal"})
    # El sexto intento ya no evalúa credenciales: corta antes.
    resp = cliente.post("/api/login", json={"username": USUARIO, "password": PASSWORD})
    assert resp.status_code == 429
