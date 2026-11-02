"""
Los revendedores, en un JSON en el volumen de la consola.

Escritura atómica, como `tema_suite.py`, con una diferencia a propósito: **un archivo ilegible es un error, no una
lista vacía.** El tema puede volver a los colores de siempre; acá, leer vacío y guardar borraría a todos los
revendedores y la memoria de qué instancias suspendió la consola.
"""
import json
import os
import tempfile
from pathlib import Path


class AlmacenIlegible(RuntimeError):
    """`revendedores.json` existe pero no se puede leer: nadie tiene que escribir encima."""


class AlmacenDeRevendedores:
    def __init__(self, ruta: Path | str):
        self._ruta = Path(ruta)
        # Aparte de los revendedores: esos datos salen a la pantalla, y así un hash no puede viajar por descuido.
        self._credenciales = self._ruta.with_name("credenciales-panel.json")

    def leer(self) -> list[dict]:
        try:
            crudo = json.loads(self._ruta.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            raise AlmacenIlegible(f"No se pudo leer {self._ruta}: {exc}") from exc
        revendedores = crudo.get("revendedores") if isinstance(crudo, dict) else None
        if not isinstance(revendedores, list):
            raise AlmacenIlegible(f"{self._ruta} no tiene la lista de revendedores.")
        return revendedores

    def guardar(self, revendedores: list[dict]) -> None:
        self._escribir(self._ruta, {"revendedores": revendedores})

    def credenciales(self) -> dict[str, str]:
        """`{id de revendedor: sha256 de su credencial}`. Sin archivo, ninguna: entrar por el panel no es posible."""
        try:
            crudo = json.loads(self._credenciales.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise AlmacenIlegible(f"No se pudo leer {self._credenciales}: {exc}") from exc
        if not isinstance(crudo, dict):
            raise AlmacenIlegible(f"{self._credenciales} no tiene las credenciales.")
        return crudo

    def guardar_credenciales(self, credenciales: dict[str, str]) -> None:
        self._escribir(self._credenciales, credenciales)

    def _escribir(self, ruta: Path, datos: dict) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=".revendedores-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            os.replace(tmp, ruta)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
