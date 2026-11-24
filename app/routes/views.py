# DDDS Views Router
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import TEMPLATES_DIR, get_local_ip, DEFAULT_ROOMS
from app.state_engine import state_manager
from app.qr_service import generate_qr_data_uri

views_router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

DEFAULT_ROOM_IDS = {r["id"] for r in DEFAULT_ROOMS}


def get_or_404_room(room_id: str):
    room = state_manager.get_room(room_id)
    if not room:
        if room_id in DEFAULT_ROOM_IDS:
            room = state_manager.create_or_update_room(room_id, f"Auditoriya {room_id}")
        else:
            raise HTTPException(status_code=404, detail="Auditoriya topilmadi yoki o'chirilgan")
    return room


def is_mobile_user_agent(ua: str) -> bool:
    ua = ua.lower()
    return any(keyword in ua for keyword in [
        "mobile", "android", "iphone", "ipod", "blackberry", "windows phone", "opera mini"
    ])


@views_router.get("/", response_class=HTMLResponse)
async def lobby_page(request: Request):
    rooms = list(state_manager.rooms.values())
    return templates.TemplateResponse(
        request=request,
        name="rooms.html",
        context={"rooms": rooms}
    )


@views_router.get("/screen/{room_id}/{screen_num}", response_class=HTMLResponse)
async def screen_kiosk_page(request: Request, room_id: str, screen_num: int):
    if screen_num not in (1, 2):
        raise HTTPException(status_code=400, detail="Monitor raqami 1 yoki 2 bo'lishi kerak")

    room = get_or_404_room(room_id)

    side_label = "Chap" if screen_num == 1 else "O'ng"
    screen_title = f"{screen_num}-Smart Monitor ({side_label})"
    return templates.TemplateResponse(
        request=request,
        name="screen.html",
        context={
            "room": room,
            "screen_num": screen_num,
            "screen_role": f"screen_{screen_num}",
            "screen_title": screen_title
        }
    )


@views_router.get("/admin/{room_id}", response_class=HTMLResponse)
async def admin_dashboard_page(request: Request, room_id: str):
    room = get_or_404_room(room_id)

    base_url = str(request.base_url).rstrip("/")
    join_url = f"{base_url}/join/{room_id}"
    qr_data_uri = generate_qr_data_uri(join_url, box_size=8, border=1)

    # Local Wi-Fi networking detection
    wifi_ip = get_local_ip()
    port = request.url.port or 8000
    wifi_url = f"http://{wifi_ip}:{port}"
    tv_url = f"http://{wifi_ip}:{port}/tv"
    hotspot_url = f"http://192.168.137.1:{port}/tv"

    admin_token = state_manager.create_auth_token(room_id)

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "room": room,
            "admin_token": admin_token,
            "qr_data_uri": qr_data_uri,
            "join_url": join_url,
            "wifi_ip": wifi_ip,
            "wifi_url": wifi_url,
            "tv_url": tv_url,
            "hotspot_url": hotspot_url,
            "port": port
        }
    )


@views_router.get("/tv", response_class=HTMLResponse)
async def tv_selector_default(request: Request):
    # Default to 204 or first room
    first_room_id = list(state_manager.rooms.keys())[0] if state_manager.rooms else "204"
    return await tv_selector_page(request, first_room_id)


@views_router.get("/tv/{room_id}", response_class=HTMLResponse)
async def tv_selector_page(request: Request, room_id: str):
    room = get_or_404_room(room_id)

    return templates.TemplateResponse(
        request=request,
        name="tv_selector.html",
        context={
            "room": room,
            "room_id": room_id
        }
    )


@views_router.get("/remote/{room_id}", response_class=HTMLResponse)
async def mobile_remote_page(request: Request, room_id: str):
    room = get_or_404_room(room_id)

    return templates.TemplateResponse(
        request=request,
        name="remote.html",
        context={"room": room}
    )


@views_router.get("/join/{room_id}")
async def smart_join_page(request: Request, room_id: str):
    room = get_or_404_room(room_id)

    ua = request.headers.get("user-agent", "")
    is_mobile = is_mobile_user_agent(ua)

    # If query param ?manual=1 is given, show manual selection page, otherwise auto-redirect
    if request.query_params.get("manual") == "1":
        return templates.TemplateResponse(
            request=request,
            name="join.html",
            context={
                "room": room,
                "is_mobile": is_mobile
            }
        )

    # Smart auto-redirect
    if is_mobile:
        return RedirectResponse(url=f"/remote/{room_id}")
    else:
        return RedirectResponse(url=f"/admin/{room_id}")


@views_router.get("/print_qr/{room_id}", response_class=HTMLResponse)
async def print_qr_stand_page(request: Request, room_id: str):
    room = get_or_404_room(room_id)

    base_url = str(request.base_url).rstrip("/")
    join_url = f"{base_url}/join/{room_id}"
    qr_data_uri = generate_qr_data_uri(join_url, box_size=14, border=2)

    return templates.TemplateResponse(
        request=request,
        name="print_qr.html",
        context={
            "room": room,
            "join_url": join_url,
            "qr_data_uri": qr_data_uri
        }
    )
