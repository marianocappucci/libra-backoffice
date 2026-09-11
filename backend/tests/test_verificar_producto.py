"""El chequeo de CI que importa los scripts de un producto con NUESTRA libracore.

Lo corren los PRs de los productos (contra el backoffice de `main`) y los de este
repo (contra `main` y `develop` de cada producto). Si este módulo diera verde de
más, el acoplamiento que tumbó los paneles tres veces vuelve a pasar sin aviso,
así que cada rojo que promete tiene su test, y cada test su control positivo.
"""
import sys
import types

import pytest

from libra_backoffice import verificar_producto

# Lo que hace un producto de verdad, contra la libracore INSTALADA: no un
# `raise` de mentira sino el `configure()` real con un argumento que no existe.
_ARGUMENTOS = (
    "product_name='Producto', image_name='producto', container_prefix='producto', "
    "db_filename='producto.db', repo_root='/tmp/producto-de-prueba'"
)
SCRIPT_SANO = f"from libracore.provisioning import configure\nconfigure({_ARGUMENTOS})\n"
SCRIPT_CON_ARGUMENTO_NUEVO = (
    f"from libracore.provisioning import configure\nconfigure({_ARGUMENTOS}, argumento_que_no_existe=1)\n"
)


@pytest.fixture(autouse=True)
def fuera_de_actions(monkeypatch):
    """La salida cambia de prefijo dentro de GitHub Actions (`::error` en vez de
    `ERROR:`), y el runner define `GITHUB_ACTIONS=true` para toda la suite.

    Sin esto los tests pasaban en local y fallaban en el CI —pasó en el primer
    push de este archivo—: asertaban sobre el prefijo de un entorno que no era
    el que corría. El caso de Actions tiene su propio test, que la vuelve a
    poner.
    """
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


@pytest.fixture(autouse=True)
def sin_scripts_importados():
    """Deja `sys.modules`, `sys.path` y el `_cfg` del motor como estaban.

    El import exitoso queda cacheado bajo el nombre pelado `panel_admin`: sin
    esto, el test del script roto pasaría en verde por correr después del sano.
    """
    from libracore import provisioning

    path_previo = list(sys.path)
    cfg_previo = provisioning._cfg
    for modulo in ("panel_admin", "nuevo_cliente"):
        sys.modules.pop(modulo, None)
    yield
    for modulo in ("panel_admin", "nuevo_cliente"):
        sys.modules.pop(modulo, None)
    sys.path[:] = path_previo
    provisioning._cfg = cfg_previo


def _producto(tmp_path, *, panel=SCRIPT_SANO, nuevo=SCRIPT_SANO):
    scripts = tmp_path / "producto" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "panel_admin.py").write_text(panel, encoding="utf-8")
    (scripts / "nuevo_cliente.py").write_text(nuevo, encoding="utf-8")
    return scripts.parent


def test_verde_cuando_los_dos_scripts_cargan(tmp_path, capsys):
    """El control positivo: sin él, los rojos de abajo pasarían aunque el
    módulo diera 1 siempre."""
    assert verificar_producto.main([str(_producto(tmp_path)), "--etiqueta", "prueba@develop"]) == 0

    salida = capsys.readouterr().out
    assert "OK  prueba@develop: scripts/panel_admin.py" in salida
    assert "OK  prueba@develop: scripts/nuevo_cliente.py" in salida


def test_rojo_si_el_panel_pasa_un_argumento_que_la_libracore_no_conoce(tmp_path, capsys):
    """El 2026-08-24, reproducido con el `configure()` real. El mensaje tiene
    que decir QUÉ script, CON QUÉ libracore y QUÉ error: es lo único que se lee
    en la anotación del PR."""
    repo = _producto(tmp_path, panel=SCRIPT_CON_ARGUMENTO_NUEVO)

    assert verificar_producto.main([str(repo), "--etiqueta", "prueba@develop"]) == 1

    salida = capsys.readouterr().out
    linea = next(renglon for renglon in salida.splitlines() if renglon.startswith("ERROR:"))
    assert "scripts/panel_admin.py" in linea
    assert verificar_producto.version_de_libracore() in linea
    assert "argumento_que_no_existe" in linea
    # Y el otro script se sigue reportando por separado: un rojo en uno no
    # tiene que esconder el estado del otro.
    assert "OK  prueba@develop: scripts/nuevo_cliente.py" in salida


def test_rojo_si_el_del_alta_no_carga(tmp_path, capsys):
    """`nuevo_cliente.py` y no sólo el panel: el `configure()` que rompe está en
    los dos, y mirar uno solo deja el alta muerta con el semáforo en verde."""
    repo = _producto(tmp_path, nuevo=SCRIPT_CON_ARGUMENTO_NUEVO)

    assert verificar_producto.main([str(repo)]) == 1

    salida = capsys.readouterr().out
    assert "OK  producto: scripts/panel_admin.py" in salida
    assert "producto: scripts/nuevo_cliente.py no carga" in salida


def test_rojo_si_el_script_sale_al_importarse(tmp_path, capsys):
    """Un `sys.exit()` al importar también mata el panel, y no es `Exception`."""
    repo = _producto(tmp_path, panel="import sys\nsys.exit(3)\n")

    assert verificar_producto.main([str(repo)]) == 1
    assert "SystemExit" in capsys.readouterr().out


def test_rojo_si_el_modulo_importado_no_es_el_del_repo(tmp_path, capsys):
    """El verde que no prueba nada: un `panel_admin` que ya estaba cargado
    —de otro producto, en el mismo proceso— haría que el import "funcione" sin
    ejecutar el `configure()` de este repo."""
    ajeno = types.ModuleType("panel_admin")
    ajeno.__file__ = str(tmp_path / "otro-producto" / "scripts" / "panel_admin.py")
    sys.modules["panel_admin"] = ajeno

    assert verificar_producto.main([str(_producto(tmp_path))]) == 1
    assert "en lugar de" in capsys.readouterr().out


def test_codigo_propio_si_la_ruta_no_es_un_producto(tmp_path, capsys):
    """Una ruta equivocada no es un producto roto: sale con 2 y lo dice."""
    assert verificar_producto.main([str(tmp_path)]) == 2
    assert "no están scripts/panel_admin.py, scripts/nuevo_cliente.py" in capsys.readouterr().out


def test_la_anotacion_de_actions_solo_dentro_de_actions(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    repo = _producto(tmp_path, panel=SCRIPT_CON_ARGUMENTO_NUEVO)

    assert verificar_producto.main([str(repo)]) == 1
    assert "::error title=Scripts del producto vs backoffice::" in capsys.readouterr().out


def test_la_version_informada_es_la_instalada():
    """El número tiene que ser el del paquete que corrió, no el del pin escrito:
    si difieren, la diferencia es justamente lo que hay que ver."""
    from importlib import metadata

    assert verificar_producto.version_de_libracore().startswith(metadata.version("libracore"))


def test_version_cuando_libracore_no_esta(monkeypatch):
    from importlib import metadata

    def no_esta(nombre):
        raise metadata.PackageNotFoundError(nombre)

    monkeypatch.setattr(verificar_producto.metadata, "distribution", no_esta)
    assert verificar_producto.version_de_libracore() == "no instalada"
