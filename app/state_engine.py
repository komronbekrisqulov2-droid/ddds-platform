import asyncio
import time
import uuid
import shutil
import json
from typing import Dict, Any, List, Optional
from fastapi import WebSocket

from app.config import DEFAULT_ROOMS, CACHE_DIR, UPLOADS_DIR, DATA_DIR
from app.models import (
    RoomState, ScreenState, LaserState, DrawingStroke, VideoSyncState,
    DisplayMode, MediaType, ClientRole, ConnectedClient, SlideItem, PresentationDeck
)
from app.media_processor import (
    get_default_starter_slides, get_whiteboard_permanent_slides, purge_deck_disk_files
)

ROOMS_STORE_FILE = DATA_DIR / "rooms_store.json"


class RoomStateManager:
    def __init__(self):
        self.rooms: Dict[str, RoomState] = {}
        # Connections: room_id -> {client_id: WebSocket}
        self.active_sockets: Dict[str, Dict[str, WebSocket]] = {}
        # Client metadata: client_id -> ConnectedClient
        self.clients: Dict[str, ConnectedClient] = {}
        # Auth tokens: token -> (room_id, timestamp)
        self._auth_tokens: Dict[str, tuple] = {}
        # Lock for thread-safe mutations
        self._lock = asyncio.Lock()
        
        # Initialize default rooms
        self._init_default_rooms()

    def _save_rooms_to_disk(self):
        try:
            data = []
            for r_id, room in self.rooms.items():
                data.append({
                    "id": room.room_id,
                    "name": room.room_name,
                    "pin": room.pin,
                    "description": room.description or ""
                })
            ROOMS_STORE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[StateManager] Error saving rooms to disk: {e}")

    def _init_default_rooms(self):
        room_defs = DEFAULT_ROOMS
        if ROOMS_STORE_FILE.exists():
            try:
                loaded = json.loads(ROOMS_STORE_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, list) and len(loaded) > 0:
                    room_defs = loaded
            except Exception as e:
                print(f"[StateManager] Error reading rooms store: {e}")

        for room_def in room_defs:
            r_id = room_def["id"]
            starter_slides = get_default_starter_slides(r_id, room_def["name"])
            starter_deck = PresentationDeck(
                id="deck_smart_starter",
                name="DDDS_Smart_Taqdimot",
                format="pptx",
                slide_count=len(starter_slides),
                slides=starter_slides,
                is_active=True,
                is_permanent=False
            )
            wb_slides = get_whiteboard_permanent_slides(r_id)
            whiteboard_deck = PresentationDeck(
                id="deck_whiteboard_permanent",
                name="📋 Interaktiv Oq Doska (Namuna)",
                format="whiteboard",
                slide_count=len(wb_slides),
                slides=wb_slides,
                is_active=False,
                is_permanent=True
            )
            self.rooms[r_id] = RoomState(
                room_id=r_id,
                room_name=room_def["name"],
                pin=room_def["pin"],
                description=room_def.get("description", ""),
                version=1,
                display_mode=DisplayMode.MIRROR,
                active_media_type=MediaType.SLIDES,
                slides=starter_slides,
                active_deck_name=starter_deck.name,
                active_deck_id=starter_deck.id,
                # Permanent example deck pinned at index 0
                saved_decks=[whiteboard_deck, starter_deck],
                screen1=ScreenState(label="1-Smart Monitor (Chap)", slide_index=0),
                screen2=ScreenState(label="2-Smart Monitor (O'ng)", slide_index=0 if DisplayMode.MIRROR else 1),
                screen3=ScreenState(label="3-Smart Monitor", slide_index=0),
                screen4=ScreenState(label="4-Smart Monitor", slide_index=0)
            )
            self.active_sockets[r_id] = {}

        self._save_rooms_to_disk()

    def get_room(self, room_id: str) -> Optional[RoomState]:
        return self.rooms.get(room_id)

    def create_or_update_room(self, room_id: str, name: str, pin: str = "1234", description: str = "") -> RoomState:
        if room_id in self.rooms:
            room = self.rooms[room_id]
            room.room_name = name
            room.pin = pin
            room.description = description
            room.updated_at = time.time()
            self._save_rooms_to_disk()
            return room

        starter_slides = get_default_starter_slides(room_id, name)
        starter_deck = PresentationDeck(
            id="deck_smart_starter",
            name="DDDS_Smart_Taqdimot",
            format="pptx",
            slide_count=len(starter_slides),
            slides=starter_slides,
            is_active=True,
            is_permanent=False
        )
        wb_slides = get_whiteboard_permanent_slides(room_id)
        whiteboard_deck = PresentationDeck(
            id="deck_whiteboard_permanent",
            name="📋 Interaktiv Oq Doska (Namuna)",
            format="whiteboard",
            slide_count=len(wb_slides),
            slides=wb_slides,
            is_active=False,
            is_permanent=True
        )
        room = RoomState(
            room_id=room_id,
            room_name=name,
            pin=pin,
            description=description,
            version=1,
            slides=starter_slides,
            active_deck_name=starter_deck.name,
            active_deck_id=starter_deck.id,
            # Permanent example deck pinned at index 0
            saved_decks=[whiteboard_deck, starter_deck],
            screen1=ScreenState(label="1-Smart Monitor (Chap)", slide_index=0),
            screen2=ScreenState(label="2-Smart Monitor (O'ng)", slide_index=0),
            screen3=ScreenState(label="3-Smart Monitor", slide_index=0),
            screen4=ScreenState(label="4-Smart Monitor", slide_index=0)
        )
        self.rooms[room_id] = room
        if room_id not in self.active_sockets:
            self.active_sockets[room_id] = {}
        self._save_rooms_to_disk()
        return room

    def create_auth_token(self, room_id: str) -> str:
        token = f"tok_{uuid.uuid4().hex}"
        self._auth_tokens[token] = (room_id, time.time())
        return token

    def verify_auth_token(self, room_id: str, token: str) -> bool:
        if not token or token not in self._auth_tokens:
            return False
        tok_room, created_at = self._auth_tokens[token]
        # Valid for 24 hours
        if tok_room == room_id and (time.time() - created_at < 86400):
            return True
        return False

    async def register_connection(self, room_id: str, client_id: str, role: ClientRole, 
                                  websocket: WebSocket, ip: str = "", user_agent: str = "") -> ConnectedClient:
        async with self._lock:
            if room_id not in self.rooms:
                self.create_or_update_room(room_id, f"Auditoriya {room_id}")

            if room_id not in self.active_sockets:
                self.active_sockets[room_id] = {}

            self.active_sockets[room_id][client_id] = websocket
            
            client_info = ConnectedClient(
                client_id=client_id,
                role=role,
                room_id=room_id,
                ip=ip,
                user_agent=user_agent,
                connected_at=time.time(),
                last_ping_at=time.time(),
                is_active=True
            )
            self.clients[client_id] = client_info

        # Broadcast client joined event to admin/screens
        await self.broadcast_event(room_id, "CLIENT_JOINED", {
            "client_id": client_id,
            "role": role.value,
            "connected_clients": self.get_connected_clients_summary(room_id)
        }, exclude_client_id=client_id)
        
        return client_info

    async def unregister_connection(self, room_id: str, client_id: str):
        async with self._lock:
            if room_id in self.active_sockets and client_id in self.active_sockets[room_id]:
                del self.active_sockets[room_id][client_id]
            if client_id in self.clients:
                del self.clients[client_id]

        await self.broadcast_event(room_id, "CLIENT_LEFT", {
            "client_id": client_id,
            "connected_clients": self.get_connected_clients_summary(room_id)
        })

    def get_connected_clients_summary(self, room_id: str) -> List[Dict[str, Any]]:
        summary = []
        for c_id, c in self.clients.items():
            if c.room_id == room_id:
                summary.append({
                    "client_id": c.client_id,
                    "role": c.role.value,
                    "ip": c.ip,
                    "latency_ms": round(c.latency_ms, 1),
                    "connected_at": c.connected_at
                })
        return summary

    async def broadcast_state(self, room_id: str, reason: str = "STATE_UPDATE"):
        room = self.rooms.get(room_id)
        if not room:
            return

        room.version += 1
        room.updated_at = time.time()

        message = {
            "type": "SYNC_STATE",
            "reason": reason,
            "version": room.version,
            "room_id": room_id,
            "timestamp": time.time(),
            "state": room.model_dump(mode="json")
        }

        await self._broadcast_json(room_id, message)

    async def broadcast_event(self, room_id: str, event_type: str, payload: Dict[str, Any], 
                              exclude_client_id: Optional[str] = None):
        message = {
            "type": event_type,
            "room_id": room_id,
            "timestamp": time.time(),
            "payload": payload
        }
        await self._broadcast_json(room_id, message, exclude_client_id=exclude_client_id)

    async def _broadcast_json(self, room_id: str, data: Dict[str, Any], exclude_client_id: Optional[str] = None):
        sockets = self.active_sockets.get(room_id, {})
        if not sockets:
            return

        dead_clients = []
        tasks = []

        for cid, ws in list(sockets.items()):
            if exclude_client_id and cid == exclude_client_id:
                continue
            tasks.append(self._safe_send_json(cid, ws, data, dead_clients))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Cleanup disconnected sockets
        for dead_id in dead_clients:
            if dead_id in sockets:
                del sockets[dead_id]
            if dead_id in self.clients:
                del self.clients[dead_id]

    async def _safe_send_json(self, client_id: str, ws: WebSocket, data: Dict[str, Any], dead_clients: List[str]):
        try:
            await ws.send_json(data)
        except Exception:
            dead_clients.append(client_id)

    # State mutations
    async def set_display_mode(self, room_id: str, mode: DisplayMode):
        room = self.rooms.get(room_id)
        if not room:
            return
        room.display_mode = mode
        if mode == DisplayMode.MIRROR:
            room.screen2.slide_index = room.screen1.slide_index
            room.screen2.media_type = room.screen1.media_type
        elif mode == DisplayMode.SPLIT:
            total = len(room.slides)
            if total > 0:
                room.screen2.slide_index = min(room.screen1.slide_index + 1, total - 1)
        await self.broadcast_state(room_id, reason="DISPLAY_MODE_CHANGED")

    async def set_active_media_type(self, room_id: str, media_type: MediaType):
        room = self.rooms.get(room_id)
        if not room:
            return
        room.active_media_type = media_type
        room.screen1.media_type = media_type
        room.screen2.media_type = media_type
        await self.broadcast_state(room_id, reason="MEDIA_TYPE_CHANGED")

    async def set_blackout(self, room_id: str, blackout: bool):
        room = self.rooms.get(room_id)
        if not room:
            return
        room.blackout = blackout
        await self.broadcast_state(room_id, reason="BLACKOUT_TOGGLED")

    async def set_lock(self, room_id: str, locked: bool):
        room = self.rooms.get(room_id)
        if not room:
            return
        room.locked = locked
        await self.broadcast_state(room_id, reason="LOCK_TOGGLED")

    async def set_touch_lock(self, room_id: str, touch_locked: Optional[bool] = None) -> bool:
        room = self.rooms.get(room_id)
        if not room:
            return False
        if touch_locked is None:
            room.touch_locked = not getattr(room, "touch_locked", False)
        else:
            room.touch_locked = bool(touch_locked)
        await self.broadcast_state(room_id, reason="TOUCH_LOCK_TOGGLED")
        return room.touch_locked

    async def reload_screens(self, room_id: str):
        await self.broadcast_event(room_id, "RELOAD_PAGE", {})

    async def trigger_rgb_test(self, room_id: str):
        await self.broadcast_event(room_id, "RGB_TEST", {"duration": 4})

    async def update_room(self, room_id: str, name: str, pin: str = "1234", description: str = "") -> Optional[RoomState]:
        async with self._lock:
            if room_id not in self.rooms:
                return None
            room = self.rooms[room_id]
            room.room_name = name
            room.pin = pin
            room.description = description
            room.updated_at = time.time()
            self._save_rooms_to_disk()
        await self.broadcast_state(room_id, reason="ROOM_METADATA_UPDATED")
        return room

    async def delete_room(self, room_id: str) -> bool:
        async with self._lock:
            if room_id not in self.rooms:
                return False
            # Close all active sockets
            sockets = self.active_sockets.get(room_id, {})
            for cid, ws in list(sockets.items()):
                try:
                    await ws.close(code=1000, reason="ROOM_DELETED")
                except Exception:
                    pass
                if cid in self.clients:
                    del self.clients[cid]
            if room_id in self.active_sockets:
                del self.active_sockets[room_id]
            del self.rooms[room_id]
            self._save_rooms_to_disk()

            # Completely purge cache and upload folders from disk
            room_cache = CACHE_DIR / room_id
            room_upload = UPLOADS_DIR / room_id
            if room_cache.exists():
                shutil.rmtree(room_cache, ignore_errors=True)
            if room_upload.exists():
                shutil.rmtree(room_upload, ignore_errors=True)
            return True

    async def change_slide(self, room_id: str, slide_index: int, target_screen: str = "both"):
        room = self.rooms.get(room_id)
        if not room or not room.slides:
            return

        total = len(room.slides)
        slide_index = max(0, min(slide_index, total - 1))

        if target_screen == "both":
            room.screen1.slide_index = slide_index
            if room.display_mode == DisplayMode.MIRROR:
                room.screen2.slide_index = slide_index
            else:  # SPLIT
                room.screen2.slide_index = min(slide_index + 1, total - 1)
        elif target_screen == "screen_1":
            room.screen1.slide_index = slide_index
        elif target_screen == "screen_2":
            room.screen2.slide_index = slide_index

        # Clean old drawings when advancing to a new slide so they don't bleed onto the new slide
        room.drawing_strokes.clear()
        room.active_media_type = MediaType.SLIDES

        # Zero-latency Fast Slide Dispatch (<2ms transmission)
        await self.broadcast_event(room_id, "FAST_SLIDE_SWITCH", {
            "screen1": room.screen1.slide_index,
            "screen2": room.screen2.slide_index,
            "display_mode": room.display_mode.value,
            "total_slides": total
        })

        await self.broadcast_state(room_id, reason="SLIDE_CHANGED")

    async def next_slide(self, room_id: str):
        room = self.rooms.get(room_id)
        if not room or not room.slides:
            return
        total = len(room.slides)
        curr = room.screen1.slide_index
        if curr < total - 1:
            await self.change_slide(room_id, curr + 1, target_screen="both")

    async def prev_slide(self, room_id: str):
        room = self.rooms.get(room_id)
        if not room or not room.slides:
            return
        curr = room.screen1.slide_index
        if curr > 0:
            await self.change_slide(room_id, curr - 1, target_screen="both")

    async def update_laser(self, room_id: str, active: bool, x: float, y: float, 
                           color: str = "#ff2a5f", client_id: Optional[str] = None):
        room = self.rooms.get(room_id)
        if not room:
            return
        room.laser.active = active
        room.laser.x = max(0.0, min(1.0, x))
        room.laser.y = max(0.0, min(1.0, y))
        room.laser.color = color
        room.laser.client_id = client_id

        # Fast direct event without bumping authoritative version (for 60fps laser smoothness)
        await self.broadcast_event(room_id, "LASER_MOVE", {
            "active": active,
            "x": room.laser.x,
            "y": room.laser.y,
            "color": color,
            "client_id": client_id
        }, exclude_client_id=client_id)

    async def add_drawing_stroke(self, room_id: str, stroke_data: Dict[str, Any], sender_id: Optional[str] = None):
        room = self.rooms.get(room_id)
        if not room:
            return
        stroke = DrawingStroke(
            id=stroke_data.get("id", str(uuid.uuid4())[:8]),
            tool=stroke_data.get("tool", "pen"),
            color=stroke_data.get("color", "#ff0055"),
            width=float(stroke_data.get("width", 4.0)),
            points=stroke_data.get("points", []),
            screen_target=stroke_data.get("screen_target", "both")
        )
        room.drawing_strokes.append(stroke)
        await self.broadcast_event(room_id, "DRAW_STROKE", stroke.model_dump(mode="json"), exclude_client_id=sender_id)

    async def clear_drawings(self, room_id: str):
        room = self.rooms.get(room_id)
        if not room:
            return
        room.drawing_strokes.clear()
        await self.broadcast_event(room_id, "CLEAR_DRAWINGS", {"room_id": room_id})

    async def sync_video_playback(self, room_id: str, is_playing: bool, current_time: float, 
                                  playback_rate: float = 1.0, sender_id: Optional[str] = None):
        room = self.rooms.get(room_id)
        if not room:
            return
        room.video_state.is_playing = is_playing
        room.video_state.current_time = current_time
        room.video_state.playback_rate = playback_rate
        room.video_state.last_updated_at = time.time()

        await self.broadcast_event(room_id, "VIDEO_SYNC", {
            "is_playing": is_playing,
            "current_time": current_time,
            "playback_rate": playback_rate,
            "timestamp": time.time()
        }, exclude_client_id=sender_id)

    async def set_deck_slides(self, room_id: str, deck_name: str, slides: List[SlideItem],
                              format_type: str = "pdf", auto_activate: bool = True):
        room = self.rooms.get(room_id)
        if not room:
            return
        
        deck_id = "deck_" + str(uuid.uuid4())[:8]
        new_deck = PresentationDeck(
            id=deck_id,
            name=deck_name,
            format=format_type,
            slide_count=len(slides),
            slides=slides,
            is_active=auto_activate,
            is_permanent=False
        )

        # Enforce memory & disk retention limit: Keep at most 10 uploaded non-permanent decks (+ permanent example deck)
        perm_decks = [d for d in room.saved_decks if getattr(d, 'is_permanent', False)]
        non_perm = [d for d in room.saved_decks if not getattr(d, 'is_permanent', False)]

        while len(non_perm) >= 10:
            oldest = non_perm.pop(0)
            purge_deck_disk_files(room_id, oldest)

        if auto_activate:
            # Mark all other decks inactive
            for d in perm_decks + non_perm:
                d.is_active = False

            new_deck.is_active = True
            # Permanent example deck is ALWAYS pinned at index 0
            room.saved_decks = perm_decks + non_perm + [new_deck]

            # Set as currently active
            room.slides = slides
            room.active_deck_name = deck_name
            room.active_deck_id = deck_id
            room.screen1.slide_index = 0
            room.screen2.slide_index = 0 if room.display_mode == DisplayMode.MIRROR else (1 if len(slides) > 1 else 0)
            room.active_media_type = MediaType.SLIDES
            room.drawing_strokes.clear()
            await self.broadcast_state(room_id, reason="NEW_DECK_LOADED")
        else:
            # Preserve current slide on monitors; just save to portfolio
            new_deck.is_active = False
            # Permanent example deck is ALWAYS pinned at index 0
            room.saved_decks = perm_decks + non_perm + [new_deck]
            await self.broadcast_state(room_id, reason="NEW_DECK_SAVED")

    async def activate_deck(self, room_id: str, deck_id: str):
        room = self.rooms.get(room_id)
        if not room:
            return
        
        target_deck = None
        for d in room.saved_decks:
            if d.id == deck_id:
                d.is_active = True
                target_deck = d
            else:
                d.is_active = False

        if target_deck:
            room.slides = target_deck.slides
            room.active_deck_name = target_deck.name
            room.active_deck_id = target_deck.id
            room.screen1.slide_index = 0
            room.screen2.slide_index = 0 if room.display_mode == DisplayMode.MIRROR else (1 if len(target_deck.slides) > 1 else 0)
            room.active_media_type = MediaType.SLIDES
            room.drawing_strokes.clear()
            await self.broadcast_state(room_id, reason="DECK_ACTIVATED")

    async def delete_deck_from_portfolio(self, room_id: str, deck_id: str):
        room = self.rooms.get(room_id)
        if not room:
            return
        
        # Prevent deletion of permanent whiteboard
        deck = next((d for d in room.saved_decks if d.id == deck_id), None)
        if deck and getattr(deck, 'is_permanent', False):
            return

        if deck:
            purge_deck_disk_files(room_id, deck)

        room.saved_decks = [d for d in room.saved_decks if d.id != deck_id]
        # If we deleted the active deck, activate the first available
        if room.active_deck_id == deck_id and room.saved_decks:
            await self.activate_deck(room_id, room.saved_decks[0].id)
        else:
            await self.broadcast_state(room_id, reason="DECK_DELETED")

    async def clear_deck_portfolio(self, room_id: str):
        room = self.rooms.get(room_id)
        if not room:
            return

        for d in room.saved_decks:
            if not getattr(d, 'is_permanent', False):
                purge_deck_disk_files(room_id, d)

        # Keep permanent decks (e.g. permanent whiteboard)
        room.saved_decks = [d for d in room.saved_decks if getattr(d, 'is_permanent', False)]
        if room.saved_decks:
            await self.activate_deck(room_id, room.saved_decks[0].id)
        else:
            room.slides = []
            room.active_deck_name = "Taqdimotlar mavjud emas"
            room.active_deck_id = None
            await self.broadcast_state(room_id, reason="PORTFOLIO_CLEARED")

    async def add_text_slide_to_active(self, room_id: str, title: str, content: str):
        room = self.rooms.get(room_id)
        if not room:
            return
        new_slide = SlideItem(
            id="text_" + str(uuid.uuid4())[:8],
            index=len(room.slides),
            title=title or "Yangi Slayd",
            text_content=content,
            speaker_notes=content,
            slide_type="text_card"
        )
        room.slides.append(new_slide)
        await self.broadcast_state(room_id, reason="SLIDE_ADDED")


# Global state manager instance
state_manager = RoomStateManager()
