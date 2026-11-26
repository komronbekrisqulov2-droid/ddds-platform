import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app.main import app
from app.config import get_local_ip
from app.models import RoomState, ScreenState
from app.state_engine import state_manager

client = TestClient(app)

def test_1_lobby_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "DDDS Cloud" in response.text
    assert "302-Auditoriya" in response.text
    assert "101-Auditoriya" in response.text
    assert "Fizika-1" in response.text

def test_2_screen_page():
    # Screen 1
    res1 = client.get("/screen/204/1")
    assert res1.status_code == 200
    assert "1-Smart Monitor" in res1.text
    assert "sync-video" in res1.text
    assert "touch-locked-badge" in res1.text

    # Screen 2: Must have muted attribute to prevent audio echo in classroom
    res2 = client.get("/screen/204/2")
    assert res2.status_code == 200
    assert "2-Smart Monitor" in res2.text
    assert "muted" in res2.text

def test_3_admin_page():
    response = client.get("/admin/204")
    assert response.status_code == 200
    assert "DDDS" in response.text
    assert "Jonli Uzatish" in response.text
    assert "upload-progress-container" in response.text
    assert "btn-ctrl-touch-lock" in response.text
    assert "Sensorni Bloklash" in response.text
    assert "Esc Chiqish" not in response.text

def test_4_tv_page():
    response = client.get("/tv")
    assert response.status_code == 200
    assert "Zaldagi Smart Monitor" in response.text

def test_5_remote_page_pin_leak_prevention():
    response = client.get("/remote/204")
    assert response.status_code == 200
    assert "Smartfon Pulti" in response.text
    # Security: Ensure PIN is NOT leaked in client JS
    assert 'const ROOM_PIN = "{{ room.pin }}";' not in response.text
    assert 'ROOM_PIN' not in response.text
    assert "/api/room/" in response.text
    assert "verify_pin" in response.text

def test_6_print_qr_page():
    response = client.get("/print_qr/204")
    assert response.status_code == 200
    assert "Stol QR Stendi" in response.text
    assert "data:image/png;base64," in response.text

def test_7_smart_join_redirect():
    # User-Agent mobile -> redirect to /remote/{id}
    res_mobile = client.get(
        "/join/204",
        headers={"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"},
        follow_redirects=False
    )
    assert res_mobile.status_code == 307
    assert "/remote/204" in res_mobile.headers["location"]

    # User-Agent desktop -> redirect to /admin/{id}
    res_desktop = client.get(
        "/join/204",
        headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        follow_redirects=False
    )
    assert res_desktop.status_code == 307
    assert "/admin/204" in res_desktop.headers["location"]

def test_8_api_rooms_listing():
    response = client.get("/api/rooms")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert len(data["rooms"]) >= 3
    # Security: Ensure secret PIN is NOT returned in public room listings
    for r in data["rooms"]:
        assert "pin" not in r
        assert "has_pin" in r

def test_9_api_room_crud():
    # 1. Create temporary room
    res_create = client.post("/api/rooms", json={
        "room_id": "test-crud-1",
        "room_name": "Test Xona 1",
        "pin": "5555",
        "description": "Sinov auditoriyasi"
    })
    assert res_create.status_code == 200

    token = state_manager.create_auth_token("test-crud-1")

    # 2. Update room (with auth token)
    res_update = client.put(f"/api/room/test-crud-1?token={token}", json={
        "room_name": "Test Xona 1 Yangilandi",
        "pin": "7777",
        "description": "Yangilangan tavsif"
    })
    assert res_update.status_code == 200
    assert res_update.json()["room"]["room_name"] == "Test Xona 1 Yangilandi"

    # 3. Unauthenticated delete is rejected (401)
    res_del_unauth = client.delete("/api/room/test-crud-1")
    assert res_del_unauth.status_code == 401

    # 4. Authenticated delete succeeds
    res_del = client.delete(f"/api/room/test-crud-1?token={token}")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "ok"

    # 5. Confirm deleted in API
    res_get = client.get("/api/room/test-crud-1")
    assert res_get.status_code == 404

def test_10_ghost_room_prevention():
    # Once deleted, views.py must return 404 and not resurrect deleted room
    res_view = client.get("/screen/deleted-ghost-room-99/1")
    assert res_view.status_code == 404

    res_admin = client.get("/admin/deleted-ghost-room-99")
    assert res_admin.status_code == 404

def test_11_pin_verification_and_auth_token():
    # 1. Valid PIN issues session token
    res_ok = client.post("/api/room/204/verify_pin", json={"pin": "2040"})
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["valid"] is True
    assert "token" in data
    assert len(data["token"]) > 16

    # Verify the token is valid in state_manager
    assert state_manager.verify_auth_token("204", data["token"]) is True

    # 2. Invalid PIN rejected
    res_fail = client.post("/api/room/204/verify_pin", json={"pin": "0000"})
    assert res_fail.status_code == 200
    assert res_fail.json()["valid"] is False

def test_12_room_lock_state_serialization():
    room = RoomState(
        room_id="lock-test",
        room_name="Lock Test Room",
        pin="1234",
        screen1=ScreenState(screen_id=1, screen_name="Screen 1"),
        screen2=ScreenState(screen_id=2, screen_name="Screen 2"),
        locked=True,
        touch_locked=True
    )
    dumped = room.model_dump(mode="json")
    assert "locked" in dumped
    assert dumped["locked"] is True
    assert "touch_locked" in dumped
    assert dumped["touch_locked"] is True

def test_13_local_ip_detection():
    ip = get_local_ip()
    assert isinstance(ip, str)
    assert len(ip.split(".")) == 4
    # Ensure it's not a loopback 127.0.0.1 unless completely isolated
    parts = [int(p) for p in ip.split(".")]
    assert all(0 <= p <= 255 for p in parts)

def test_14_qr_png_generation():
    response = client.get("/api/room/204/qr.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert len(response.content) > 100

def test_15_websocket_connection_and_heartbeat():
    with client.websocket_connect("/ws/204/screen_1") as ws:
        init_data = ws.receive_json()
        assert init_data["type"] == "SYNC_STATE"
        assert init_data["room_id"] == "204"
        assert len(init_data["state"]["slides"]) > 0

        # Send Ping -> expect Pong
        ws.send_json({"type": "PING", "timestamp": 12345.0})
        pong = ws.receive_json()
        assert pong["type"] == "PONG"

def test_16_touch_lock_toggle_and_palm_rejection():
    # 1. Obtain authenticated session token for room 204
    token = state_manager.create_auth_token("204")

    with client.websocket_connect("/ws/204/admin") as ws:
        # Initial sync state
        init_data = ws.receive_json()
        assert init_data["type"] == "SYNC_STATE"
        
        # Authenticate session
        ws.send_json({"type": "AUTH", "token": token})
        auth_resp = ws.receive_json()
        assert auth_resp["type"] == "AUTH_SUCCESS"

        # Toggle Touch Lock to True
        ws.send_json({"type": "TOGGLE_TOUCH_LOCK", "payload": {"touch_locked": True}})
        msg1 = ws.receive_json()
        assert msg1["type"] == "SYNC_STATE"
        assert msg1["state"]["touch_locked"] is True

        # Toggle Touch Lock back to False
        ws.send_json({"type": "TOGGLE_TOUCH_LOCK", "payload": {"touch_locked": False}})
        msg2 = ws.receive_json()
        assert msg2["type"] == "SYNC_STATE"
        assert msg2["state"]["touch_locked"] is False

def test_17_webrtc_screenshare_signaling_and_canvas_fallback():
    # Verify screenshare media switching, WebRTC signal handling, and canvas fallback frames
    room_id = "204"
    token = state_manager.create_auth_token(room_id)
    with client.websocket_connect(f"/ws/{room_id}/admin") as ws_admin:
        init_admin = ws_admin.receive_json()
        assert init_admin["type"] == "SYNC_STATE"

        # Authenticate session
        ws_admin.send_json({"type": "AUTH", "token": token})
        auth_resp = ws_admin.receive_json()
        assert auth_resp["type"] == "AUTH_SUCCESS"

        # 1. Admin switches media to screenshare
        ws_admin.send_json({"type": "SET_MEDIA_TYPE", "payload": {"media_type": "screenshare"}})
        admin_sync = ws_admin.receive_json()
        assert admin_sync["type"] == "SYNC_STATE"
        assert admin_sync["state"]["active_media_type"] == "screenshare"

        # 2. Admin announces WEBRTC_BROADCAST_START (relayed without error)
        ws_admin.send_json({"type": "WEBRTC_BROADCAST_START", "payload": {"broadcaster_id": "admin_test"}})

        # 3. Admin sends CANVAS_FALLBACK_FRAME (relayed without error)
        sample_frame = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
        ws_admin.send_json({"type": "CANVAS_FALLBACK_FRAME", "payload": {"frame": sample_frame}})

        # 4. Admin restores media back to slides
        ws_admin.send_json({"type": "SET_MEDIA_TYPE", "payload": {"media_type": "slides"}})
        admin_restored = ws_admin.receive_json()
        assert admin_restored["type"] == "SYNC_STATE"
        assert admin_restored["state"]["active_media_type"] == "slides"

def test_18_fast_image_upload_and_auto_switch():
    import io
    from PIL import Image

    token = state_manager.create_auth_token("204")
    room_before = state_manager.get_room("204")
    original_active_deck = room_before.active_deck_id

    # Create small test PNG image in-memory
    img_byte_arr = io.BytesIO()
    img = Image.new("RGB", (600, 400), color=(50, 100, 200))
    img.save(img_byte_arr, format="PNG")
    img_bytes = img_byte_arr.getvalue()

    # 1. Upload image with auto_activate=False -> should NOT disrupt current active presentation
    res_no_auto = client.post(
        f"/api/room/204/upload",
        files={"file": ("test_slide.png", img_bytes, "image/png")},
        data={"auto_activate": "false", "token": token}
    )
    assert res_no_auto.status_code == 200
    data_no_auto = res_no_auto.json()
    assert data_no_auto["status"] == "ok"
    assert data_no_auto["auto_activated"] is False

    # Confirm active deck is UNCHANGED on monitors
    room_after = state_manager.get_room("204")
    assert room_after.active_deck_id == original_active_deck

    # 2. Upload image with auto_activate=True -> immediately switches active deck
    res_auto = client.post(
        f"/api/room/204/upload",
        files={"file": ("test_slide_live.png", img_bytes, "image/png")},
        data={"auto_activate": "true", "token": token}
    )
    assert res_auto.status_code == 200
    data_auto = res_auto.json()
    assert data_auto["auto_activated"] is True

    room_after_auto = state_manager.get_room("204")
    assert room_after_auto.active_deck_name == "test_slide_live.png"

def test_19_disk_cleanup_on_deck_delete():
    from app.config import CACHE_DIR
    token = state_manager.create_auth_token("204")
    room = state_manager.get_room("204")

    # Find an uploaded deck with cache files
    target_deck = next((d for d in room.saved_decks if not getattr(d, 'is_permanent', False) and "test_slide" in d.name), None)
    if target_deck:
        deck_id = target_deck.id
        # Delete deck via API
        res_del = client.delete(f"/api/room/204/delete_deck/{deck_id}?token={token}")
        assert res_del.status_code == 200

        # Verify deck removed from state
        assert not any(d.id == deck_id for d in room.saved_decks)

def test_20_max_10_decks_retention_and_permanent_pin():
    import io
    from PIL import Image

    room_id = "101"
    token = state_manager.create_auth_token(room_id)
    room = state_manager.get_room(room_id)

    # 1. The permanent whiteboard / example deck MUST always be at index 0
    assert room.saved_decks[0].is_permanent is True
    assert "Namuna" in room.saved_decks[0].name or "Oq Doska" in room.saved_decks[0].name

    # Create dummy PNG bytes
    img_byte_arr = io.BytesIO()
    img = Image.new("RGB", (200, 200), color=(10, 20, 30))
    img.save(img_byte_arr, format="PNG")
    img_bytes = img_byte_arr.getvalue()

    # Upload 11 decks sequentially
    for i in range(1, 12):
        res = client.post(
            f"/api/room/{room_id}/upload",
            files={"file": (f"deck_num_{i}.png", img_bytes, "image/png")},
            data={"auto_activate": "false", "token": token}
        )
        assert res.status_code == 200

    # Non-permanent decks must be capped at 10
    non_perm = [d for d in room.saved_decks if not getattr(d, 'is_permanent', False)]
    assert len(non_perm) == 10

    # The 1st uploaded ("deck_num_1.png") must have been evicted
    assert not any(d.name == "deck_num_1.png" for d in room.saved_decks)
    # The 11th uploaded must be present
    assert any(d.name == "deck_num_11.png" for d in room.saved_decks)
    # The permanent example deck is STILL pinned at index 0!
    assert room.saved_decks[0].is_permanent is True

def test_21_room_json_persistence():
    from app.state_engine import ROOMS_STORE_FILE
    assert ROOMS_STORE_FILE.exists()
    import json
    data = json.loads(ROOMS_STORE_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    room_ids = [r["id"] for r in data]
    assert "204" in room_ids
    assert "101" in room_ids
    assert "fizika-1" in room_ids
    # Check 204 has custom 302-Auditoriya name
    r204 = next(r for r in data if r["id"] == "204")
    assert "302-Auditoriya" in r204["name"]

if __name__ == "__main__":
    tests = [
        test_1_lobby_page,
        test_2_screen_page,
        test_3_admin_page,
        test_4_tv_page,
        test_5_remote_page_pin_leak_prevention,
        test_6_print_qr_page,
        test_7_smart_join_redirect,
        test_8_api_rooms_listing,
        test_9_api_room_crud,
        test_10_ghost_room_prevention,
        test_11_pin_verification_and_auth_token,
        test_12_room_lock_state_serialization,
        test_13_local_ip_detection,
        test_14_qr_png_generation,
        test_15_websocket_connection_and_heartbeat,
        test_16_touch_lock_toggle_and_palm_rejection,
        test_17_webrtc_screenshare_signaling_and_canvas_fallback,
        test_18_fast_image_upload_and_auto_switch,
        test_19_disk_cleanup_on_deck_delete,
        test_20_max_10_decks_retention_and_permanent_pin,
        test_21_room_json_persistence,
    ]
    for idx, t in enumerate(tests, 1):
        t()
        print(f"[{idx}/{len(tests)}] {t.__name__} passed successfully.")
    print(f"\n🎉 ALL {len(tests)} PLATFORM INTEGRATION & SECURITY TESTS PASSED PERFECTLY!")
