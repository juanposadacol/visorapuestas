"""Puente local entre la extension del navegador y la aplicacion.

Todo ocurre dentro de este equipo: un servidor HTTP diminuto que solo escucha
en 127.0.0.1 y que unicamente ACEPTA DATOS. No expone ninguna forma de
ejecutar acciones, abrir ficheros ni controlar el navegador.
"""

from .schema import BridgeValidationError, validate_browser_payload
from .server import BridgeServer, BridgeSettings

__all__ = ["BridgeServer", "BridgeSettings", "validate_browser_payload",
           "BridgeValidationError"]
