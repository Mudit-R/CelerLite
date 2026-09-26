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
    Subscribes to Redis Pub/Sub and forwards each event as JSON.
    """
    await websocket.accept()
    logger.info("ws_client_connected", client=str(websocket.client))

    # Create a separate Redis connection for pub/sub
    pubsub_client = aioredis.Redis.from_url(
        config.REDIS_URL, decode_responses=True
    )
    pubsub = pubsub_client.pubsub()
    await pubsub.subscribe(EVENTS_CHANNEL)

    try:
        # Send welcome message
        await websocket.send_json({
            "event": "connected",
            "message": "CelerLite real-time event stream active",
        })

        while True:
            # Non-blocking get with timeout
            message = await asyncio.wait_for(
                pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1),
                timeout=1.0,
            )
            if message and message.get("data"):
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                try:
                    event = json.loads(data)
                    await websocket.send_json(event)
                except json.JSONDecodeError:
                    pass

            # Keep-alive ping
            await asyncio.sleep(0.05)

    except (WebSocketDisconnect, asyncio.CancelledError):
        logger.info("ws_client_disconnected")
    except Exception as e:
        logger.error("ws_error", error=str(e))
    finally:
        await pubsub.unsubscribe(EVENTS_CHANNEL)
        await pubsub_client.aclose()
        try:
            await websocket.close()
        except Exception:
            pass
