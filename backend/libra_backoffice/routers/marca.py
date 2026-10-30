"""«Marca» de una instancia: el nombre, el logo, el color y los Términos propios con los que un revendedor la vende como suya (feature `marca`).

Todo lo de acá es proxy contra la API de la propia instancia (`libracore.marca_router`, ADR-092, y `libracore.terminos_propios`, ADR-093), nunca
acceso a sus archivos: la marca vive en el `config.json` y el volumen de ESA instancia, igual que su correo (ver `cliente_instancia.py`). A
diferencia de «Apariencia», que es UNA elección para toda la suite, la marca es de una instancia: las rutas cuelgan de
`/api/instancias/{slug}/marca`.

## 🔴 Lo que este router evita: dejar a los usuarios de un cliente sin poder entrar

Con marca propia, la instancia **tiene que** tener Términos propios (libraauth ADR-030: `exigir_propio`); si no los tiene, queda frenada y
nadie puede aceptar. Por eso el orden importa: **primero los términos, después la marca**. Guardar el nombre, un color o el logo en una
instancia que todavía no es de marca propia y no tiene términos se rechaza con `409 terminos_primero`, salvo que quien opera diga
explícitamente (`sin_terminos`) que lo hace a sabiendas. Y quitar los términos de una instancia con marca propia pide la misma confirmación.

## Lo que NO hace

- No muestra el texto de los términos: la instancia guarda y devuelve sólo versión, vigencia y huella (el texto lo ve quien entra a ella). Para
  cambiarlos se carga un texto nuevo con otra versión.
- No decide si el texto es correcto: eso es del humano y de su asesor.
"""
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from ..cliente_instancia import InstanciaInalcanzable, RespuestaDeInstancia
from ..deps import admin_actual, requiere_feature
from ..inventario import InstanciaDesconocida

router = APIRouter(
    prefix="/api/instancias/{slug}/marca",
    tags=["marca"],
    dependencies=[Depends(requiere_feature("marca")), Depends(admin_actual)],
)

#: Tope del logo que pasa por acá (el de la instancia es el mismo: 1 MB). Cortarlo antes ahorra mandar a la instancia lo que va a rechazar.
MAX_BYTES_LOGO = 1_000_000

SIN_SOPORTE = (
    "La instancia todavía no tiene la marca (libracore anterior a v1.206.0, o el producto no montó sus rutas): hay que actualizarla."
)

CODIGO_TERMINOS_PRIMERO = "terminos_primero"
CODIGO_QUEDARIA_FRENADA = "quedaria_frenada"


class MarcaIn(BaseModel):
    # El tope es de cordura, no de negocio: los límites de verdad (40 y 12 caracteres, `#rrggbb`) los pone la instancia y su 422 llega tal cual.
    nombre: str = Field("", max_length=200)
    nombre_corto: str = Field("", max_length=200)
    color: str = Field("", max_length=50)
    #: «Entiendo que esta instancia queda frenada para sus usuarios hasta que cargue sus términos».
    sin_terminos: bool = False


class TerminosIn(BaseModel):
    version: str = Field(max_length=200)
    vigente_desde: str = Field(max_length=50)
    texto: str = Field(max_length=300_000)


def _ruta(request: Request, sufijo: str = "") -> str:
    return request.app.state.settings.marca_instancia_path + sufijo


def _instancia(request: Request, slug: str):
    try:
        return request.app.state.inventario.obtener(slug)
    except InstanciaDesconocida:
        raise HTTPException(404, f"No hay ninguna instancia '{slug}'.")


def _sin_soporte(exc: RespuestaDeInstancia) -> bool:
    # 404/405: la ruta no existe (el fallback de la SPA sólo sirve GET). «no es JSON»: el fallback contestó 200 con HTML.
    return exc.status_code in (404, 405) or "no es JSON" in exc.detalle


async def _pedir(request: Request, slug: str, metodo: str, sufijo: str = "", cuerpo=None, *, archivos=None, crudo: bool = False):
    """Le habla a la instancia y traduce los fallos: 502 si no contesta, 409 si es vieja, y el código de ella en cualquier otro caso (un 422
    suyo llega al formulario como 422)."""
    instancia = _instancia(request, slug)
    try:
        return await request.app.state.cliente_instancia.pedir(
            metodo, instancia, _ruta(request, sufijo), json=cuerpo, archivos=archivos, crudo=crudo,
        )
    except InstanciaInalcanzable as exc:
        raise HTTPException(502, str(exc))
    except RespuestaDeInstancia as exc:
        if _sin_soporte(exc):
            raise HTTPException(409, SIN_SOPORTE)
        raise HTTPException(exc.status_code, exc.detalle)


async def _estado(request: Request, slug: str) -> tuple[bool, bool]:
    """`(es de marca propia, tiene términos propios)`, según la propia instancia."""
    marca = await _pedir(request, slug, "GET")
    if not isinstance(marca, dict):
        raise HTTPException(409, SIN_SOPORTE)
    return bool(marca.get("propia")), bool(marca.get("terminos_propios"))


async def _exigir_terminos_antes(request: Request, slug: str) -> None:
    """Crear una marca propia en una instancia sin términos la deja frenada: se pide cargarlos primero. Si ya es de marca propia, no aplica
    (ya está como está, y cambiarle el nombre no empeora nada)."""
    propia, con_terminos = await _estado(request, slug)
    if propia or con_terminos:
        return
    raise HTTPException(
        409,
        {
            "code": CODIGO_TERMINOS_PRIMERO,
            "mensaje": (
                "Cargá primero los Términos y Condiciones de esta instancia. Con marca propia y sin términos, "
                "sus usuarios no pueden entrar hasta que se carguen."
            ),
        },
    )


async def tiene_marca_propia(request: Request, instancia) -> bool:
    """Si la instancia tiene marca propia, para que «Apariencia» no le pise la suya. **Nunca lanza**: una instancia vieja (sin la ruta), caída o
    que contesta basura es «no» (el tema de la suite se le aplica como siempre)."""
    try:
        marca = await request.app.state.cliente_instancia.pedir("GET", instancia, _ruta(request))
    except Exception:
        return False
    return isinstance(marca, dict) and marca.get("propia") is True


# ── Leer ────────────────────────────────────────────────────────────────────

@router.get("")
async def leer(slug: str, request: Request):
    """La marca y los términos de la instancia, más el producto de este backoffice (para que la pantalla diga de cuál es)."""
    marca = await _pedir(request, slug, "GET")
    terminos = await _pedir(request, slug, "GET", "/terminos")
    return {"marca": marca, "terminos": terminos, "producto": request.app.state.settings.product_slug}


@router.get("/logo")
async def ver_logo(slug: str, request: Request):
    """El logo, para la vista previa. La instancia no está en internet: lo sirve este backoffice, detrás de la sesión del superadmin."""
    try:
        tipo, datos = await _pedir(request, slug, "GET", "/logo", crudo=True)
    except HTTPException as exc:
        # El 404 de «no hay logo» es una respuesta, no un fallo del proxy.
        if exc.status_code in (404, 409):
            raise HTTPException(404, "No hay logo cargado.")
        raise
    if not tipo.startswith("image/"):  # el fallback de la SPA contestando 200 con HTML
        raise HTTPException(404, "No hay logo cargado.")
    return Response(datos, media_type=tipo, headers={"Cache-Control": "private, no-cache"})


# ── Marca ───────────────────────────────────────────────────────────────────

@router.put("")
async def guardar(slug: str, datos: MarcaIn, request: Request):
    if not datos.sin_terminos:
        await _exigir_terminos_antes(request, slug)
    cuerpo = datos.model_dump(exclude={"sin_terminos"})
    return await _pedir(request, slug, "PUT", "", cuerpo)


@router.post("/logo")
async def subir_logo(slug: str, request: Request, logo: UploadFile = File(...), sin_terminos: bool = False):
    contenido = await logo.read(MAX_BYTES_LOGO + 1)
    if len(contenido) > MAX_BYTES_LOGO:
        raise HTTPException(413, f"El logo pesa más de {MAX_BYTES_LOGO // 1_000_000} MB.")
    if not sin_terminos:
        await _exigir_terminos_antes(request, slug)
    archivos = {"logo": (logo.filename or "logo", contenido, logo.content_type or "application/octet-stream")}
    return await _pedir(request, slug, "POST", "/logo", archivos=archivos)


@router.delete("/logo")
async def quitar_logo(slug: str, request: Request):
    return await _pedir(request, slug, "DELETE", "/logo")


@router.delete("")
async def volver_a_la_marca_del_producto(slug: str, request: Request):
    """La instancia vuelve a ser del producto: sin nombre, logo ni color propios **y sin sus términos propios** (lo hace la instancia)."""
    return await _pedir(request, slug, "DELETE")


# ── Términos propios ────────────────────────────────────────────────────────

@router.put("/terminos")
async def guardar_terminos(slug: str, datos: TerminosIn, request: Request):
    return await _pedir(request, slug, "PUT", "/terminos", datos.model_dump())


@router.delete("/terminos")
async def quitar_terminos(slug: str, request: Request, confirmar: bool = False):
    """Quitar los términos de una instancia con marca propia la deja frenada: hace falta `?confirmar=true`."""
    if not confirmar:
        propia, _ = await _estado(request, slug)
        if propia:
            raise HTTPException(
                409,
                {
                    "code": CODIGO_QUEDARIA_FRENADA,
                    "mensaje": (
                        "Esta instancia tiene marca propia: sin sus Términos queda frenada y sus usuarios no pueden entrar. "
                        "Cargá otros antes, o confirmá que querés quitarlos igual."
                    ),
                },
            )
    return await _pedir(request, slug, "DELETE", "/terminos")
