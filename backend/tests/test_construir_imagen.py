"""`scripts/construir_imagen.sh` arma el `docker build` y no se desincroniza del Dockerfile.

El build de la imagen vivía sólo en la memoria de quien lo hacía: tres claves
`--ssh`, dos `--build-arg` y dos tags, sin ningún archivo que lo dijera. El script
lo vuelve un comando, y estos tests cuidan lo que se rompería sin avisar: que los
ids de `--ssh` sean los que el Dockerfile monta (si el Dockerfile suma una
dependencia privada y el script no, el build falla recién en el VPS, adentro de
`uv sync`), que la imagen lleve el commit que se construyó y que un árbol sucio o
una rama equivocada no pasen en silencio.

Todo corre con `--dry-run`: no hace falta docker ni ninguna clave real.
"""
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "construir_imagen.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="hace falta bash")

CLAVES = {
    "LIBRA_SSH_KEY_LIBRACORE": "/ruta/de/prueba/uno",
    "LIBRA_SSH_KEY_LIBRAAUTH": "/ruta/de/prueba/dos",
    "LIBRA_SSH_KEY_LIBRA_UI": "/ruta/de/prueba/tres",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    """Un repo git de juguete con el script y el Dockerfile REAL copiados.

    Copiar el Dockerfile real (y no uno de prueba) es lo que hace que estos tests
    detecten una desincronización de verdad.
    """
    (tmp_path / "scripts").mkdir()
    shutil.copy2(SCRIPT, tmp_path / "scripts" / "construir_imagen.sh")
    shutil.copy2(RAIZ / "Dockerfile", tmp_path / "Dockerfile")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "inicial")
    return tmp_path


def _correr(repo: Path, *args: str, claves=CLAVES):
    entorno = {k: v for k, v in os.environ.items() if not k.startswith("LIBRA_SSH_KEY_")}
    entorno.update(claves)
    return subprocess.run(
        ["bash", str(repo / "scripts" / "construir_imagen.sh"), *args],
        capture_output=True,
        text=True,
        env=entorno,
    )


def _comando(salida: str) -> list[str]:
    return shlex.split(salida.strip().splitlines()[-1])


def _ids_del_dockerfile() -> set[str]:
    return set(re.findall(r"--mount=type=ssh,id=([A-Za-z0-9_-]+)", (RAIZ / "Dockerfile").read_text()))


def test_el_dockerfile_declara_las_tres_dependencias_privadas():
    """El control del control: sin esto, un Dockerfile sin mounts haría pasar en
    verde la comparación de abajo (vacío == vacío)."""
    assert _ids_del_dockerfile() == {"libra-ui", "libracore", "libraauth"}


def test_dry_run_arma_un_ssh_por_cada_id_del_dockerfile(repo):
    r = _correr(repo, "--dry-run", "v-prueba")
    assert r.returncode == 0, r.stderr
    cmd = _comando(r.stdout)
    assert cmd[:2] == ["docker", "build"]
    ssh = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--ssh"]
    # Una clave por id, cada una en su propio --ssh (nunca un agente con las tres).
    assert {s.split("=", 1)[0] for s in ssh} == _ids_del_dockerfile()
    assert len(ssh) == len(_ids_del_dockerfile())
    assert dict(s.split("=", 1) for s in ssh) == {
        "libracore": CLAVES["LIBRA_SSH_KEY_LIBRACORE"],
        "libraauth": CLAVES["LIBRA_SSH_KEY_LIBRAAUTH"],
        "libra-ui": CLAVES["LIBRA_SSH_KEY_LIBRA_UI"],
    }


def test_la_imagen_lleva_la_version_y_el_commit_que_se_construyo(repo):
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    r = _correr(repo, "--dry-run", "v2026.10.15-120000")
    assert r.returncode == 0, r.stderr
    cmd = _comando(r.stdout)
    build_args = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--build-arg"]
    assert sorted(build_args) == sorted(["APP_VERSION=v2026.10.15-120000", f"APP_COMMIT={commit}"])
    tags = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-t"]
    assert tags == ["libra-backoffice:v2026.10.15-120000", "libra-backoffice:latest"]
    # Los dos ARG existen en el Dockerfile: un nombre mal escrito acá pasaría el
    # build y dejaría la imagen diciendo "desconocida" en la pantalla de salud.
    dockerfile = (RAIZ / "Dockerfile").read_text()
    for nombre in ("APP_VERSION", "APP_COMMIT"):
        assert re.search(rf"^ARG {nombre}=", dockerfile, re.M)


def test_sin_tag_usa_la_fecha_y_hora(repo):
    r = _correr(repo, "--dry-run")
    assert r.returncode == 0, r.stderr
    tag = [a for a in _comando(r.stdout) if a.startswith("APP_VERSION=")][0].split("=", 1)[1]
    assert re.fullmatch(r"v\d{4}\.\d{2}\.\d{2}-\d{6}", tag)


def test_falta_una_clave_y_el_mensaje_dice_cual(repo):
    claves = {k: v for k, v in CLAVES.items() if k != "LIBRA_SSH_KEY_LIBRAAUTH"}
    r = _correr(repo, "--dry-run", claves=claves)
    assert r.returncode == 1
    assert "LIBRA_SSH_KEY_LIBRAAUTH" in r.stderr
    assert "LIBRA_SSH_KEY_LIBRACORE" not in r.stderr
    assert "docker build" not in r.stdout


def test_un_id_nuevo_en_el_dockerfile_exige_su_clave(repo):
    """El caso que motiva el script: el Dockerfile suma una dependencia privada y
    nadie actualiza el comando. Acá el script lo exige solo, por su variable."""
    dockerfile = repo / "Dockerfile"
    dockerfile.write_text(dockerfile.read_text() + "\nRUN --mount=type=ssh,id=libra-nueva true\n")
    _git(repo, "commit", "-q", "-am", "dependencia nueva")
    r = _correr(repo, "--dry-run")
    assert r.returncode == 1
    assert "LIBRA_SSH_KEY_LIBRA_NUEVA" in r.stderr


def test_un_arbol_sucio_no_se_construye(repo):
    (repo / "Dockerfile").write_text((repo / "Dockerfile").read_text() + "\n# cambio sin commitear\n")
    r = _correr(repo, "--dry-run", "v-prueba")
    assert r.returncode == 1
    assert "sin commitear" in r.stderr


def test_fuera_de_main_pide_confirmacion_explicita(repo):
    _git(repo, "checkout", "-q", "-b", "otra")
    r = _correr(repo, "--dry-run", "v-prueba")
    assert r.returncode == 1
    assert "--permitir-rama" in r.stderr
    assert _correr(repo, "--dry-run", "--permitir-rama", "v-prueba").returncode == 0


@pytest.mark.parametrize("tag", ["con espacio", "-empieza-con-guion", "a/b", "x;rm", ""])
def test_un_tag_invalido_se_rechaza(repo, tag):
    r = _correr(repo, "--dry-run", tag)
    assert r.returncode == 2
    assert "docker build" not in r.stdout


def test_una_opcion_desconocida_falla(repo):
    r = _correr(repo, "--dry-run", "--por-las-dudas")
    assert r.returncode == 2
