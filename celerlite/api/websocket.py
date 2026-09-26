"""WebSocket endpoint for real-time task event streaming via Redis Pub/Sub."""

import asyncio
import json

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from celerlite.api.app import get_broker
from celerlite.config import config
from celerlite.observability.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)

EVENTS_CHANNEL = "celerlite:events"


@router.websocket("/api/v1/ws/events")
async def websocket_events(websocket: WebSocket):
    """
    Streams real-time task lifecycle events to connected clients.
    Works seamlessly with both RedisBroker and InMemoryBroker.
    """
    await websocket.accept()
    logger.info("ws_client_connected", client=str(websocket.client))

    broker = get_broker()
    if not broker:
        await websocket.close(code=1011, reason="Broker not ready")
        return

    try:
        # Send welcome message
        await websocket.send_json({
            "event": "connected",
            "message": "CelerLite real-time event stream active",
        })

        async for event in broker.subscribe_events():
            await websocket.send_json(event)

    except (WebSocketDisconnect, asyncio.CancelledError):
        logger.info("ws_client_disconnected")
    except Exception as e:
        logger.error("ws_error", error=str(e))
    finally:
        try:
            await websocket.close()
        except Exception:
            pass

