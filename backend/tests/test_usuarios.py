NUEVO = {"username": "ana", "name": "Ana Pérez", "password": "clave-inicial", "role": "staff"}


def test_usuarios_pide_sesion(cliente):
    assert cliente.get("/api/usuarios").status_code == 401


def test_lista_vacia_al_principio(logueado):
    assert logueado.get("/api/usuarios").json() == []


def test_alta_y_listado(logueado):
    creado = logueado.post("/api/usuarios", json=NUEVO)
    assert creado.status_code == 201
    assert creado.json()["username"] == "ana"
    assert creado.json()["active"] is True
    assert "password" not in creado.json()

    assert [u["username"] for u in logueado.get("/api/usuarios").json()] == ["ana"]


def test_username_repetido_es_409(logueado):
    logueado.post("/api/usuarios", json=NUEVO)
    assert logueado.post("/api/usuarios", json=NUEVO).status_code == 409


def test_rol_invalido_es_422(logueado):
    assert logueado.post("/api/usuarios", json={**NUEVO, "role": "dueño"}).status_code == 422


def test_edicion_y_baja_logica(logueado):
    uid = logueado.post("/api/usuarios", json=NUEVO).json()["id"]

    editado = logueado.put(
        f"/api/usuarios/{uid}", json={"name": "Ana P.", "role": "admin", "active": True}
    ).json()
    assert editado["name"] == "Ana P."
    assert editado["role"] == "admin"

    desactivado = logueado.put(
        f"/api/usuarios/{uid}", json={"name": "Ana P.", "role": "admin", "active": False}
    ).json()
    assert desactivado["active"] is False


def test_editar_inexistente_es_404(logueado):
    resp = logueado.put("/api/usuarios/999", json={"name": "X", "role": "staff", "active": True})
    assert resp.status_code == 404
