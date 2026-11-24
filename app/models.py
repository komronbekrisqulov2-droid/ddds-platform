from enum import Enum
from typing import List, Dict, Optional, Any, Tuple
from pydantic import BaseModel, Field, ConfigDict
import time


class DisplayMode(str, Enum):
    MIRROR = "mirror"
    SPLIT = "split"


class MediaType(str, Enum):
    SLIDES = "slides"
    VIDEO = "video"
    SCREENSHARE = "screenshare"
    WHITEBOARD = "whiteboard"
    BLACKOUT = "blackout"


class ClientRole(str, Enum):
    SCREEN_1 = "screen_1"
    SCREEN_2 = "screen_2"
    ADMIN = "admin"
    REMOTE = "remote"
    VIEWER = "viewer"


class SlideItem(BaseModel):
    id: str
    index: int
    title: str = ""
    text_content: str = ""
    image_url: Optional[str] = None
    speaker_notes: str = ""
    slide_type: str = "pdf_page"  # "pdf_page", "pptx_card", "image", "text_card"
    extra_data: Dict[str, Any] = Field(default_factory=dict)


class ScreenState(BaseModel):
    media_type: MediaType = MediaType.SLIDES
    slide_index: int = 0
    video_time: float = 0.0
    is_playing: bool = False
    custom_text: str = ""
    label: str = "Display"


class LaserState(BaseModel):
    active: bool = False
    x: float = 0.5  # Normalized 0.0 to 1.0
    y: float = 0.5  # Normalized 0.0 to 1.0
    color: str = "#ff2a5f"
    client_id: Optional[str] = None
    target_screen: str = "both"  # "both", "screen_1", "screen_2"


class DrawingStroke(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    tool: str = "pen"  # "pen", "highlighter", "eraser"
    color: str = "#ff0055"
    width: float = 4.0
    points: List[Tuple[float, float]] = Field(default_factory=list)  # Normalized coordinates [x, y]
    screen_target: str = "both"  # "both", "screen_1", "screen_2"


class VideoSyncState(BaseModel):
    src: str = ""
    is_playing: bool = False
    current_time: float = 0.0
    playback_rate: float = 1.0
    volume: float = 1.0
    is_muted: bool = False
    last_updated_at: float = Field(default_factory=time.time)


class ConnectedClient(BaseModel):
    client_id: str
    role: ClientRole
    room_id: str
    ip: str = "127.0.0.1"
    user_agent: str = ""
    connected_at: float = Field(default_factory=time.time)
    last_ping_at: float = Field(default_factory=time.time)
    latency_ms: float = 0.0
    is_active: bool = True


class PresentationDeck(BaseModel):
    id: str
    name: str
    format: str = "pptx"  # "pptx", "pdf", "image"
    slide_count: int = 0
    slides: List[SlideItem] = Field(default_factory=list)
    is_active: bool = False
    created_at: float = Field(default_factory=time.time)


class RoomState(BaseModel):
    model_config = ConfigDict(extra="ignore")
    room_id: str
    room_name: str
    pin: str = "1234"
    description: str = ""
    version: int = 1
    display_mode: DisplayMode = DisplayMode.MIRROR
    active_media_type: MediaType = MediaType.SLIDES
    blackout: bool = False
    locked: bool = False
    touch_locked: bool = False
    whiteboard_bg: str = "grid"  # "dark", "white", "grid"
    
    # Active presentation decks / items
    slides: List[SlideItem] = Field(default_factory=list)
    active_deck_name: str = "7-maruza_Parallel_dasturlar_unumdorligini_baholash"
    active_deck_id: Optional[str] = "starter_deck"
    saved_decks: List[PresentationDeck] = Field(default_factory=list)
    
    # Independent or synchronized screen status
    screen1: ScreenState = Field(default_factory=lambda: ScreenState(label="1-Smart Monitor (Chap)"))
    screen2: ScreenState = Field(default_factory=lambda: ScreenState(label="2-Smart Monitor (O'ng)"))
    
    # Live laser & drawing overlays
    laser: LaserState = Field(default_factory=LaserState)
    drawing_strokes: List[DrawingStroke] = Field(default_factory=list)
    
    # Synchronized video hub
    video_state: VideoSyncState = Field(default_factory=VideoSyncState)
    
    # WebRTC Screen sharing broadcaster id
    webrtc_broadcaster_id: Optional[str] = None
    screenshare_active: bool = False
    
    # Timestamps
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class WSMessage(BaseModel):
    type: str
    room_id: str
    version: Optional[int] = None
    sender_id: Optional[str] = None
    sender_role: Optional[ClientRole] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)

