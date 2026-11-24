# DDDS Cloud — Global Serverga O'rnatish Qo'llanmasi (Production Deployment)

Ushbu qo'llanma orqali DDDS platformasini istalgan Linux (Ubuntu) serveriga o'rnatib, rasmiy domen va bepul SSL (HTTPS) sertifikati bilan global internetga chiqarishingiz mumkin.

---

## 1. Talablar

1. **VPS Server (Linux Ubuntu 22.04 yoki 24.04 LTS):**
   * Kamida 2 vCPU, 2-4 GB RAM, 20 GB SSD.
   * O'zbekiston ichida: VDS.uz, PS.uz yoki Eskiz.uz (Tas-IX ichida kechikish atigi 1-5ms bo'ladi).
   * Xalqaro: Hetzner yoki DigitalOcean.
2. **Domen nomi:**
   * Masalan: `ddds.uz` yoki universitetning tekin subdomeni: `ddds.univer.uz`.
   * Domen boshqaruv panelida (DNS) `A` yozuvini serveringizning ommaviy IP manziliga yo'naltiring:
     ```
     Type: A
     Host: @ (yoki ddds)
     Value: SERVER_IP_MANZILI
     ```

---

## 2. Serverda Dastlabki Dasturlarni O'rnatish

Serveringizga SSH orqali kiring va quyidagi buyruqlarni bajaring:

```bash
# Server paketlarini yangilash
sudo apt update && sudo apt upgrade -y

# Docker, Nginx va Certbot o'rnatish
sudo apt install -y docker.io docker-compose git nginx certbot python3-certbot-nginx

# Docker xizmatini yoqish
sudo systemctl enable --now docker
```

---

## 3. Loyihani Serverga Yuklash va Ishga Tushirish

```bash
# Loyihani yuklash uchun papka ochish
mkdir -p /var/www/ddds
cd /var/www/ddds

# Fayllarni git orqali yoki SCP bilan yuklaysiz:
# git clone <sizning-repo-linki> .

# Docker orqali fonda ishga tushirish:
docker-compose up -d --build
```

---

## 4. Nginx va Bepul SSL (HTTPS) Sozlash

```bash
# Nginx konfiguratsiya faylini nusxalash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/ddds.conf

# Fayldagi domenni o'zingiznikiga o'zgartiring (masalan ddds.uz)
sudo nano /etc/nginx/sites-available/ddds.conf

# Saytni faollashtirish
sudo ln -s /etc/nginx/sites-available/ddds.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Bepul Let's Encrypt SSL (HTTPS) sertifikatini o'rnatish:
sudo certbot --nginx -d sizning-domeningiz.uz
```

*Certbot avtomatik ravishda HTTPS ni yoqadi va har 3 oyda sertifikatni o'zi avtomatik yangilab turadi.*

---

## 5. NAT va Mobil Tarmoqlararo WebRTC Uchun CoTURN (Ixtiyoriy, tavsiya etiladi)

Turli viloyatlardagi o'qituvchilar va mobil provayderlar (Ucell, Beeline, Uztelecom) o'rtasida WebRTC jonli ekran oqimi NAT to'siqlaridan qat'i nazar o'tishi uchun:

```bash
sudo apt install -y coturn
sudo systemctl enable --now coturn
```

---

## 6. Natija

Endi tizim dunyoning istalgan burchagidan:
* **Admin:** `https://sizning-domeningiz.uz/admin/{room_id}`
* **Monitorlar:** `https://sizning-domeningiz.uz/screen/1`
* **Pult:** `https://sizning-domeningiz.uz/remote/{room_id}`

orqali xavfsiz (yashil qulfli HTTPS / WSS) rejimida 100% tezkor ishlaydi!

