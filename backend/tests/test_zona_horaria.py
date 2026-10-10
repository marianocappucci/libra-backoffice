"""El backoffice corre con la hora de Argentina, como los productos (2026-10-10).

Corre adentro los `panel_admin.py` y `nuevo_cliente.py` de cada producto, que nombran la versión desplegada, el
`desplegado_at` de `cliente.json` y los respaldos con `datetime.now()`. Medido ese día: los ocho `-admin` corrían sin
`TZ` (en UTC) y los contenedores de los productos, el servidor y las 21 bases, con la hora de Argentina.
"""
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"


def test_la_imagen_final_fija_la_zona_de_argentina():
    etapas = DOCKERFILE.read_text().split("\nFROM ")
    final = etapas[-1]
    assert "ENV TZ=America/Argentina/Buenos_Aires" in final, "la etapa final del Dockerfile no fija TZ"
