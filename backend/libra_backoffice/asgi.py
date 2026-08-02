"""Punto de entrada de uvicorn: `uvicorn libra_backoffice.asgi:app`."""
from .app import create_app

app = create_app()
