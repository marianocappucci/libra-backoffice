"""
La pantalla de SMTP es la razón por la que existe este proyecto, y su regla
delicada es la de la contraseña: la clave `password` ausente significa "dejala
como está", presente y vacía significa "borrala". Estos tests fijan esa
semántica del lado del backend; el componente de libra-ui la fija del lado del
formulario (`cuerpoAGuardar`).
"""
CONFIG = {
    "host": "smtp.miempresa.com", "port": 587, "user": "cuenta@miempresa.com",
    "from_email": "no-responder@miempresa.com", "from_name": "Soporte",
}


def test_smtp_pide_sesion(cliente):
    assert cliente.get("/api/smtp").status_code == 401


def test_estado_inicial_sale_del_entorno(logueado):
    estado = logueado.get("/api/smtp").json()
    assert estado["origen"] == "entorno"
    assert estado["password_definida"] is False


def test_guardar_y_releer(logueado):
    guardado = logueado.put("/api/smtp", json={**CONFIG, "password": "secreta"}).json()
    assert guardado["origen"] == "base"
    assert guardado["host"] == CONFIG["host"]
    assert guardado["password_definida"] is True

    releido = logueado.get("/api/smtp").json()
    assert releido == guardado


def test_la_password_nunca_vuelve_en_la_respuesta(logueado):
    resp = logueado.put("/api/smtp", json={**CONFIG, "password": "secreta"})
    assert "secreta" not in resp.text
    assert "password" not in resp.json()


def test_editar_sin_mandar_password_la_conserva(logueado):
    logueado.put("/api/smtp", json={**CONFIG, "password": "secreta"})
    # El formulario manda el resto de los campos sin la clave `password`.
    estado = logueado.put("/api/smtp", json={**CONFIG, "from_name": "Otro"}).json()
    assert estado["from_name"] == "Otro"
    assert estado["password_definida"] is True


def test_password_vacia_la_borra(logueado):
    logueado.put("/api/smtp", json={**CONFIG, "password": "secreta"})
    estado = logueado.put("/api/smtp", json={**CONFIG, "password": ""}).json()
    assert estado["password_definida"] is False


def test_host_vacio_es_422(logueado):
    resp = logueado.put("/api/smtp", json={**CONFIG, "host": ""})
    assert resp.status_code == 422


def test_delete_vuelve_al_entorno(logueado):
    logueado.put("/api/smtp", json={**CONFIG, "password": "secreta"})
    estado = logueado.delete("/api/smtp").json()
    assert estado["origen"] == "entorno"
    assert estado["password_definida"] is False


def test_la_password_queda_cifrada_en_la_base(logueado, db_instancia):
    """El punto del cifrado en reposo: el `.db` por sí solo no alcanza para
    mandar correo en nombre del cliente."""
    import sqlite3

    logueado.put("/api/smtp", json={**CONFIG, "password": "secreta"})
    con = sqlite3.connect(db_instancia)
    guardada = con.execute("SELECT password_cifrada FROM smtp_settings").fetchone()[0]
    con.close()
    assert "secreta" not in guardada
    assert guardada.startswith("v1:")
