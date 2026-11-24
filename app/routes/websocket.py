import json
import time
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.models import ClientRole, DisplayMode, MediaType
from app.config import DEFAULT_ROOMS, get_local_ip
from app.state_engine import state_manager

ws_router = APIRouter()

DEFAULT_ROOM_IDS = {r["id"] for r in DEFAULT_ROOMS}


def safe_float(val, default: float = 0.5) -> float:
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


@ws_router.websocket("/ws/{room_id}/{client_role}")
async def room_websocket_endpoint(websocket: WebSocket, room_id: str, client_role: str):
    await websocket.accept()

    # 1. Room existence validation (Strict Ghost Room Prevention)
    room = state_manager.get_room(room_id)
    if not room:
        if room_id in DEFAULT_ROOM_IDS:
            room = state_manager.create_or_update_room(room_id, f"Auditoriya {room_id}")
        else:
            await websocket.close(code=4004, reason="ROOM_NOT_FOUND")
            return

    # Validate role
    try:
        role = ClientRole(client_role.lower())
    except ValueError:
        role = ClientRole.VIEWER

    client_id = f"{role.value}_{hex(id(websocket))[2:]}"
    client_ip = websocket.client.host if websocket.client else "unknown"
    user_agent = websocket.headers.get("user-agent", "unknown")

    # Kiosks and local admin on localhost have default pass; mobile remotes authenticate
    is_authenticated = (role in (ClientRole.SCREEN_1, ClientRole.SCREEN_2))
    token_param = websocket.query_params.get("token")
    if token_param and state_manager.verify_auth_token(room_id, token_param):
        is_authenticated = True
    local_server_ip = get_local_ip()
    if client_ip in ("127.0.0.1", "localhost", local_server_ip) and role == ClientRole.ADMIN:
        is_authenticated = True

    # Register client connection
    client_info = await state_manager.register_connection(
        room_id=room_id,
        client_id=client_id,
        role=role,
        websocket=websocket,
        ip=client_ip,
        user_agent=user_agent
    )

    # Immediately push full authoritative state (Auto State Catch-Up)
    await websocket.send_json({
        "type": "SYNC_STATE",
        "reason": "INITIAL_CONNECT",
        "version": room.version,
        "room_id": room_id,
        "client_id": client_id,
        "role": role.value,
        "timestamp": time.time(),
        "state": room.model_dump(mode="json")
    })

    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                msg = json.loads(raw_data)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")
            payload = msg.get("payload", {})

            # 0. Session Authentication
            if msg_type == "AUTH":
                tok = payload.get("token") or msg.get("token", "")
                if tok and state_manager.verify_auth_token(room_id, tok):
                    is_authenticated = True
                    await websocket.send_json({"type": "AUTH_SUCCESS", "client_id": client_id})
                else:
                    await websocket.send_json({"type": "AUTH_FAILED", "detail": "Noto'g'ri yoki eskirgan token"})
                continue

            # Command protection: require authentication for mutative actions
            COMMAND_ACTIONS = {
                "CHANGE_SLIDE", "NEXT_SLIDE", "PREV_SLIDE", "SET_DISPLAY_MODE",
                "SET_MEDIA_TYPE", "TOGGLE_BLACKOUT", "TOGGLE_LOCK", "TOGGLE_TOUCH_LOCK", "RELOAD_SCREENS"
            }
            if msg_type in COMMAND_ACTIONS and not is_authenticated:
                await websocket.send_json({
                    "type": "AUTH_REQUIRED",
                    "detail": "Boshqarish uchun PIN-kod orqali autentifikatsiya talab qilinadi"
                })
                continue
            payload = msg.get("payload", {})

            # 1. Heartbeat & Latency Calculation
            if msg_type == "PING":
                client_sent_at = msg.get("timestamp", time.time())
                now = time.time()
                roundtrip = max(0.0, (now - client_sent_at) * 1000)
                client_info.last_ping_at = now
                client_info.latency_ms = roundtrip
                await websocket.send_json({
                    "type": "PONG",
                    "client_sent_at": client_sent_at,
                    "server_time": now,
                    "latency_ms": round(roundtrip, 1)
                })

            # 2. Slide Navigation
            elif msg_type == "CHANGE_SLIDE":
                slide_index = payload.get("index", 0)
                target = payload.get("target", "both")
                await state_manager.change_slide(room_id, slide_index, target_screen=target)

            elif msg_type == "NEXT_SLIDE":
                await state_manager.next_slide(room_id)

            elif msg_type == "PREV_SLIDE":
                await state_manager.prev_slide(room_id)

            # 3. Display Mode & Media Switching
            elif msg_type == "SET_DISPLAY_MODE":
                mode_str = payload.get("mode", "mirror")
                try:
                    mode = DisplayMode(mode_str)
                    await state_manager.set_display_mode(room_id, mode)
                except ValueError:
                    pass

            elif msg_type == "SET_MEDIA_TYPE":
                media_str = payload.get("media_type", "slides")
                try:
                    media_type = MediaType(media_str)
                    await state_manager.set_active_media_type(room_id, media_type)
                except ValueError:
                    pass

            elif msg_type == "TOGGLE_BLACKOUT":
                blackout = payload.get("blackout", not room.blackout)
                await state_manager.set_blackout(room_id, blackout)

            elif msg_type == "TOGGLE_LOCK":
                locked = payload.get("locked", not room.locked)
                await state_manager.set_lock(room_id, locked)

            elif msg_type == "TOGGLE_TOUCH_LOCK":
                target_state = payload.get("touch_locked", None)
                await state_manager.set_touch_lock(room_id, target_state)

            elif msg_type == "RESYNC":
                await state_manager.broadcast_state(room_id, reason="MANUAL_RESYNC")

            elif msg_type == "RELOAD_SCREENS":
                await state_manager.reload_screens(room_id)

            elif msg_type == "RGB_TEST":
                await state_manager.trigger_rgb_test(room_id)

            # 4. Laser Pointer (Fast zero-latency broadcast)
            elif msg_type == "LASER_MOVE":
                await state_manager.update_laser(
                    room_id=room_id,
                    active=bool(payload.get("active", False)),
                    x=safe_float(payload.get("x"), 0.5),
                    y=safe_float(payload.get("y"), 0.5),
                    color=payload.get("color", "#ff2a5f"),
                    client_id=client_id
                )

            # 5. Drawing & Whiteboard
            elif msg_type == "DRAW_STROKE":
                await state_manager.add_drawing_stroke(room_id, payload, sender_id=client_id)

            elif msg_type == "CLEAR_DRAWINGS":
                await state_manager.clear_drawings(room_id)

            # 6. Video Sync Hub
            elif msg_type == "VIDEO_COMMAND":
                is_playing = payload.get("is_playing", False)
                curr_time = float(payload.get("current_time", 0.0))
                rate = float(payload.get("playback_rate", 1.0))
                await state_manager.sync_video_playback(
                    room_id=room_id,
                    is_playing=is_playing,
                    current_time=curr_time,
                    playback_rate=rate,
                    sender_id=client_id
                )

            # 7. WebRTC Screen Share Signaling
            elif msg_type.startswith("WEBRTC_"):
                # Optimize ICE host candidates for local LAN/Wi-Fi (replace unresolvable .local mDNS)
                if msg_type == "WEBRTC_ICE_CANDIDATE" and "candidate" in payload:
                    cand_obj = payload.get("candidate")
                    if isinstance(cand_obj, dict):
                        cand_str = cand_obj.get("candidate", "")
                        if ".local" in cand_str:
                            tokens = cand_str.split(" ")
                            if len(tokens) >= 5 and tokens[4].endswith(".local"):
                                effective_ip = client_ip if client_ip not in ("unknown", "testclient") else "127.0.0.1"
                                tokens[4] = effective_ip
                                cand_obj["candidate"] = " ".join(tokens)

                # Relay signaling packet to target clients or all peers
                await state_manager.broadcast_event(
                    room_id=room_id,
                    event_type=msg_type,
                    payload={
                        "from_client": client_id,
                        "from_role": role.value,
                        **payload
                    },
                    exclude_client_id=client_id
                )

            # 8. Canvas Fallback Frame Streamer (Ultra robust fallback when WebRTC is blocked)
            elif msg_type == "CANVAS_FALLBACK_FRAME":
                await state_manager.broadcast_event(
                    room_id=room_id,
                    event_type="CANVAS_FALLBACK_FRAME",
                    payload={
                        "frame": payload.get("frame"),
                        "timestamp": time.time()
                    },
                    exclude_client_id=client_id
                )

            # 9. Quick Announcement / Alert Banner
            elif msg_type == "QUICK_BANNER":
                banner_text = payload.get("text", "")
                duration = payload.get("duration", 10)
                await state_manager.broadcast_event(
                    room_id=room_id,
                    event_type="SHOW_BANNER",
                    payload={"text": banner_text, "duration": duration}
                )

    except WebSocketDisconnect:
        await state_manager.unregister_connection(room_id, client_id)
    except Exception as e:
        print(f"[WebSocket Error] {client_id} in {room_id}: {e}")
        await state_manager.unregister_connection(room_id, client_id)

