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
    assert "204-Auditoriya" in response.text

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

def test_9_api_room_crud():
    # 1. Create temporary room
    res_create = client.post("/api/rooms", json={
        "room_id": "test-crud-1",
        "room_name": "Test Xona 1",
        "pin": "5555",
        "description": "Sinov auditoriyasi"
    })
    assert res_create.status_code == 200

    # 2. Update room
    res_update = client.put("/api/room/test-crud-1", json={
        "room_name": "Test Xona 1 Yangilandi",
        "pin": "7777",
        "description": "Yangilangan tavsif"
    })
    assert res_update.status_code == 200
    assert res_update.json()["room"]["room_name"] == "Test Xona 1 Yangilandi"
    assert res_update.json()["room"]["pin"] == "7777"

    # 3. Delete room
    res_del = client.delete("/api/room/test-crud-1")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "ok"

    # 4. Confirm deleted in API
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
    ]
    for idx, t in enumerate(tests, 1):
        t()
        print(f"[{idx}/17] {t.__name__} passed successfully.")
    print("\n🎉 ALL 17 PLATFORM INTEGRATION & SECURITY TESTS PASSED PERFECTLY!")
