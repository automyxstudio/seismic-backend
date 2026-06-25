"""
WebSocket para actualización de eventos sísmicos en tiempo real.

Endpoint: WS /ws/events

Flujo:
  1. Cliente Angular se conecta al WebSocket.
  2. El handler se suscribe al canal Redis 'seismic:new_event'.
  3. Cuando la ingesta publica un evento nuevo en ese canal,
     el handler lo retransmite a todos los clientes conectados.
  4. Al desconectarse el cliente, se hace unsubscribe del canal.

Redis Pub/Sub desacopla la ingesta del WebSocket:
  - La ingesta no sabe cuántos clientes están conectados.
  - El WebSocket no sabe nada de la API de USGS.
"""

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.database.redis import get_redis
from src.config.constants import REDIS_CHANNEL_NEW_EVENT

log = structlog.get_logger()
router = APIRouter(tags=["websocket"])


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    """
    Establece una conexión WebSocket y retransmite eventos sísmicos en tiempo real.

    No requiere autenticación JWT en el handshake — el token puede enviarse
    como query param si se necesita en el futuro (?token=...).
    """
    await websocket.accept()
    client_host = websocket.client.host if websocket.client else "unknown"
    log.info("websocket_connected", client=client_host)

    redis = get_redis()

    try:
        # Crear un cliente pubsub dedicado para esta conexión
        async with redis.pubsub() as pubsub:
            await pubsub.subscribe(REDIS_CHANNEL_NEW_EVENT)

            async for message in pubsub.listen():
                # Redis también envía mensajes de control (subscribe/unsubscribe)
                # Solo retransmitir mensajes de datos reales
                if message["type"] == "message":
                    await websocket.send_text(message["data"])

    except WebSocketDisconnect:
        log.info("websocket_disconnected", client=client_host)
    except Exception as e:
        log.error("websocket_error", client=client_host, error=str(e))
        await websocket.close()
