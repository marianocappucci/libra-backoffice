"""Las cabeceras de seguridad del backoffice, con la política de SPA.

El middleware vive en libracore y tiene sus propios tests. Lo que cuida este
archivo es **qué política se monta acá**. Hasta el 2026-09-12 el backoffice
montaba `SecurityHeadersMiddleware` sin argumentos, así que servía su SPA con la
CSP de las apps Jinja2: `'unsafe-inline'` en `script-src` y `cdn.jsdelivr.net`,
dos permisos que una SPA de Vite no usa y que sólo sirven a un XSS inyectado.
"""
from fastapi.testclient import TestClient
from libracore.security_headers import CSP, CSP_SPA

from libra_backoffice.app import create_app

from .conftest import construir_settings


def test_las_respuestas_traen_los_headers_de_seguridad(cliente):
    r = cliente.get("/health")
    assert r.headers["Content-Security-Policy"] == CSP_SPA
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "includeSubDomains" in r.headers["Strict-Transport-Security"]


def test_es_la_politica_de_spa_y_no_la_de_las_apps_jinja(cliente):
    csp = cliente.get("/health").headers["Content-Security-Policy"]
    script_src = csp.split("script-src")[1].split(";")[0]
    assert "'unsafe-inline'" not in script_src
    assert "jsdelivr" not in csp
    # Control positivo: la de Jinja sí tiene las dos cosas. Sin esto, un
    # `CSP_SPA` que un día las volviera a traer pasaría igual.
    assert "'unsafe-inline'" in CSP.split("script-src")[1].split(";")[0]
    assert "jsdelivr" in CSP


def test_tambien_en_una_respuesta_de_error(cliente):
    """Un 401 también sale envuelto: el middleware es el más externo."""
    r = cliente.get("/api/salud")
    assert r.status_code == 401
    assert r.headers["Content-Security-Policy"] == CSP_SPA


def test_el_index_de_la_spa_sale_con_la_politica_de_spa(tmp_path, inventario):
    """El documento que carga el navegador es el que importa: la CSP de la
    respuesta del `index.html` es la que rige los scripts de la página."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><div id="root"></div><script type="module" src="/assets/app.js"></script>'
    )
    (dist / "assets" / "app.js").write_text("console.log('ok')")
    app = create_app(construir_settings(tmp_path), inventario=inventario, frontend_dist=str(dist))
    c = TestClient(app, base_url="https://testserver")
    for ruta in ("/", "/instancias/acme/smtp", "/assets/app.js"):
        assert c.get(ruta).headers["Content-Security-Policy"] == CSP_SPA, ruta
