"""El `/health` toca los scripts del producto, y el pin los entiende.

🔴 **Este archivo existe porque el mismo defecto entró tres veces.** El
backoffice importa `scripts/panel_admin.py` y `scripts/nuevo_cliente.py` del
repo del producto —montados desde el host— y los ejecuta con la libracore de
ESTE contenedor. Cuando un producto le suma un argumento a `configure()` y sube
el pin *de su repo*, acá no cambia nada: el panel revienta con un `TypeError`
en el primer request.

| Fecha | Argumento | Alcance |
|---|---|---|
| 2026-08-12 | `backup_zip` | los seis paneles, 500 en `/api/salud` |
| 2026-08-24 | `migraciones` | cinco de ocho, panel vacío y sin alta |

Las dos veces el contenedor siguió `healthy`, porque el import es diferido y el
`/health` no lo tocaba. Los tests de acá cubren los dos lados: que el `/health`
se ponga rojo cuando los scripts no cargan, y que la libracore **instalada**
entienda lo que los productos le pasan hoy.
"""
import sys

import pytest
from fastapi.testclient import TestClient

from libra_backoffice.app import create_app
from libra_backoffice.inventario import Inventario

from .conftest import construir_settings


@pytest.fixture
def sin_scripts_importados():
    """Deja `sys.modules`/`sys.path` como estaban.

    Hace falta de verdad: un import exitoso queda cacheado en `sys.modules`, así
    que sin esto el test del script roto pasaría en verde por haber corrido
    después del sano — leyendo el módulo viejo y no el del `tmp_path` nuevo.
    """
    path_previo = list(sys.path)
    yield
    for modulo in ("panel_admin", "nuevo_cliente"):
        sys.modules.pop(modulo, None)
    sys.path[:] = path_previo


def _repo_de_producto(tmp_path, *, panel="", nuevo=""):
    scripts = tmp_path / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "panel_admin.py").write_text(panel, encoding="utf-8")
    (scripts / "nuevo_cliente.py").write_text(nuevo, encoding="utf-8")
    return tmp_path


# ── El mecanismo real, contra scripts de verdad ─────────────────────────────

def test_verificar_scripts_pasa_cuando_los_dos_importan(tmp_path, sin_scripts_importados):
    """El control positivo. Sin él, el test de abajo pasa aunque
    `verificar_scripts()` levantara SIEMPRE — incluso si no importara nada."""
    inventario = Inventario(_repo_de_producto(tmp_path), "producto.db")

    inventario.verificar_scripts()


def test_verificar_scripts_levanta_si_el_panel_no_importa(tmp_path, sin_scripts_importados):
    """El caso del 2026-08-24, reproducido: el `configure()` del producto pasa
    un argumento que esta libracore no conoce."""
    repo = _repo_de_producto(
        tmp_path,
        panel="raise TypeError(\"configure() got an unexpected keyword argument 'migraciones'\")\n",
    )
    inventario = Inventario(repo, "producto.db")

    with pytest.raises(TypeError, match="migraciones"):
        inventario.verificar_scripts()


def test_verificar_scripts_levanta_si_el_del_alta_no_importa(tmp_path, sin_scripts_importados):
    """`nuevo_cliente.py` y no sólo `panel_admin.py`.

    El `configure()` que rompe está en los dos archivos. Chequear uno solo
    dejaría el alta muerta con el semáforo en verde, que es la mitad exacta del
    defecto que este trabajo cierra."""
    repo = _repo_de_producto(tmp_path, nuevo="raise TypeError('configure() ... nuevo_cliente')\n")
    inventario = Inventario(repo, "producto.db")

    with pytest.raises(TypeError, match="nuevo_cliente"):
        inventario.verificar_scripts()


# ── El cableado: qué contesta el endpoint ───────────────────────────────────

class _InventarioQueNoImporta:
    def verificar_scripts(self):
        raise TypeError("configure() got an unexpected keyword argument 'migraciones'")

    def listar(self):
        raise AssertionError("no debería llegar acá")


def test_health_devuelve_503_cuando_los_scripts_no_cargan(tmp_path):
    """Lo que lee el healthcheck de Docker es el código, no el cuerpo."""
    app = create_app(construir_settings(tmp_path), inventario=_InventarioQueNoImporta())

    with TestClient(app, base_url="https://testserver") as cliente:
        resp = cliente.get("/health")

    assert resp.status_code == 503, resp.text
    cuerpo = resp.json()
    assert cuerpo["ok"] is False
    # El motivo tiene que viajar: un 503 pelado manda a leer logs de contenedor
    # a las tres de la mañana para enterarse de que era el pin.
    assert "migraciones" in cuerpo["error"]
    assert "pyproject.toml" in cuerpo["detalle"]


def test_health_sigue_en_200_cuando_los_scripts_cargan(cliente):
    """El otro lado del par. Si `/health` diera 503 siempre, el chequeo nuevo
    volvería a los ocho contenedores rojos y nadie miraría el semáforo nunca
    más."""
    resp = cliente.get("/health")

    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


# ── El pin, contra la libracore instalada ───────────────────────────────────

def test_la_libracore_instalada_entiende_las_migraciones_del_deploy():
    """El guard del pin, mirado desde el lado del argumento nuevo.

    🔴 **No alcanza con `inspect.signature`.** El argumento existe desde
    `v1.48.0`, pero ahí es `tuple[str, ...]` — UN comando. Gestiolibra y
    MedLibra pasan DOS cadenas de Alembic (la de LibraGenda y la propia), y la
    forma anidada recién existe en `v1.51.0`. Un pin en `v1.48.0` pasaría un
    test de firma y dejaría esos dos paneles rotos igual.

    Por eso el test **llama** a `configure()`: la única versión que acepta la
    forma anidada y rechaza la plana es la que hace falta.
    """
    from libracore import provisioning

    cfg_previo = provisioning._cfg
    try:
        provisioning.configure(
            product_name="Producto", image_name="producto",
            container_prefix="producto", db_filename="producto.db",
            repo_root="/tmp/producto-de-prueba",
            # Exactamente lo que pasan Gestiolibra y MedLibra.
            migraciones=(("libragenda-migrar", "upgrade"), ("alembic", "upgrade", "head")),
        )

        with pytest.raises(TypeError):
            # La forma plana: `v1.48.0` la aceptaba y la corría carácter por
            # carácter. Que ACÁ levante es lo que distingue el pin bueno.
            provisioning.configure(
                product_name="Producto", image_name="producto",
                container_prefix="producto", db_filename="producto.db",
                repo_root="/tmp/producto-de-prueba",
                migraciones=("alembic", "upgrade", "head"),
            )
    except TypeError as exc:
        if "migraciones" in str(exc) and "unexpected keyword" in str(exc):
            pytest.fail(
                "La libracore instalada no acepta `migraciones` en "
                "provisioning.configure(): los paneles de LibraDesk, "
                "Gestiolibra, LibraCargo, LibraClub y MedLibra devuelven 500 al "
                "listar instancias. Hace falta el pin >= v1.51.0 en "
                "backend/pyproject.toml."
            )
        raise
    finally:
        provisioning._cfg = cfg_previo
