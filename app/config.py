import os
import socket
from pathlib import Path

def get_local_ip() -> str:
    # 1. Try public routing if available
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.6)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        if ip and not ip.startswith('127.'):
            return ip
    except Exception:
        pass
    finally:
        s.close()

    # 2. Offline fallback: Inspect local hostname interfaces (Wi-Fi, Hotspot, LAN)
    try:
        hostname = socket.gethostname()
        candidate_ips = socket.gethostbyname_ex(hostname)[2]
        # Filter for non-loopback IPv4 addresses
        valid_ips = [ip for ip in candidate_ips if not ip.startswith('127.') and ':' not in ip]
        if valid_ips:
            # Prioritize Windows Mobile Hotspot (192.168.137.x)
            hotspot_ips = [ip for ip in valid_ips if ip.startswith('192.168.137.')]
            if hotspot_ips:
                return hotspot_ips[0]
            # Prioritize standard home/class Wi-Fi (192.168.x.x)
            lan_ips = [ip for ip in valid_ips if ip.startswith('192.168.')]
            if lan_ips:
                return lan_ips[0]
            # Prioritize university/enterprise subnets (172.x or 10.x)
            for ip in valid_ips:
                if ip.startswith(('172.', '10.')):
                    return ip
            return valid_ips[0]
    except Exception:
        pass

    return "127.0.0.1"

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
UPLOADS_DIR = BASE_DIR / "uploads"
CACHE_DIR = BASE_DIR / "cache"
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"

# Ensure runtime directories exist
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "css").mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "js").mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "assets").mkdir(parents=True, exist_ok=True)

# Server Configuration
HOST = os.getenv("DDDS_HOST", "0.0.0.0")
PORT = int(os.getenv("DDDS_PORT", "8000"))
DEBUG = os.getenv("DDDS_DEBUG", "False").lower() in ("true", "1", "t")

# Multi-tenant Room Defaults
DEFAULT_ROOMS = [
    {
        "id": "204",
        "name": "204-Auditoriya (Bosh Bino)",
        "pin": "2040",
        "description": "Smart Kengash va Ma'ruzalar zali"
    },
    {
        "id": "101",
        "name": "101-Auditoriya (Axborot Texnologiyalari)",
        "pin": "1010",
        "description": "Dasturlash va Kiberxavfsizlik markazi"
    },
    {
        "id": "fizika-1",
        "name": "Fizika-1 Laboratoriyasi",
        "pin": "7788",
        "description": "Eksperimental fizika va optika auditoriyasi"
    }
]

# Supported media extensions (Ultra-fast PDF, Images and Videos)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PDF_EXTENSIONS = {".pdf"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".ogg", ".mov"}
ALLOWED_EXTENSIONS = PDF_EXTENSIONS | IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

# Maximum upload size (100 MB to prevent DoS / RAM blowouts)
MAX_UPLOAD_SIZE = 100 * 1024 * 1024


