"""Puente local: esquema, servidor y seguridad.

Lo que mas importa aqui no es que funcione, sino que NO haga cosas: que no
escuche fuera de loopback, que no acepte payloads mal formados y que no ofrezca
ninguna forma de ejecutar acciones.
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request

import pytest

from visorunder.bridge.schema import (
    MIN_MARKET_CONFIDENCE,
    BridgeValidationError,
    ensure_valid,
    validate_browser_payload,
)
from visorunder.bridge.server import BRIDGE_HEADER, BridgeServer, BridgeSettings


def payload_valido(**cambios):
    base = {
        "protocol": 1,
        "source": "betplay",
        "observedAt": "2026-08-19T02:00:00.000Z",
        "event": {"id": "9876543", "name": "Equipo A vs Equipo B"},
        "visibleMarket": {
            "marketType": "QUARTER_TOTAL", "period": 4, "half": None,
            "confidence": 0.95, "rawTitle": "Total de puntos - Cuarto 4",
            "sidesConfirmed": True,
        },
        "lines": [{"line": 44.5, "overOdds": 1.75, "underOdds": 1.90}],
        "gameState": None,
    }
    base.update(cambios)
    return base


# ------------------------------------------------------------------- esquema
def test_payload_real_valido():
    valido, errores = validate_browser_payload(payload_valido())
    assert valido, errores


@pytest.mark.parametrize("cambio,fragmento", [
    ({"protocol": 99}, "protocolo"),
    ({"source": "otra"}, "fuente"),
    ({"observedAt": ""}, "observedAt"),
    ({"lines": []}, "sin lineas"),
    ({"lines": [{"line": 5000.0, "overOdds": 1.8}]}, "fuera de rango"),
    ({"lines": [{"line": 44.5, "overOdds": 0.2}]}, "fuera de rango"),
    ({"lines": [{"line": 44.5}]}, "sin ninguna cuota"),
    ({"lines": [{"line": 44.5, "overOdds": 1.8, "extra": 1}]}, "desconocidos"),
])
def test_payloads_invalidos_se_rechazan(cambio, fragmento):
    valido, errores = validate_browser_payload(payload_valido(**cambio))
    assert not valido
    assert any(fragmento in e for e in errores), errores


def test_mercado_desconocido_se_rechaza():
    p = payload_valido()
    p["visibleMarket"]["marketType"] = "CUALQUIER_COSA"
    valido, errores = validate_browser_payload(p)
    assert not valido
    assert any("marketType" in e for e in errores)


def test_confianza_insuficiente_se_rechaza():
    p = payload_valido()
    p["visibleMarket"]["confidence"] = MIN_MARKET_CONFIDENCE - 0.2
    valido, errores = validate_browser_payload(p)
    assert not valido
    assert any("confidence" in e for e in errores)


def test_periodo_incoherente_con_el_tipo():
    p = payload_valido()
    p["visibleMarket"]["period"] = 9
    assert not validate_browser_payload(p)[0]

    p = payload_valido()
    p["visibleMarket"]["marketType"] = "GAME_TOTAL"
    p["visibleMarket"]["period"] = 3
    assert not validate_browser_payload(p)[0]


def test_mitad_solo_en_mercados_de_mitad():
    p = payload_valido()
    p["visibleMarket"].update({"marketType": "HALF_TOTAL", "period": None, "half": 2})
    assert validate_browser_payload(p)[0]
    p["visibleMarket"]["half"] = 5
    assert not validate_browser_payload(p)[0]


def test_campos_desconocidos_en_la_raiz():
    valido, errores = validate_browser_payload(payload_valido(comando="rm -rf"))
    assert not valido
    assert any("desconocidos" in e for e in errores)


def test_estado_de_juego_opcional_y_validado():
    p = payload_valido(gameState={"scoreA": 58, "scoreB": 52, "period": 4, "clock": "06:24"})
    assert validate_browser_payload(p)[0]
    for malo in ({"scoreA": -1}, {"period": 12}, {"clock": "6:99"}, {"clock": "abc"}):
        p = payload_valido(gameState=malo)
        assert not validate_browser_payload(p)[0], malo


def test_ensure_valid_lanza_con_los_motivos():
    with pytest.raises(BridgeValidationError) as info:
        ensure_valid(payload_valido(lines=[]))
    assert info.value.errors


# ------------------------------------------------------------------ ajustes
def test_el_host_siempre_acaba_en_loopback():
    for host in ("0.0.0.0", "192.168.1.50", "example.com", ""):
        assert BridgeSettings(host=host).validate().host == "127.0.0.1"


def test_el_puerto_se_acota():
    assert BridgeSettings(port=80).validate().port == 8765
    assert BridgeSettings(port=99999).validate().port == 8765
    assert BridgeSettings(port=9000).validate().port == 9000


# ----------------------------------------------------------------- servidor
@pytest.fixture()
def servidor():
    recibidos = []
    server = BridgeServer(BridgeSettings(port=0), on_payload=recibidos.append, version="9.9.9")
    assert server.start()
    yield server, recibidos
    server.stop()


def _post(server, cuerpo, cabeceras=None, crudo=None):
    datos = crudo if crudo is not None else json.dumps(cuerpo).encode("utf-8")
    peticion = urllib.request.Request(
        f"{server.url}/v1/browser-state", data=datos, method="POST")
    for clave, valor in (cabeceras or {"Content-Type": "application/json",
                                       BRIDGE_HEADER: "1"}).items():
        peticion.add_header(clave, valor)
    try:
        with urllib.request.urlopen(peticion, timeout=5) as respuesta:
            return respuesta.status, json.loads(respuesta.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "{}")


def test_health_responde(servidor):
    server, _ = servidor
    with urllib.request.urlopen(f"{server.url}/health", timeout=5) as respuesta:
        cuerpo = json.loads(respuesta.read().decode("utf-8"))
    assert cuerpo["status"] == "ok"
    assert cuerpo["app"] == "VisorApuestas"
    assert cuerpo["version"] == "9.9.9"


def test_payload_valido_se_acepta_y_se_entrega(servidor):
    server, recibidos = servidor
    estado, cuerpo = _post(server, payload_valido())
    assert estado == 200 and cuerpo["accepted"] is True
    assert len(recibidos) == 1
    assert recibidos[0]["lines"][0]["underOdds"] == 1.90


def test_payload_invalido_se_rechaza_sin_entregarse(servidor):
    server, recibidos = servidor
    estado, cuerpo = _post(server, payload_valido(lines=[{"line": 5000.0, "overOdds": 1.8}]))
    assert estado == 422
    assert recibidos == []
    assert cuerpo["details"]


def test_sin_la_cabecera_del_protocolo_se_rechaza(servidor):
    server, recibidos = servidor
    estado, _ = _post(server, payload_valido(),
                      cabeceras={"Content-Type": "application/json"})
    assert estado == 400
    assert recibidos == []


def test_content_type_incorrecto_se_rechaza(servidor):
    server, _ = servidor
    estado, _ = _post(server, payload_valido(),
                      cabeceras={"Content-Type": "text/plain", BRIDGE_HEADER: "1"})
    assert estado == 415


def test_cuerpo_demasiado_grande_se_rechaza(servidor):
    server, recibidos = servidor
    enorme = json.dumps(payload_valido(
        lines=[{"line": 20.5 + i, "overOdds": 1.9} for i in range(30)],
        event={"id": "x" * 100, "name": "y" * 190})).encode("utf-8")
    server.settings.max_body_bytes = 200
    estado, _ = _post(server, None, crudo=enorme)
    assert estado == 413
    assert recibidos == []


def test_json_invalido_se_rechaza(servidor):
    server, _ = servidor
    estado, _ = _post(server, None, crudo=b"{esto no es json")
    assert estado == 400


def test_no_existen_rutas_para_ejecutar_nada(servidor):
    server, _ = servidor
    for ruta in ("/v1/command", "/exec", "/v1/bet", "/shell", "/files"):
        peticion = urllib.request.Request(f"{server.url}{ruta}", data=b"{}", method="POST")
        peticion.add_header("Content-Type", "application/json")
        peticion.add_header(BRIDGE_HEADER, "1")
        try:
            with urllib.request.urlopen(peticion, timeout=5) as respuesta:
                assert respuesta.status == 404
        except urllib.error.HTTPError as error:
            assert error.code == 404, ruta


def test_un_origen_que_no_es_extension_se_rechaza(servidor):
    server, recibidos = servidor
    estado, _ = _post(server, payload_valido(), cabeceras={
        "Content-Type": "application/json", BRIDGE_HEADER: "1",
        "Origin": "https://sitio-cualquiera.com"})
    assert estado == 403
    assert recibidos == []


def test_el_origen_de_una_extension_se_acepta_y_se_devuelve_exacto(servidor):
    server, _ = servidor
    origen = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    peticion = urllib.request.Request(
        f"{server.url}/v1/browser-state",
        data=json.dumps(payload_valido()).encode("utf-8"), method="POST")
    peticion.add_header("Content-Type", "application/json")
    peticion.add_header(BRIDGE_HEADER, "1")
    peticion.add_header("Origin", origen)
    with urllib.request.urlopen(peticion, timeout=5) as respuesta:
        assert respuesta.status == 200
        # Nunca "*": se devuelve el origen concreto.
        assert respuesta.headers.get("Access-Control-Allow-Origin") == origen


def test_solo_escucha_en_loopback(servidor):
    server, _ = servidor
    direccion_local = socket.gethostbyname(socket.gethostname())
    if direccion_local.startswith("127."):
        pytest.skip("el equipo no tiene una IP no-loopback con la que probarlo")
    prueba = socket.socket()
    prueba.settimeout(1.5)
    with pytest.raises((ConnectionRefusedError, OSError, socket.timeout)):
        prueba.connect((direccion_local, server.port))
    prueba.close()


def test_el_puerto_queda_libre_al_parar():
    server = BridgeServer(BridgeSettings(port=0))
    assert server.start()
    puerto = server.port
    server.stop()
    # Si el servidor hubiera dejado el puerto ocupado, esto fallaria.
    comprobacion = socket.socket()
    comprobacion.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    comprobacion.bind(("127.0.0.1", puerto))
    comprobacion.close()


def test_parar_dos_veces_es_seguro():
    server = BridgeServer(BridgeSettings(port=0))
    server.start()
    server.stop()
    server.stop()
    assert not server.is_running


def test_un_error_al_procesar_no_tumba_el_servidor(servidor):
    server, _ = servidor

    def explota(_payload):
        raise RuntimeError("fallo simulado")

    server.on_payload = explota
    estado, _ = _post(server, payload_valido())
    assert estado == 500
    # y el servidor sigue en pie
    server.on_payload = lambda _p: None
    assert _post(server, payload_valido())[0] == 200


def test_si_el_puerto_esta_ocupado_no_revienta():
    ocupado = socket.socket()
    ocupado.bind(("127.0.0.1", 0))
    ocupado.listen(1)
    puerto = ocupado.getsockname()[1]
    server = BridgeServer(BridgeSettings(port=puerto))
    try:
        assert server.start() is False
        assert "no se pudo abrir el puerto" in server.stats.last_error
    finally:
        server.stop()
        ocupado.close()


# ------------------------------- el reloj crudo dentro del contrato del puente

def test_el_esquema_acepta_el_reloj_con_su_semantica():
    from visorunder.bridge.schema import validate_browser_payload

    base = payload_valido()
    base["gameState"] = {"period": 4, "clockRaw": "33:52",
                         "clockSemantics": "GAME_ELAPSED"}
    valido, errores = validate_browser_payload(base)
    assert valido, errores


def test_el_esquema_rechaza_un_reloj_crudo_sin_semantica():
    from visorunder.bridge.schema import validate_browser_payload

    base = payload_valido()
    base["gameState"] = {"period": 4, "clockRaw": "33:52"}
    valido, errores = validate_browser_payload(base)
    assert not valido
    assert any("clockRaw sin clockSemantics" in e for e in errores)


def test_el_esquema_rechaza_una_semantica_inventada():
    from visorunder.bridge.schema import validate_browser_payload

    base = payload_valido()
    base["gameState"] = {"period": 4, "clockRaw": "33:52", "clockSemantics": "LO_QUE_SEA"}
    valido, errores = validate_browser_payload(base)
    assert not valido
    assert any("clockSemantics" in e for e in errores)


def test_el_reloj_crudo_admite_mas_de_99_minutos_y_el_publicado_no_miente():
    from visorunder.bridge.schema import validate_browser_payload

    base = payload_valido()
    base["gameState"] = {"period": 4, "clockRaw": "100:30",
                         "clockSemantics": "GAME_ELAPSED"}
    valido, _ = validate_browser_payload(base)
    assert valido, "un acumulado puede pasar de 99 minutos en otros deportes"

    base["gameState"] = {"period": 4, "clock": "99:99"}
    valido, errores = validate_browser_payload(base)
    assert not valido and any("clock" in e for e in errores)
