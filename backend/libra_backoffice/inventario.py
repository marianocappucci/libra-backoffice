"""
Inventario de instancias: quiénes son y cómo se les habla.

Los seis productos son multi-instancia, pero no todos la despliegan igual, así
que hay dos backends:

- **`libracore`** — cinco productos (Contalibra, Restolibra, VentaLibra,
  Gestiolibra, MedLibra) tienen `scripts/nuevo_cliente.py`,
  `scripts/panel_admin.py` y `plans.py`. El inventario, el ciclo de vida y los
  planes salen de `libracore.admin.services`, que ya envuelve esos scripts.
- **`compose`** — LibraDesk despliega con `scripts/deploy_cliente.sh` (imagen
  pineada por instancia) y no depende de libracore, así que no hay planes ni
  `container_status`. Lo único uniforme es `clientes/<slug>/docker-compose.yml`,
  y de ahí sale el nombre del contenedor.

Lo que ambos garantizan es el `container`, que es lo que el control plane
necesita: la URL de una instancia es su nombre de contenedor en la red
`stack_stack-net`.
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Instancia:
    slug: str
    nombre: str
    container: str
    domain: str = ""
    port: int | str = ""
    plan: str = ""
    estado: str = "desconocido"
    iniciado: str = ""
    modulos_activos: int | None = None

    def dict(self) -> dict:
        return asdict(self)


class InstanciaDesconocida(LookupError):
    """No hay ninguna instancia con ese slug."""


class InventarioLibracore:
    """Los cinco productos con `libracore.provisioning`."""

    soporta_ciclo_de_vida = True
    soporta_planes = True

    def __init__(self, repo_root: Path, db_filename: str):
        from libracore.admin import services

        services.configure(repo_root=repo_root, db_filename=db_filename)
        self.servicios = services

    def listar(self) -> list[Instancia]:
        return [self._a_instancia(c) for c in self.servicios.listar_clientes()]

    def obtener(self, slug: str) -> Instancia:
        cliente = self.servicios.get_cliente(slug)
        if not cliente:
            raise InstanciaDesconocida(slug)
        return self._a_instancia(cliente)

    @staticmethod
    def _a_instancia(c: dict) -> Instancia:
        return Instancia(
            slug=c["slug"], nombre=c.get("nombre", ""), container=c["container"],
            domain=c.get("domain", ""), port=c.get("port", ""), plan=c.get("plan", ""),
            estado=c.get("estado", "desconocido"), iniciado=c.get("iniciado", ""),
            modulos_activos=c.get("modulos_activos"),
        )


class InventarioCompose:
    """LibraDesk: sólo lo que se puede leer de `clientes/<slug>/docker-compose.yml`.

    `estado` queda en `desconocido` a propósito y no se inventa un "running":
    sin `libracore.provisioning` no hay nada que consulte a Docker acá, y una
    pantalla que afirma que una instancia está viva sin haberlo verificado es
    peor que una que dice que no sabe. Quien sí lo verifica es la feature
    `salud`, preguntándole a la instancia.
    """

    soporta_ciclo_de_vida = False
    soporta_planes = False

    def __init__(self, repo_root: Path):
        self.clientes_dir = Path(repo_root) / "clientes"

    def listar(self) -> list[Instancia]:
        if not self.clientes_dir.is_dir():
            return []
        instancias = []
        for d in sorted(self.clientes_dir.iterdir()):
            if d.is_dir() and (d / "docker-compose.yml").is_file():
                instancias.append(self._leer(d))
        return instancias

    def obtener(self, slug: str) -> Instancia:
        d = self.clientes_dir / slug
        if not (d / "docker-compose.yml").is_file():
            raise InstanciaDesconocida(slug)
        return self._leer(d)

    def _leer(self, d: Path) -> Instancia:
        compose = yaml.safe_load((d / "docker-compose.yml").read_text(encoding="utf-8")) or {}
        servicios = compose.get("services") or {}
        # El primer servicio del compose es la app; los `container_name` de esta
        # familia son explícitos, y si faltara, el default de Docker Compose es
        # impredecible desde afuera — mejor decirlo que adivinarlo.
        container = ""
        for definicion in servicios.values():
            container = (definicion or {}).get("container_name", "")
            if container:
                break

        nombre, domain = d.name, ""
        meta = d / "cliente.json"
        if meta.is_file():
            try:
                datos = json.loads(meta.read_text(encoding="utf-8"))
                nombre = datos.get("nombre") or nombre
                domain = datos.get("domain") or ""
            except (json.JSONDecodeError, OSError):
                pass

        return Instancia(slug=d.name, nombre=nombre, container=container, domain=domain)


def construir_inventario(settings):
    if settings.instancias_backend == "compose":
        return InventarioCompose(settings.repo_root)
    return InventarioLibracore(settings.repo_root, settings.db_filename)
