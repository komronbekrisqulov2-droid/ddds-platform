# 🏛 DDDS Cloud (Distributed Dual-Display Smart Classroom Platform)

**DDDS Cloud** — Universitet va ta'lim muassasalari auditoriyalari uchun ikkita mustaqil Smart Monitorni (Dual-Display) simsiz, real vaqtda sinxron boshqaruvchi ko'p xonali (Multi-Tenant Cloud SaaS) veb-platformasi.

---

## 🎯 1. Hal qilingan Muammolar va Zero-Friction Flow

1. **Kabellar va drayverlar chalkashligiga barham:**
   - 100% brauzer asosida ishlaydi. Noutbukka maxsus dastur, `.exe` yoki drayver o'rnatish talab etilmaydi.
2. **Noutbuk to'liq erkin:**
   - O'qituvchi noutbukida bemalol Word ochib talabalarni baholashi, Telegram yoki brauzerda boshqa ishlari bilan shug'ullanishi mumkin — monitorlarga bu aslo xalaqit bermaydi (OS klaviaturasi o'g'irlanmaydi).
3. **Bitta ekranning cheklanganligini bartaraf etish:**
   - Auditoriyadagi 2 ta Smart Monitor birgalikda parallel ishlaydi:
     - **Mirror Rejimi:** Ikkala monitor bir xil slaydni ko'rsatadi (Katta zallar uchun).
     - **Split Rejimi:** 1-Monitorda masala sharti, 2-Monitorda yechim yoki formulalar ko'rsatiladi.
4. **Stoldagi Doimiy A4 QR Stend:**
   - O'qituvchi xonaga kiradi, stol ustidagi A4 QR stendni kamerasi bilan skanerlaydi (`/join/{room_id}`). Tizim smartfonni aniqlab darhol pultga yo'naltiradi.

---

## 🏛 2. Tizim Rollari va Havolalar

Har bir auditoriya (masalan, `204`, `101`, `fizika-1`) mustaqil ravishda quyidagi 4 ta asosiy qismdan iborat:

| Rol | Manzil (URL) | Tavsif |
|---|---|---|
| **Lobby (Bosh Sahifa)** | `http://localhost:8000/` | Barcha xonalar ro'yxati va yangi auditoriya ochish |
| **1-Smart Monitor (Chap)** | `http://localhost:8000/screen/{room_id}/1` | Chap monitorda Kiosk to'liq ekran rejimida ochiladi |
| **2-Smart Monitor (O'ng)** | `http://localhost:8000/screen/{room_id}/2` | O'ng monitorda Kiosk to'liq ekran rejimida ochiladi |
| **O'qituvchi Boshqaruvi** | `http://localhost:8000/admin/{room_id}` | Noutbuk/planshet uchun Dual-Display boshqaruv paneli |
| **Smartfon Masofaviy Pulti** | `http://localhost:8000/remote/{room_id}` | O'qituvchi smartfoni uchun lazerli sensor pult |
| **Aqlli Yo'naltirgich (Join)** | `http://localhost:8000/join/{room_id}` | Smartfon bo'lsa pultga, kompyuter bo'lsa panelga yo'naltiradi |
| **Chop etish stendi (A4)** | `http://localhost:8000/print_qr/{room_id}` | O'qituvchi stoli uchun buklanuvchi A4 QR stend |

---

## ⚙️ 3. Asosiy Funksional Modullar

### 1. Authoritative State Engine (Parallel Sinxronizatsiya)
- Har bir holat o'zgarishi serverda monoton o'suvchi `version = version + 1` oladi.
- WebSocket orqali har ikki monitorga `asyncio.gather` bilan parallel tarqatiladi.
- Kechikish (Latency): Lokal Wi-Fi da `< 15ms`, bulutda `< 40ms`.
- **Auto State Catch-Up:** Aloqa uzilib qayta ulangan monitor darhol serverdan eng so'nggi nufuzli versiyani oladi.
- **Heartbeat & Health:** Real vaqtda har bir monitor va pultning pingi (masalan `12ms 🟢`) ko'rinib turadi.

### 2. Universal Media Hub (PPTX, PDF, Video)
- **PowerPoint (.pptx):** `python-pptx` orqali matnlar, sarlavhalar, shakllar va eng muhimi **Speaker Notes** (ma'ruzachi eslatmalari) ajratiladi. Slaydlar yuqori sifatli WebP formatida keshlanadi.
- **PDF Hujjatlar:** `pypdfium2` yordamida har bir sahifa 1080p WebP formatiga keshlanadi (monitorlarda `<20ms` da yuklanadi).
- **Dual-Display Sinxron Video (MP4 / WebM):** Ikkala monitorda bir vaqtda Play/Pause bo'ladi va vaqt farqi (`Drift Correction < 0.3s`) avtomatik tekislanadi.
- **Standart Tayyor Dars:** Tizim ishga tushishi bilanoq har bir xonada interaktiv tayyor slaydlar to'plami faol bo'ladi.

### 3. Jonli Ekran Uzatish (WebRTC 1080p 60FPS & Canvas Fallback)
- O'qituvchi noutbukidagi istalgan oynani (3D dastur, kod muharriri, simulyatsiya) 1-klikda ikkala monitorga uzatadi.
- **WebRTC Peer-to-Peer:** STUN signaling va to'g'ridan-to'g'ri brauzerdan monitorlarga uzatish.
- **WebSocket Canvas Fallback:** Agar tarmoqdagi xavfsizlik devori (firewall) WebRTC UDP portlarini bloklasa, kadrlar avtomatik Canvas orqali WebSocket orqali 30 FPS da o'tadi.

### 4. Interaktiv Lazer Ko'rsatkich va Chizish (Annotation)
- O'qituvchi telefonidagi sensorli maydonda barmog'ini yurgizganda, ikkala monitor ekranida qizil nurlanuvchi lazer nuqtasi (pulsatsiya effekti bilan) real vaqtda harakatlanadi.
- **Smart Board Toolbar:** Smart monitor ekranida suzuvchi paneldan foydalanib to'g'ridan-to'g'ri slayd ustiga chizish, marker yoki o'chirg'ichdan foydalanish mumkin. Hech qanday OS virtual klaviaturasi ekranga qalqib chiqmaydi.

### 5. Stoldagi A4 QR Stend
- Har bir auditoriya uchun chop etishga tayyor A4 formatidagi QR-kodli stend sahifasi (`/print_qr/{room_id}`).
- Buklash va kesish chiziqlari (A-frame table tent stand) mavjud.

---

## 🛡 4. Xavfsizlik va Mustaqillik

1. **Host OS Isolation:** Hech qanday `pyautogui`, `keybd_event`, yoki `ctypes` ishlatilmaydi. 100% veb-texnologiyalar.
2. **Room PIN:** O'qituvchi boshqaruvi 4 xonali PIN bilan himoyalangan (masalan `2040`, `1010`, `7788`).
3. **Zero-CDN Mustaqilligi:** Barcha CSS, JS, SVG va shriftlar lokal yuklanadi. Tashqi internet uzilsa ham universitet ichki Wi-Fi tarmog'ida 100% ishlaydi.

---

## 🚀 5. O'rnatish va Ishga Tushirish

### A. Python orqali (Tavsiya etiladi)
```bash
# 1. Bog'liqliklarni o'rnatish
pip install -r requirements.txt

# 2. Serverni ishga tushirish
python run.py --host 0.0.0.0 --port 8000
```
Yoki Windowsda to'g'ridan-to'g'ri `start.bat` faylini ikki marta bosing!

### B. Docker orqali
```bash
# Docker konteynerini yig'ish va ishga tushirish
docker-compose up --build -d
```

### C. Testlarni ishga tushirish
```bash
python tests/test_platform.py
```

---

## 📱 Foydalanish Bo'yicha 3 Qadam:

1. **Monitorlarni tayyorlash:**
   - 1-Smart Monitorda: `http://server_ip:8000/screen/204/1` (F11 bosib to'liq ekranga o'tkazing).
   - 2-Smart Monitorda: `http://server_ip:8000/screen/204/2` (F11 bosib to'liq ekranga o'tkazing).
2. **O'qituvchi ulanishi:**
   - Stoldagi A4 QR kodni telefon bilan skanerlaydi (`/join/204`).
   - 4 xonali PIN-kodni (masalan `2040`) kiritadi.
3. **Darsni boshqarish:**
   - Slaydlarni almashtiring, Mirror yoki Split rejimiga o'ting, lazer touchpad yordamida doskani ko'rsating va ma'ruzachi eslatmalarini smartfoningizdan o'qing!

