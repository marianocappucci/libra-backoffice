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

**Una credencial por instancia (libracore v1.183.0, ADR-071).** Cada instancia
tiene su propio `LIBRA_SERVICE_TOKEN` en su compose (o su `.env`), y el
backoffice lo lee del disco **en cada request** con
`libracore.admin.services.token_de_servicio(slug)`: sin caché, para que una
rotación (`panel_admin.py token-servicio <slug> --rotar`) se vea enseguida y no
pida reiniciar el backoffice. Mientras haya instancias sin token propio (las
anteriores al ADR-071, hasta que se roten), se les manda el global
(`LIBRA_SERVICE_TOKEN` del backoffice). Ver `credencial()` y `pedir()`.
"""
import hmac
from collections.abc import Callable

import httpx

#: `propio`: la instancia tiene un token suyo, distinto del global. `compartido`:
#: tiene uno, pero es el mismo valor que el global (una instancia anterior al
#: ADR-071 que todavía no se rotó). `ausente`: el compose no tiene ninguno.
PROPIO, COMPARTIDO, AUSENTE = "propio", "compartido", "ausente"


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


class SinCredencial(RespuestaDeInstancia):
    """El backoffice no tiene con qué autenticarse ante esta instancia: no tiene
    token propio y no hay global. Es de esa instancia y no del backoffice, así
    que sale como su error (503 con el slug) y las demás siguen andando."""

    def __init__(self, slug: str):
        self.slug = slug
        super().__init__(
            503,
            f"El backoffice no tiene credencial para la instancia '{slug}': su compose no tiene "
            "LIBRA_SERVICE_TOKEN y el backoffice no tiene uno global de respaldo. Generarle uno "
            f"con `panel_admin.py token-servicio {slug} --rotar`.",
        )


def _iguales(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class ClienteInstancia:
    def __init__(
        self,
        *,
        token: str = "",
        token_de_instancia: Callable[[str], str | None] | None = None,
        anterior_de_instancia: Callable[[str], str | None] | None = None,
        puerto: int = 8000,
        timeout: float = 5.0,
        transport=None,
    ):
        # `token` es el global (`settings.service_token`): el respaldo de las
        # instancias sin token propio y el valor viejo durante una rotación.
        # `token_de_instancia(slug)` lee el propio del disco; en producción es
        # `libracore.admin.services.token_de_servicio`. Sin él (los tests que no
        # lo prueban), todas usan el global, como antes del ADR-071.
        self._token = token or ""
        self._token_de_instancia = token_de_instancia
        # `anterior_de_instancia(slug)`: el `LIBRA_SERVICE_TOKEN_ANTERIOR` de la instancia (el que
        # deja `--rotar`), primer respaldo ante un 401 con el propio. Ver `respaldos()`.
        self._anterior_de_instancia = anterior_de_instancia
        self._puerto = puerto
        self._timeout = timeout
        # Costura para los tests: con un `ASGITransport` la suite le habla a una
        # instancia FastAPI de verdad —con el router real de libraauth y su
        # guard real— en vez de a un doble que podría estar de acuerdo con un
        # contrato equivocado. En producción es siempre `None`.
        self._transport = transport

    def url(self, instancia, path: str) -> str:
        return f"http://{instancia.container}:{self._puerto}{path}"

    def _propio(self, slug: str) -> str:
        if self._token_de_instancia is None:
            return ""
        return (self._token_de_instancia(slug) or "").strip()

    def credencial(self, slug: str) -> tuple[str, bool]:
        """`(token a mandar, si es el propio de la instancia)`. Se lee cada vez: sin caché."""
        propio = self._propio(slug)
        if propio:
            return propio, True
        if self._token:
            return self._token, False
        raise SinCredencial(slug)

    def respaldos(self, slug: str, probado: str):
        """Los tokens a probar, en orden, después de un 401 con el propio: a lo sumo dos.

        Es la ventana de una rotación: el compose ya tiene el valor nuevo y el
        contenedor, hasta que el `up -d` lo recrea, todavía conoce el viejo. El
        viejo es el `LIBRA_SERVICE_TOKEN_ANTERIOR` que dejó `--rotar` y, si no
        hay (o tampoco entra), el global (en la primera rotación el viejo es el
        global). Se saltea lo vacío y lo ya probado. Generador: el anterior se
        lee del disco recién si hace falta.
        """
        probados = [probado]
        lectores = (
            lambda: (self._anterior_de_instancia(slug) or "").strip() if self._anterior_de_instancia else "",
            lambda: self._token,
        )
        for leer in lectores:
            candidato = leer()
            if candidato and not any(_iguales(candidato, p) for p in probados):
                probados.append(candidato)
                yield candidato

    def estado_token(self, slug: str) -> str:
        """`propio` / `compartido` / `ausente`, sin exponer ningún valor."""
        propio = self._propio(slug)
        if not propio:
            return AUSENTE
        return COMPARTIDO if self._token and _iguales(propio, self._token) else PROPIO

    async def pedir(
        self, metodo: str, instancia, path: str, json=None, esperar_json: bool = True, *, archivos=None, crudo: bool = False,
    ):
        """Devuelve el JSON de la instancia, o traduce el fallo.

        `archivos` es un `{campo: (nombre, bytes, tipo)}` que se manda como `multipart/form-data` (el logo de la marca, ADR-092 de
        libracore): bytes en memoria, así que un reintento ante el 401 de una rotación los vuelve a mandar enteros. `crudo=True` devuelve
        `(tipo, bytes)` en vez de interpretar un JSON: es la vista previa del logo, que la instancia sirve como `image/png`.

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
        token, es_propio = self.credencial(instancia.slug)
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as cliente:
                resp = await cliente.request(
                    metodo, url, json=json, files=archivos, headers={"X-Internal-Auth": token},
                )
                # La ventana de una rotación: sólo ante un 401 con el propio, el
                # anterior de la instancia y después el global, sin repetir un
                # valor (dos reintentos como máximo, ver `respaldos()`). Ningún
                # otro código se reintenta (un 403 o un 422 son respuestas, no
                # credenciales viejas) y nada de esto se loguea.
                if resp.status_code == 401 and es_propio:
                    for respaldo in self.respaldos(instancia.slug, token):
                        resp = await cliente.request(
                            metodo, url, json=json, files=archivos, headers={"X-Internal-Auth": respaldo},
                        )
                        if resp.status_code != 401:
                            break
        except httpx.HTTPError as exc:
            raise InstanciaInalcanzable(instancia.slug, f"{type(exc).__name__}: {exc}") from exc

        if resp.status_code >= 400:
            raise RespuestaDeInstancia(resp.status_code, _detalle(resp))
        if crudo:
            return resp.headers.get("content-type", ""), resp.content
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
