"""
El cliente HTTP con el que el backoffice le habla a una instancia.

**Es el corazón del diseño.** El backoffice no abre la base de ninguna
instancia: le pide a cada una que haga el trabajo en su propio proceso. La
contraseña SMTP la sigue cifrando la instancia con su propia clave —derivada de
su `SECRET_KEY`—, que es lo que hace posible administrar N instancias desde un
solo proceso. El intento de leer las bases directamente se descartó justamente
porque un proceso no puede tener N secretos en su entorno.

La autenticación es el token de servicio de `libraauth v0.7.0`
(`X-Internal-Auth`). Viaja por la red interna de Docker, entre contenedores de
`stack_stack-net`: nunca sale a internet.
"""
import httpx


class InstanciaInalcanzable(Exception):
    """La instancia no contestó. No es un error del backoffice."""

    def __init__(self, slug: str, detalle: str):
        self.slug = slug
        self.detalle = detalle
        super().__init__(f"La instancia '{slug}' no responde: {detalle}")


class RespuestaDeInstancia(Exception):
    """La instancia contestó, pero con un error. Se propaga tal cual."""

    def __init__(self, status_code: int, detalle: str):
        self.status_code = status_code
        self.detalle = detalle
        super().__init__(detalle)


class ClienteInstancia:
    def __init__(self, *, token: str, puerto: int = 8000, timeout: float = 5.0, transport=None):
        self._token = token
        self._puerto = puerto
        self._timeout = timeout
        # Costura para los tests: con un `ASGITransport` la suite le habla a una
        # instancia FastAPI de verdad —con el router real de libraauth y su
        # guard real— en vez de a un doble que podría estar de acuerdo con un
        # contrato equivocado. En producción es siempre `None`.
        self._transport = transport

    def url(self, instancia, path: str) -> str:
        return f"http://{instancia.container}:{self._puerto}{path}"

    async def pedir(self, metodo: str, instancia, path: str, json=None, esperar_json: bool = True):
        """Devuelve el JSON de la instancia, o traduce el fallo.

        Un timeout o un DNS que no resuelve **no** son un 500 del backoffice:
        son "esa instancia está caída", que es información y no una falla. El
        router lo convierte en 502 con el slug adentro, para que la pantalla
        pueda decir cuál.

        `esperar_json=False` para los chequeos donde sólo importa el código de
        estado. No es un detalle: los productos de esta familia sirven una SPA
        con fallback, así que **cualquier ruta que no exista devuelve 200 con
        HTML**. Con `esperar_json=True` eso reventaba en `resp.json()` y salía
        como un 500 del backoffice; peor todavía, si el cuerpo hubiera sido
        JSON el chequeo habría dado "ok" sin haber tocado la app.
        """
        url = self.url(instancia, path)
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as cliente:
                resp = await cliente.request(
                    metodo, url, json=json, headers={"X-Internal-Auth": self._token},
                )
        except httpx.HTTPError as exc:
            raise InstanciaInalcanzable(instancia.slug, f"{type(exc).__name__}: {exc}") from exc

        if resp.status_code >= 400:
            raise RespuestaDeInstancia(resp.status_code, _detalle(resp))
        if not esperar_json:
            return None
        try:
            return resp.json()
        except ValueError:
            # 200 con un cuerpo que no es JSON: casi siempre es el fallback de
            # la SPA respondiendo por una ruta que no existe, o sea que el path
            # configurado para este producto está mal.
            raise RespuestaDeInstancia(
                resp.status_code,
                f"La instancia contestó 200 pero el cuerpo no es JSON en {path!r}. "
                "Suele ser el fallback de la SPA: revisar SMTP_PATH/USERS_PATH/"
                "HEALTH_PATH para este producto.",
            )


def _detalle(resp: httpx.Response) -> str:
    try:
        cuerpo = resp.json()
    except ValueError:
        return resp.text[:200] or f"HTTP {resp.status_code}"
    if isinstance(cuerpo, dict) and "detail" in cuerpo:
        return str(cuerpo["detail"])
    return f"HTTP {resp.status_code}"
