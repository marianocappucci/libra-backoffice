"""
El control plane: el backoffice configurando instancias por HTTP.

Estos tests corren contra instancias FastAPI reales con el router real de
libraauth, así que prueban de punta a punta lo que el diseño promete: que el
backoffice puede escribirle la config a una instancia **sin ser usuario de esa
instancia** y sin tocar su base.
"""
CONFIG = {
    "host": "smtp.miempresa.com", "port": 587, "user": "cuenta@miempresa.com",
    "from_email": "no-responder@miempresa.com", "from_name": "Soporte",
}


def test_pide_sesion_del_superadmin(cliente):
    assert cliente.get("/api/instancias/acme/smtp").status_code == 401


def test_instancia_inexistente_es_404(logueado):
    assert logueado.get("/api/instancias/fantasma/smtp").status_code == 404


def test_leer_smtp_de_una_instancia(logueado):
    estado = logueado.get("/api/instancias/acme/smtp").json()
    assert estado["origen"] == "entorno"
    assert estado["password_definida"] is False


def test_guardar_y_releer(logueado):
    guardado = logueado.put("/api/instancias/acme/smtp", json={**CONFIG, "password": "secreta"}).json()
    assert guardado["origen"] == "base"
    assert guardado["password_definida"] is True
    assert logueado.get("/api/instancias/acme/smtp").json() == guardado


def test_cada_instancia_tiene_su_propia_config(logueado):
    """Lo que el diseño viejo —una sola base, un solo entorno— no podía dar."""
    logueado.put("/api/instancias/acme/smtp", json={**CONFIG, "host": "smtp.acme.com"})
    logueado.put("/api/instancias/beta/smtp", json={**CONFIG, "host": "smtp.beta.com"})

    assert logueado.get("/api/instancias/acme/smtp").json()["host"] == "smtp.acme.com"
    assert logueado.get("/api/instancias/beta/smtp").json()["host"] == "smtp.beta.com"


def test_la_password_no_vuelve_nunca(logueado):
    resp = logueado.put("/api/instancias/acme/smtp", json={**CONFIG, "password": "secreta"})
    assert "secreta" not in resp.text
    assert "password" not in resp.json()


def test_editar_sin_mandar_password_la_conserva(logueado):
    """La regla delicada de esta pantalla, y acá se prueba que **el proxy no la
    rompe en el camino**: si el backoffice reenviara el modelo completo, el
    `password=None` del default llegaría a la instancia como 'borrala'."""
    logueado.put("/api/instancias/acme/smtp", json={**CONFIG, "password": "secreta"})
    estado = logueado.put("/api/instancias/acme/smtp", json={**CONFIG, "from_name": "Otro"}).json()
    assert estado["from_name"] == "Otro"
    assert estado["password_definida"] is True


def test_password_vacia_la_borra(logueado):
    logueado.put("/api/instancias/acme/smtp", json={**CONFIG, "password": "secreta"})
    estado = logueado.put("/api/instancias/acme/smtp", json={**CONFIG, "password": ""}).json()
    assert estado["password_definida"] is False


def test_la_instancia_puede_descifrar_lo_que_guardo_el_backoffice(logueado, tmp_path):
    """El punto de todo el rediseño.

    Con acceso directo a la base, el backoffice habría cifrado con SU clave y
    la instancia habría leído `password_indescifrable` sin que nada fallara a
    la vista. Acá cifra la instancia, con la suya.
    """
    from libraauth.smtp_settings import SmtpSettingsRepository
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    logueado.put("/api/instancias/acme/smtp", json={**CONFIG, "password": "hunter2"})

    sesiones = sessionmaker(bind=create_engine(f"sqlite:///{tmp_path}/acme.db"))
    guardada = SmtpSettingsRepository(sesiones).get()
    assert guardada.password == "hunter2"
    assert guardada.password_indescifrable is False


def test_error_de_validacion_de_la_instancia_llega_como_422(logueado):
    """Un 422 de la instancia tiene que llegar al formulario como 422, no
    convertido en un error genérico del backoffice."""
    resp = logueado.put("/api/instancias/acme/smtp", json={**CONFIG, "host": ""})
    assert resp.status_code == 422


def test_instancia_caida_es_502_y_dice_cual(logueado):
    """Existe en el inventario pero no contesta. No es un 500 del backoffice."""
    resp = logueado.get("/api/instancias/caida/smtp")
    assert resp.status_code == 502
    assert "caida" in resp.json()["detail"]


def test_borrar_vuelve_al_entorno(logueado):
    logueado.put("/api/instancias/acme/smtp", json={**CONFIG, "password": "secreta"})
    assert logueado.delete("/api/instancias/acme/smtp").json()["origen"] == "entorno"


# ── Usuarios ────────────────────────────────────────────────────────────────

NUEVO = {"username": "ana", "name": "Ana Pérez", "password": "clave-inicial", "role": "staff"}


def test_usuarios_de_una_instancia(logueado):
    assert logueado.get("/api/instancias/acme/usuarios").json() == []

    creado = logueado.post("/api/instancias/acme/usuarios", json=NUEVO)
    assert creado.status_code == 201
    assert creado.json()["username"] == "ana"

    assert [u["username"] for u in logueado.get("/api/instancias/acme/usuarios").json()] == ["ana"]
    # Y no se filtró a la otra instancia.
    assert logueado.get("/api/instancias/beta/usuarios").json() == []


def test_username_repetido_llega_como_409(logueado):
    logueado.post("/api/instancias/acme/usuarios", json=NUEVO)
    assert logueado.post("/api/instancias/acme/usuarios", json=NUEVO).status_code == 409


def test_baja_logica_de_un_usuario(logueado):
    uid = logueado.post("/api/instancias/acme/usuarios", json=NUEVO).json()["id"]
    resp = logueado.put(
        f"/api/instancias/acme/usuarios/{uid}",
        json={"name": "Ana P.", "role": "admin", "active": False},
    )
    assert resp.json()["active"] is False
