"""
El cliente HTTP con el que la consola de revendedores le habla a los backoffices.

**Por qué a los backoffices y no a las instancias.** El corte de servicio escribe en el disco de cada instancia, y eso
lo resuelve `libracore.admin.services`, cuyo `configure()` guarda estado global de un solo producto: un proceso no
puede atender a los nueve. Cada backoffice ya lo hace para el suyo, y la consola se lo pide por `stack_stack-net`.

El token (`X-Consola-Token`) sólo abre `/api/consola`: listar y suspender o activar. 🔴 Nunca se loguea.
"""
import httpx

from .settings import ProductoDeConsola


class BackofficeInalcanzable(Exception):
    """El backoffice de ese producto no contestó, o contestó con un error."""

    def __init__(self, producto: str, detalle: str):
        self.producto = producto
        self.detalle = detalle
        super().__init__(f"{producto}: {detalle}")


class ClienteConsola:
    def __init__(self, productos: tuple[ProductoDeConsola, ...], token: str, *, timeout: float = 5.0, transport=None):
        self._productos = {p.slug: p for p in productos}
        self._token = token
        self._timeout = timeout
        self._transport = transport

    @property
    def productos(self) -> list[ProductoDeConsola]:
        return list(self._productos.values())

    def conoce(self, producto: str) -> bool:
        return producto in self._productos

    async def _pedir(self, producto: str, metodo: str, ruta: str, cuerpo: dict | None = None) -> dict:
        destino = self._productos[producto]
        try:
            async with httpx.AsyncClient(
                base_url=destino.url, timeout=self._timeout, transport=self._transport,
                headers={"X-Consola-Token": self._token},
            ) as cliente:
                respuesta = await cliente.request(metodo, ruta, json=cuerpo)
        except httpx.HTTPError as exc:
            raise BackofficeInalcanzable(producto, f"no contesta ({type(exc).__name__})") from exc
        if respuesta.status_code >= 400:
            raise BackofficeInalcanzable(producto, f"contestó {respuesta.status_code}")
        return respuesta.json()

    async def instancias(self, producto: str) -> list[dict]:
        return (await self._pedir(producto, "GET", "/api/consola/instancias"))["instancias"]

    async def cambiar_estado(self, producto: str, slug: str, accion: str, mensaje: str = "") -> None:
        await self._pedir(producto, "POST", f"/api/consola/instancias/{slug}/estado",
                          {"accion": accion, "mensaje": mensaje})
