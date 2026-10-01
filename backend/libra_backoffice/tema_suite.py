"""El tema de la suite de ESTE producto: los colores que el superadmin elige y que el backoffice empuja a todas sus instancias.

Una suite es un producto: todas las instancias de, p. ej., VentaLibra comparten tema (decisión del humano, 2026-10-01, ADR-007 de
`libra-ui`). Lo que se guarda acá es la **fuente de verdad del tema de la suite**; cada instancia guarda además su copia (en su propio
`config.json`, `libracore.tema_router`, ADR-012) y la sirve ella misma, para no depender de que este plano de control esté arriba.

## 🔑 Sólo se valida la FORMA

El catálogo de colores editables y el contraste viven en un solo lugar, `libra-ui/tema`, que usa la pantalla antes de enviar. Acá y en la
instancia alcanza con garantizar que cada par sea `identificador -> #rrggbb`. La regla se repite en esta capa a propósito y no se importa de
`libracore.tema_router`: este contenedor pinea una libracore anterior a `v1.118.0` y subir ese pin (que decide si `panel_admin.py` de cada
producto importa) por una expresión regular no vale el riesgo.

## Dónde vive

En el volumen `estado` del contenedor (`/var/lib/libra-backoffice/tema.json` por defecto, `TEMA_PATH` para cambiarlo), el mismo donde el panel
guarda los intentos fallidos de login: sobrevive a los reinicios y no está en el checkout del producto, que es de git. Se escribe de forma
atómica (archivo temporal + `os.replace`) para que un corte no deje un JSON a medias.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

MAXIMO_DE_COLORES = 32

_CLAVE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,39}$")
_HEX6 = re.compile(r"^#[0-9a-f]{6}$")
_HEX3 = re.compile(r"^#[0-9a-f]{3}$")


class TemaInvalido(ValueError):
    """El tema no tiene la forma `{identificador: #rrggbb}`."""


def normalizar_color(valor: object) -> str | None:
    """`#rgb` o `#rrggbb` (cualquier mayúscula) -> `#rrggbb` en minúsculas, o `None`."""
    if not isinstance(valor, str):
        return None
    v = valor.strip().lower()
    if _HEX3.match(v):
        return "#" + "".join(c * 2 for c in v[1:])
    return v if _HEX6.match(v) else None


def validar_forma(tema: object) -> dict[str, str]:
    """El tema normalizado, o `TemaInvalido` con el motivo (una frase que sirve para mostrar en pantalla)."""
    if not isinstance(tema, dict):
        raise TemaInvalido("El tema tiene que ser un objeto {color: #rrggbb}.")
    if len(tema) > MAXIMO_DE_COLORES:
        raise TemaInvalido(f"Demasiados colores (máximo {MAXIMO_DE_COLORES}).")
    limpio: dict[str, str] = {}
    for clave, valor in tema.items():
        if not isinstance(clave, str) or not _CLAVE.match(clave):
            raise TemaInvalido(f"Clave inválida: {clave!r}.")
        hex_ = normalizar_color(valor)
        if hex_ is None:
            raise TemaInvalido(f"{clave}: no es un color (se espera #rrggbb).")
        limpio[clave] = hex_
    return limpio


class AlmacenDeTema:
    """El tema guardado de la suite. Sin archivo, o con uno ilegible, es un tema vacío (los colores de siempre)."""

    def __init__(self, ruta: Path | str):
        self._ruta = Path(ruta)

    @property
    def ruta(self) -> Path:
        return self._ruta

    def leer(self) -> dict[str, str]:
        try:
            crudo = json.loads(self._ruta.read_text(encoding="utf-8"))
            return validar_forma(crudo.get("tema") if isinstance(crudo, dict) else None)
        except (OSError, ValueError):
            return {}

    def guardar(self, tema: dict[str, str]) -> None:
        limpio = validar_forma(tema)
        self._ruta.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._ruta.parent, prefix=".tema-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"tema": limpio}, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._ruta)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
