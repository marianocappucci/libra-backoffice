"""¿Los scripts de un producto cargan con la libracore de ESTE backoffice?

Uso::

    python -m libra_backoffice.verificar_producto <ruta-del-repo> [--etiqueta contalibra@develop]

Sale con 0 si `scripts/panel_admin.py` y `scripts/nuevo_cliente.py` importan
—o sea, si pasan su `configure()`—, 1 si alguno no, y 2 si la ruta no tiene los
dos scripts.

🔴 **Por qué existe.** El contenedor `<producto>-admin` importa esos dos
scripts del repo del producto, montados desde el host, y los ejecuta con la
libracore de la imagen del backoffice, que tiene su propio pin. Los argumentos
de `configure()` los elige el producto; los tiene que entender la libracore de
acá. Ese acoplamiento tumbó los paneles tres veces —el salto de `v1.3.0`,
`backup_zip` el 2026-08-12, `migraciones` el 2026-08-24— y las tres nos
enteramos cuando alguien abrió el panel.

El `/health` ya lo detecta, pero en producción, después del deploy. Este módulo
es el mismo chequeo movido al CI, y lo corren los dos lados:

- **cada producto**, en su PR, contra el backoffice de `main` (el workflow
  reusable `scripts-de-producto.yml`): un `configure()` nuevo se pone rojo
  antes de mergearse;
- **este repo**, en su PR y a diario, contra `main` y `develop` de cada
  producto (`scripts-de-productos.yml`): un bump del pin de acá que deje atrás
  a un producto se pone rojo antes de construir la imagen.

Hace **exactamente** el recorrido del `/health` —`Inventario.cargar_script()`,
que es lo que usa `verificar_scripts()`— y no un `import` propio: probar una
imitación dejaría pasar justo lo que el panel no perdona.

Un repo por proceso, a propósito. El import queda cacheado en `sys.modules`
bajo el nombre pelado `panel_admin`, así que verificar dos productos en el mismo
proceso haría que el segundo "cargue" el módulo del primero. El que quiera
recorrer varios, que lance un proceso por repo (así lo hace el workflow).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from importlib import metadata
from pathlib import Path

from .inventario import SCRIPTS_DEL_PRODUCTO, Inventario

# `db_filename` sólo lo usa el inventario para ubicar la base de cada instancia,
# y acá no se lista ninguna: importar los scripts no la toca. Un nombre fijo
# evita pedir una configuración que el chequeo no necesita.
_DB_FILENAME = "verificacion-ci.db"


def version_de_libracore() -> str:
    """La libracore instalada, con el commit si vino de git.

    El número solo no alcanza para leer un rojo: un tag movido o una
    instalación a mano desde una rama dan el mismo número con otro código. El
    commit sale de `direct_url.json`, que es donde pip/uv anotan de dónde
    vino un paquete instalado por URL.
    """
    try:
        dist = metadata.distribution("libracore")
    except metadata.PackageNotFoundError:
        return "no instalada"
    texto = dist.version
    try:
        crudo = dist.read_text("direct_url.json")
        commit = json.loads(crudo or "{}").get("vcs_info", {}).get("commit_id", "")
    except (OSError, ValueError):
        commit = ""
    return f"{texto} (commit {commit[:12]})" if commit else texto


def _error(mensaje: str) -> str:
    # En GitHub Actions la línea `::error::` sale como anotación en el resumen
    # del PR, que es lo que se lee sin abrir el log. Fuera de Actions sería
    # ruido.
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return f"::error title=Scripts del producto vs backoffice::{mensaje}"
    return f"ERROR: {mensaje}"


def verificar(repo_root: Path, etiqueta: str) -> int:
    scripts_dir = repo_root / "scripts"
    faltan = [f"scripts/{n}.py" for n in SCRIPTS_DEL_PRODUCTO if not (scripts_dir / f"{n}.py").is_file()]
    if faltan:
        # Salida distinta del rojo de import: una ruta equivocada no es un
        # producto roto, y confundir los dos manda a buscar al lugar que no es.
        print(_error(f"{etiqueta}: no están {', '.join(faltan)} en {repo_root}"))
        return 2

    version = version_de_libracore()
    print(f"{etiqueta}: libracore del backoffice = {version}")

    inventario = Inventario(repo_root, _DB_FILENAME)
    fallos = 0
    for nombre in SCRIPTS_DEL_PRODUCTO:
        archivo = f"scripts/{nombre}.py"
        try:
            modulo = inventario.cargar_script(nombre)
        except BaseException as exc:  # noqa: BLE001 — también SystemExit: un script que sale al importarse mata el panel igual
            fallos += 1
            traceback.print_exc(file=sys.stdout)
            print(_error(
                f"{etiqueta}: {archivo} no carga con la libracore {version} del backoffice: "
                f"{type(exc).__name__}: {exc}"
            ))
            continue

        # 🔑 Que el import no haya levantado no prueba nada si el módulo que
        # volvió es otro: un `panel_admin` que ya estaba en `sys.modules`, o uno
        # que aparece antes en el `sys.path`, da verde sin haber ejecutado el
        # `configure()` de este repo.
        cargado = Path(getattr(modulo, "__file__", "") or "").resolve()
        esperado = (scripts_dir / f"{nombre}.py").resolve()
        if cargado != esperado:
            fallos += 1
            print(_error(f"{etiqueta}: se importó {cargado} en lugar de {esperado}"))
            continue

        print(f"OK  {etiqueta}: {archivo}")

    return 1 if fallos else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m libra_backoffice.verificar_producto",
        description="Importa los scripts de un producto con la libracore de este backoffice.",
    )
    parser.add_argument("repo", type=Path, help="raíz del checkout del producto")
    parser.add_argument("--etiqueta", default="", help="cómo nombrar al producto en la salida (ej. contalibra@develop)")
    args = parser.parse_args(argv)
    repo_root = args.repo.resolve()
    return verificar(repo_root, args.etiqueta or repo_root.name)


if __name__ == "__main__":  # pragma: no cover — el cuerpo es `main()`, que la suite cubre
    sys.exit(main())
