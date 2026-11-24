import io
import time
import uuid
import json
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Response, Request
from pydantic import BaseModel

from app.config import (
    UPLOADS_DIR, DATA_DIR, PDF_EXTENSIONS, PRESENTATION_EXTENSIONS, 
    DOCUMENT_EXTENSIONS, VIDEO_EXTENSIONS, IMAGE_EXTENSIONS
)
from app.state_engine import state_manager
from app.media_processor import process_pdf_file, process_pptx_file, process_docx_file, get_default_starter_slides
from app.qr_service import generate_qr_png_bytes, generate_qr_data_uri
from app.models import SlideItem, MediaType

api_router = APIRouter(prefix="/api")


class CreateRoomRequest(BaseModel):
    room_id: str
    room_name: str
    pin: str = "1234"
    description: str = ""


class UpdateRoomRequest(BaseModel):
    room_name: str
    pin: str = "1234"
    description: str = ""


class VerifyPinRequest(BaseModel):
    pin: str


@api_router.get("/rooms")
def list_rooms():
    result = []
    for r_id, room in state_manager.rooms.items():
        clients = state_manager.get_connected_clients_summary(r_id)
        result.append({
            "room_id": room.room_id,
            "room_name": room.room_name,
            "pin": room.pin,
            "description": room.description,
            "total_slides": len(room.slides),
            "display_mode": room.display_mode.value,
            "active_media_type": room.active_media_type.value,
            "screen1_slide": room.screen1.slide_index,
            "screen2_slide": room.screen2.slide_index,
            "connected_count": len(clients),
            "clients": clients
        })
    return {"status": "ok", "rooms": result}


@api_router.post("/rooms")
def create_room(req: CreateRoomRequest):
    r_id = req.room_id.strip().lower()
    if not r_id:
        raise HTTPException(status_code=400, detail="Xona identifikatori bo'sh bo'lishi mumkin emas")
    
    room = state_manager.create_or_update_room(
        room_id=r_id,
        name=req.room_name.strip() or f"Auditoriya {r_id}",
        pin=req.pin.strip() or "1234",
        description=req.description.strip()
    )
    return {"status": "ok", "room_id": room.room_id, "room_name": room.room_name}


@api_router.get("/room/{room_id}")
def get_room_details(room_id: str):
    room = state_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Xona topilmadi")
    return {
        "status": "ok",
        "room": room.model_dump(mode="json"),
        "connected_clients": state_manager.get_connected_clients_summary(room_id)
    }


@api_router.put("/room/{room_id}")
async def update_room_endpoint(room_id: str, req: UpdateRoomRequest):
    updated = await state_manager.update_room(
        room_id=room_id,
        name=req.room_name.strip(),
        pin=req.pin.strip(),
        description=req.description.strip()
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Xona topilmadi")
    return {"status": "ok", "room": updated.model_dump(mode="json")}


@api_router.delete("/room/{room_id}")
async def delete_room_endpoint(room_id: str):
    success = await state_manager.delete_room(room_id)
    if not success:
        raise HTTPException(status_code=404, detail="Xona topilmadi")
    return {"status": "ok", "deleted_room_id": room_id}


@api_router.post("/room/{room_id}/verify_pin")
def verify_room_pin(room_id: str, req: VerifyPinRequest):
    room = state_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Xona topilmadi")
    
    if req.pin == room.pin:
        token = state_manager.create_auth_token(room_id)
        return {"status": "ok", "valid": True, "token": token, "room_name": room.room_name}
    else:
        return {"status": "error", "valid": False, "detail": "PIN-kod noto'g'ri"}


class AddTextSlideRequest(BaseModel):
    title: str
    content: str


@api_router.post("/room/{room_id}/upload")
async def upload_lecture_media(
    room_id: str,
    file: UploadFile = File(...),
    custom_name: Optional[str] = Form(None)
):
    room = state_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Xona topilmadi")

    filename = custom_name.strip() if custom_name and custom_name.strip() else (file.filename or "uploaded_file")
    ext = Path(file.filename or filename).suffix.lower()
    content = await file.read()

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Fayl bo'sh")

    slides = []
    format_type = "pptx"

    # 1. PDF File Processing
    if ext in PDF_EXTENSIONS:
        format_type = "pdf"
        try:
            slides = process_pdf_file(content, filename, room_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PDF qayta ishlashda xatolik: {e}")

    # 2. PowerPoint (.pptx) Processing
    elif ext in PRESENTATION_EXTENSIONS:
        format_type = "pptx"
        try:
            slides = process_pptx_file(content, filename, room_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PowerPoint qayta ishlashda xatolik: {e}")

    # 3. Word Document (.docx, .doc) Processing
    elif ext in DOCUMENT_EXTENSIONS:
        format_type = "docx"
        try:
            slides = process_docx_file(content, filename, room_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Word hujjatini qayta ishlashda xatolik: {e}")

    # 4. Video File Processing
    elif ext in VIDEO_EXTENSIONS:
        upload_dir = UPLOADS_DIR / room_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        video_path = upload_dir / filename
        video_path.write_bytes(content)

        video_url = f"/uploads/{room_id}/{filename}"
        room.video_state.src = video_url
        room.video_state.is_playing = False
        room.video_state.current_time = 0.0
        room.active_media_type = MediaType.VIDEO
        await state_manager.broadcast_state(room_id, reason="VIDEO_UPLOADED")
        return {
            "status": "ok",
            "media_type": "video",
            "video_url": video_url,
            "filename": filename
        }

    # 4. Single Image Processing
    elif ext in IMAGE_EXTENSIONS:
        format_type = "image"
        upload_dir = UPLOADS_DIR / room_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        img_path = upload_dir / filename
        img_path.write_bytes(content)

        slide = SlideItem(
            id=f"img_{len(room.slides)+1}",
            index=0,
            title=Path(filename).stem,
            image_url=f"/uploads/{room_id}/{filename}",
            speaker_notes=f"Tasvir: {filename}",
            slide_type="image"
        )
        slides = [slide]
    else:
        raise HTTPException(status_code=400, detail=f"Qo'llab-quvvatlanmaydigan fayl formati: {ext}")

    if slides:
        await state_manager.set_deck_slides(room_id, filename, slides, format_type=format_type)
        return {
            "status": "ok",
            "deck_name": filename,
            "slides_count": len(slides),
            "format": format_type
        }


@api_router.post("/room/{room_id}/activate_deck/{deck_id}")
async def activate_deck_endpoint(room_id: str, deck_id: str):
    room = state_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Xona topilmadi")
    await state_manager.activate_deck(room_id, deck_id)
    return {"status": "ok", "active_deck_id": deck_id}


@api_router.delete("/room/{room_id}/delete_deck/{deck_id}")
async def delete_deck_endpoint(room_id: str, deck_id: str):
    room = state_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Xona topilmadi")
    await state_manager.delete_deck_from_portfolio(room_id, deck_id)
    return {"status": "ok", "deleted_id": deck_id}


@api_router.post("/room/{room_id}/clear_decks")
async def clear_decks_endpoint(room_id: str):
    room = state_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Xona topilmadi")
    await state_manager.clear_deck_portfolio(room_id)
    return {"status": "ok"}


@api_router.post("/room/{room_id}/add_text_slide")
async def add_text_slide_endpoint(room_id: str, req: AddTextSlideRequest):
    room = state_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Xona topilmadi")
    await state_manager.add_text_slide_to_active(room_id, req.title, req.content)
    return {"status": "ok"}


@api_router.post("/room/{room_id}/reset_starter")
async def reset_to_starter(room_id: str):
    room = state_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Xona topilmadi")
    
    starter_slides = get_default_starter_slides(room_id, room.room_name)
    await state_manager.set_deck_slides(room_id, "Standart Taqdimot", starter_slides)
    return {"status": "ok", "slides_count": len(starter_slides)}


@api_router.get("/room/{room_id}/qr.png")
def get_room_qr_image(room_id: str, request: Request):
    base_url = str(request.base_url).rstrip("/")
    join_url = f"{base_url}/join/{room_id}"
    png_bytes = generate_qr_png_bytes(join_url, box_size=12, border=2)
    return Response(content=png_bytes, media_type="image/png")


class FeedbackRequest(BaseModel):
    name: str
    role: str = "O'qituvchi / Talaba"
    contact: Optional[str] = ""
    message: str


@api_router.post("/feedback")
async def submit_feedback(req: FeedbackRequest, request: Request):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Fikr yoki taklif matni bo'sh bo'lishi mumkin emas")
    
    feedback_file = DATA_DIR / "feedback.json"
    items = []
    if feedback_file.exists():
        try:
            items = json.loads(feedback_file.read_text(encoding="utf-8"))
        except Exception:
            items = []
    
    new_item = {
        "id": str(uuid.uuid4())[:8],
        "name": req.name.strip() or "Foydalanuvchi",
        "role": req.role.strip() or "O'qituvchi",
        "contact": req.contact.strip() if req.contact else "",
        "message": req.message.strip(),
        "timestamp": time.time(),
        "date_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "client_ip": request.client.host if request.client else "unknown"
    }
    items.append(new_item)
    feedback_file.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok", "message": "Taklifingiz muallifga muvaffaqiyatli yetkazildi! Rahmat ✨"}

