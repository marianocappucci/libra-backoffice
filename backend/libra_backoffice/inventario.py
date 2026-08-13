"""
Inventario de instancias: quiénes son y cómo se les habla.

**Los seis productos son multi-instancia y se administran igual.** Todos tienen
`scripts/nuevo_cliente.py`, `scripts/panel_admin.py` y `plans.py`, así que el
inventario, el ciclo de vida y los planes salen siempre de
`libracore.admin.services`, que ya envuelve esos scripts.

> Hubo brevemente un segundo backend que leía `clientes/<slug>/docker-compose.yml`
> para LibraDesk, que era el único sin provisioning. Se eliminó: la decisión es
> que los seis funcionen igual, así que LibraDesk se portó al estándar en vez de
> que el backoffice tolerara su divergencia. Un `if` menos acá es un modo menos
> que probar seis veces.

Lo que el inventario garantiza es el `container`, que es lo que el control plane
necesita: la URL de una instancia es su nombre de contenedor en la red
`stack_stack-net`.
"""
from dataclasses import asdict, dataclass
from pathlib import Path


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
    # Corte comercial, distinto de `estado`. `estado` es el contenedor (running
    # / exited); `servicio_estado` es si el cliente puede usar el sistema. Un
    # contenedor `running` suspendido devuelve 503 a todo, así que mostrar sólo
    # uno de los dos ejes da una pantalla que dice "todo bien" sobre un cliente
    # que no puede entrar.
    servicio_estado: str = "activo"
    servicio_mensaje: str = ""

    def dict(self) -> dict:
        return asdict(self)


class InstanciaDesconocida(LookupError):
    """No hay ninguna instancia con ese slug."""


class Inventario:
    """Las instancias de un producto, vía `libracore.admin.services`."""

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
            # `or` y no un default del `.get`: una libracore vieja devuelve la
            # clave ausente, pero un `config.json` con el campo vacío devuelve
            # "" — y una instancia sin corte configurado está activa.
            servicio_estado=c.get("servicio_estado") or "activo",
            servicio_mensaje=c.get("servicio_mensaje") or "",
        )


def construir_inventario(settings) -> Inventario:
    return Inventario(settings.repo_root, settings.db_filename)
