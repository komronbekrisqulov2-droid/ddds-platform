import os
import shutil
import hashlib
import time
import glob
from pathlib import Path
from typing import List, Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont

from app.config import UPLOADS_DIR, CACHE_DIR
from app.models import SlideItem

# Check engines
try:
    import pypdfium2 as pdfium
    HAS_PDFIUM = True
except ImportError:
    HAS_PDFIUM = False

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

try:
    from pptx import Presentation
    HAS_PPTX = True
except ImportError:
    HAS_PPTX = False

try:
    import win32com.client
    import pythoncom
    HAS_WIN32COM = True
except ImportError:
    HAS_WIN32COM = False


def get_file_hash(content: bytes) -> str:
    return hashlib.md5(content).hexdigest()[:12]


def ensure_room_dirs(room_id: str):
    room_upload = UPLOADS_DIR / room_id
    room_cache = CACHE_DIR / room_id
    room_upload.mkdir(parents=True, exist_ok=True)
    room_cache.mkdir(parents=True, exist_ok=True)
    return room_upload, room_cache


def process_pdf_file(file_bytes: bytes, filename: str, room_id: str) -> List[SlideItem]:
    """Convert each PDF page into Ultra-HD WebP image (300 DPI, razor-sharp vector clarity)."""
    file_hash = get_file_hash(file_bytes)
    _, room_cache = ensure_room_dirs(room_id)
    pdf_cache_dir = room_cache / f"pdf_{file_hash}"
    pdf_cache_dir.mkdir(parents=True, exist_ok=True)

    slides: List[SlideItem] = []

    # 1. Primary: pypdfium2 (Render at Ultra-HD scale 3.0 = 300 DPI)
    if HAS_PDFIUM:
        try:
            pdf = pdfium.PdfDocument(file_bytes)
            num_pages = len(pdf)
            for page_idx in range(num_pages):
                webp_filename = f"page_{page_idx + 1}.webp"
                webp_path = pdf_cache_dir / webp_filename
                
                if not webp_path.exists():
                    page = pdf[page_idx]
                    # Scale 3.0 provides 2880x1620 / 4K crispness
                    bitmap = page.render(scale=3.0)
                    pil_image = bitmap.to_pil()
                    pil_image.save(webp_path, "WEBP", quality=98, method=6)
                
                # Text extraction for search/notes if any
                page_text = ""
                try:
                    text_page = pdf[page_idx].get_textpage()
                    page_text = text_page.get_text_range()
                except Exception:
                    pass

                slides.append(SlideItem(
                    id=f"{file_hash}_p{page_idx + 1}",
                    index=page_idx,
                    title=f"{Path(filename).stem} - Slayd {page_idx + 1}",
                    text_content=page_text[:300] if page_text else "",
                    image_url=f"/cache/{room_id}/pdf_{file_hash}/{webp_filename}",
                    speaker_notes=f"Slayd {page_idx + 1} / {num_pages}: {Path(filename).stem}",
                    slide_type="pdf_page",
                    extra_data={"page_number": page_idx + 1, "total_pages": num_pages}
                ))
            pdf.close()
            return slides
        except Exception as e:
            print(f"[MediaProcessor] pypdfium2 failed: {e}, falling back to fitz...")

    # 2. Fallback: PyMuPDF (fitz) at 250 DPI
    if HAS_FITZ:
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            num_pages = len(doc)
            for page_idx in range(num_pages):
                webp_filename = f"page_{page_idx + 1}.webp"
                webp_path = pdf_cache_dir / webp_filename
                
                if not webp_path.exists():
                    page = doc.load_page(page_idx)
                    pix = page.get_pixmap(dpi=250)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    img.save(webp_path, "WEBP", quality=98, method=6)
                
                page_text = doc[page_idx].get_text()

                slides.append(SlideItem(
                    id=f"{file_hash}_p{page_idx + 1}",
                    index=page_idx,
                    title=f"{Path(filename).stem} - Slayd {page_idx + 1}",
                    text_content=page_text[:300] if page_text else "",
                    image_url=f"/cache/{room_id}/pdf_{file_hash}/{webp_filename}",
                    speaker_notes=f"Slayd {page_idx + 1} / {num_pages}",
                    slide_type="pdf_page",
                    extra_data={"page_number": page_idx + 1, "total_pages": num_pages}
                ))
            doc.close()
            return slides
        except Exception as e:
            print(f"[MediaProcessor] PyMuPDF failed: {e}")

    raise RuntimeError("No working PDF rendering engine found.")


def find_soffice_binary() -> Optional[str]:
    """Finds LibreOffice soffice binary across PATH and standard OS locations."""
    # 1. System PATH
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        return soffice
    
    # 2. Windows locations
    if os.name == "nt":
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            r"D:\Program Files\LibreOffice\program\soffice.exe"
        ]
        for c in candidates:
            if os.path.exists(c):
                return c

    # 3. Linux locations
    for p in ["/usr/bin/libreoffice", "/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice"]:
        if os.path.exists(p):
            return p
            
    return None


def convert_to_pdf_with_libreoffice(input_path: Path, out_dir: Path) -> Optional[Path]:
    """Converts PPTX/DOCX to Vector PDF using headless LibreOffice with isolated profile."""
    soffice = find_soffice_binary()
    if not soffice:
        return None
    try:
        import subprocess
        profile_dir = Path("/tmp/ddds_lo_profile") if os.name != "nt" else Path(os.environ.get("TEMP", ".")) / "ddds_lo"
        profile_dir.mkdir(parents=True, exist_ok=True)
        profile_uri = profile_dir.as_uri()

        cmd = [
            soffice,
            "--headless",
            "--invisible",
            "--nocrashreport",
            "--nodefault",
            "--nofirststartwizard",
            "--nologo",
            "--norestore",
            f"-env:UserInstallation={profile_uri}",
            "--convert-to", "pdf",
            str(input_path.resolve()),
            "--outdir", str(out_dir.resolve())
        ]
        env = os.environ.copy()
        env["HOME"] = "/tmp" if os.name != "nt" else env.get("USERPROFILE", "")
        env["SAL_USE_VCLPLUGIN"] = "gen"

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45, env=env)
        if proc.returncode != 0:
            print(f"[MediaProcessor] LibreOffice code {proc.returncode}: {proc.stderr.decode('utf-8', errors='ignore')}")

        # Check for expected pdf
        expected = out_dir / f"{input_path.stem}.pdf"
        if expected.exists() and expected.stat().st_size > 0:
            return expected
        for p in out_dir.glob("*.pdf"):
            if p.stat().st_size > 0:
                return p
    except Exception as e:
        print(f"[MediaProcessor] LibreOffice conversion exception: {e}")
    return None


def process_pptx_file(file_bytes: bytes, filename: str, room_id: str) -> List[SlideItem]:
    """
    Renders PowerPoint slides 100% UNCHANGED with ULTRA-HD clarity
    using PowerPoint Vector PDF Export + 300 DPI pypdfium2 renderer.
    """
    file_hash = get_file_hash(file_bytes)
    _, room_cache = ensure_room_dirs(room_id)
    pptx_cache_dir = room_cache / f"pptx_{file_hash}"
    pptx_cache_dir.mkdir(parents=True, exist_ok=True)
    
    temp_pptx = pptx_cache_dir / "presentation.pptx"
    temp_pptx.write_bytes(file_bytes)

    # 1. Extract speaker notes & titles with python-pptx
    notes_per_slide = {}
    titles_per_slide = {}
    num_slides = 0

    if HAS_PPTX:
        try:
            prs = Presentation(str(temp_pptx))
            num_slides = len(prs.slides)
            for idx, slide in enumerate(prs.slides):
                # Speaker notes
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                    t = slide.notes_slide.notes_text_frame.text.strip()
                    if t:
                        notes_per_slide[idx] = t
                # Slide title
                for shape in slide.shapes:
                    if shape.has_text_frame and shape.text_frame.text.strip():
                        titles_per_slide[idx] = shape.text_frame.text.strip()[:60]
                        break
        except Exception as e:
            print(f"[MediaProcessor] python-pptx parse warning: {e}")

    # 2. Convert PPTX to Vector PDF using PowerPoint COM (Format 32) on Windows
    pdf_converted = pptx_cache_dir / "presentation.pdf"
    if HAS_WIN32COM and not pdf_converted.exists():
        ppt_app = None
        pres = None
        try:
            pythoncom.CoInitialize()
            ppt_app = win32com.client.Dispatch("PowerPoint.Application")
            abs_pptx = str(temp_pptx.resolve())
            abs_pdf = str(pdf_converted.resolve())
            try:
                pres = ppt_app.Presentations.Open(abs_pptx, ReadOnly=1, Untitled=0, WithWindow=0)
            except Exception:
                pres = ppt_app.Presentations.Open(abs_pptx)
            # 32 = ppSaveAsPDF (Vector lossless)
            pres.SaveAs(abs_pdf, 32)
        except Exception as e:
            print(f"[MediaProcessor] PowerPoint COM PDF export error: {e}")
        finally:
            if pres:
                try: pres.Close()
                except Exception: pass
            if ppt_app:
                try: ppt_app.Quit()
                except Exception: pass
            try: pythoncom.CoUninitialize()
            except Exception: pass

    # 3. Fallback: Try LibreOffice headless (Linux & Windows)
    if not (pdf_converted.exists() and pdf_converted.stat().st_size > 0):
        lo_pdf = convert_to_pdf_with_libreoffice(temp_pptx, pptx_cache_dir)
        if lo_pdf:
            pdf_converted = lo_pdf

    # 4. If PDF was generated by either engine, render with Ultra-HD pypdfium2 at scale 3.0 (300 DPI)
    if pdf_converted.exists() and pdf_converted.stat().st_size > 0:
        slides = process_pdf_file(pdf_converted.read_bytes(), filename, room_id)
        # Attach extracted notes and titles
        for s in slides:
            if s.index in notes_per_slide:
                s.speaker_notes = notes_per_slide[s.index]
            if s.index in titles_per_slide:
                s.title = titles_per_slide[s.index]
            s.slide_type = "pptx_card"
        return slides

    # 5. Last resort fallback to clean presentation builder
    return build_fallback_pptx_slides(temp_pptx, filename, room_id, file_hash)


def process_docx_file(file_bytes: bytes, filename: str, room_id: str) -> List[SlideItem]:
    """
    Converts Word documents (.docx, .doc) into Vector PDF via LibreOffice (or Word COM on Windows),
    then renders each page into an Ultra-HD WebP slide card.
    """
    file_hash = get_file_hash(file_bytes)
    _, room_cache = ensure_room_dirs(room_id)
    doc_cache_dir = room_cache / f"doc_{file_hash}"
    doc_cache_dir.mkdir(parents=True, exist_ok=True)
    
    ext = Path(filename).suffix.lower() or ".docx"
    temp_doc = doc_cache_dir / f"document{ext}"
    temp_doc.write_bytes(file_bytes)
    pdf_converted = doc_cache_dir / "document.pdf"

    # 1. Primary: LibreOffice headless (Linux, Docker, Windows)
    lo_pdf = convert_to_pdf_with_libreoffice(temp_doc, doc_cache_dir)
    if lo_pdf:
        pdf_converted = lo_pdf

    # 2. Secondary: Windows Word COM (if on Windows)
    if not (pdf_converted.exists() and pdf_converted.stat().st_size > 0) and HAS_WIN32COM:
        word_app = None
        doc = None
        try:
            pythoncom.CoInitialize()
            word_app = win32com.client.Dispatch("Word.Application")
            abs_doc = str(temp_doc.resolve())
            abs_pdf = str(pdf_converted.resolve())
            try:
                doc = word_app.Documents.Open(abs_doc, ReadOnly=True, Visible=False)
            except Exception:
                doc = word_app.Documents.Open(abs_doc)
            # 17 = wdFormatPDF
            doc.SaveAs(abs_pdf, 17)
        except Exception as e:
            print(f"[MediaProcessor] Word COM PDF export failed: {e}")
        finally:
            if doc:
                try: doc.Close(SaveChanges=False)
                except Exception: pass
            if word_app:
                try: word_app.Quit()
                except Exception: pass
            try: pythoncom.CoUninitialize()
            except Exception: pass

    # 3. If PDF was generated, render with Ultra-HD pypdfium2 / PyMuPDF
    if pdf_converted.exists() and pdf_converted.stat().st_size > 0:
        slides = process_pdf_file(pdf_converted.read_bytes(), filename, room_id)
        for s in slides:
            s.slide_type = "word_doc"
            s.title = f"{Path(filename).stem} ({s.index + 1}-bet)"
        return slides

    raise RuntimeError("Word hujjatini PDF formatiga o'tkazish imkoni bo'lmadi. Serverda LibreOffice kerak.")


def build_fallback_pptx_slides(pptx_path: Path, filename: str, room_id: str, file_hash: str) -> List[SlideItem]:
    prs = Presentation(str(pptx_path))
    slides = []
    pptx_cache_dir = CACHE_DIR / room_id / f"pptx_{file_hash}"
    for idx, slide in enumerate(prs.slides):
        title = f"{Path(filename).stem} - Slayd {idx + 1}"
        lines = []
        notes = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            notes = slide.notes_slide.notes_text_frame.text.strip()
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    t = p.text.strip()
                    if t:
                        if not lines:
                            title = t
                        lines.append(t)
        webp_name = f"slide_{idx + 1}.webp"
        webp_path = pptx_cache_dir / webp_name
        render_clean_presentation_card(webp_path, title, lines[1:6], idx + 1, len(prs.slides))
        slides.append(SlideItem(
            id=f"{file_hash}_s{idx + 1}",
            index=idx,
            title=title,
            image_url=f"/cache/{room_id}/pptx_{file_hash}/{webp_name}",
            speaker_notes=notes or f"Slayd #{idx+1}: {title}",
            slide_type="pptx_card"
        ))
    return slides


def render_clean_presentation_card(output_path: Path, title: str, lines: List[str], num: int, total: int):
    width, height = 1920, 1080
    img = Image.new("RGB", (width, height), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)
    try:
        font_title = ImageFont.truetype("arial.ttf", 48)
        font_body = ImageFont.truetype("arial.ttf", 32)
        font_sub = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    draw.rectangle([80, 80, width - 80, 200], fill=(30, 41, 59), outline=(51, 65, 85), width=2)
    draw.text((120, 115), title[:65], fill=(248, 250, 252), font=font_title)

    y = 260
    for l in lines:
        draw.ellipse([120, y + 10, 132, y + 22], fill=(0, 210, 255))
        draw.text((150, y), l[:80], fill=(226, 232, 240), font=font_body)
        y += 75

    draw.text((80, height - 60), f"Slayd {num} / {total}", fill=(148, 163, 184), font=font_sub)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "WEBP", quality=90)


def get_default_starter_slides(room_id: str, room_name: str) -> List[SlideItem]:
    """
    Renders an inspiring, futuristic, modern education presentation
    that engages students with creative visuals, tech themes, and interactive tips.
    """
    _, room_cache = ensure_room_dirs(room_id)
    starter_dir = room_cache / "starter_deck"
    starter_dir.mkdir(parents=True, exist_ok=True)

    # Slide 1: Welcome & Innovation
    slide1_path = starter_dir / "slide_1.webp"
    render_creative_smart_slide(
        output_path=slide1_path,
        badge_tag="⚡ DDDS SMART AUDITORIYA",
        badge_color=(14, 165, 233),
        main_title="Simsiz Interaktiv Dars Platformasi",
        subtitle="Kelajak Ta'lim Texnologiyasi Bugun Amalda",
        bullet_points=[
            "Ultra-HD Slaydlar va Jonli 60 FPS Efir (WebRTC)",
            "Smartfon Pulti orqali Masofadan Boshqaruv va Lazer",
            "Ko'p Monitorli Sinxronizatsiya va Sensor Bloklash",
            "Interaktiv Oq Doska va Raqamli Qalam bilan Tahlil"
        ],
        slide_num=1,
        total_slides=4,
        quote="«Auditoriyangizni zamonaviy innovatsion markazga aylantiring»"
    )

    # Slide 2: Digital Era & AI
    slide2_path = starter_dir / "slide_2.webp"
    render_creative_smart_slide(
        output_path=slide2_path,
        badge_tag="🚀 RAQAMLI KELAJAK & SUN'IY INTELLEKT",
        badge_color=(168, 85, 247),
        main_title="Sun'iy Intellekt va Yangi Imkoniyatlar",
        subtitle="Raqamli Dunyoda Muvaffaqiyat Asoslari",
        bullet_points=[
            "Generativ modellar va zamonaviy algoritmlar rivoji",
            "Bulutli platformalar va real vaqtli kommunikatsiyalar",
            "Katta ma'lumotlar tahlili va yuqori unumdor tizimlar",
            "Nazariy bilimlarni amaliy loyihalarga aylantirish san'ati"
        ],
        slide_num=2,
        total_slides=4,
        quote="«Kelajak kasblari bugungi darslarda boshlanadi»"
    )

    # Slide 3: Interactive Learning
    slide3_path = starter_dir / "slide_3.webp"
    render_creative_smart_slide(
        output_path=slide3_path,
        badge_tag="🎯 INTERAKTIV MULOQOT",
        badge_color=(16, 185, 129),
        main_title="Qiziqarli Munozara va Jonli Tahlil",
        subtitle="Har bir talaba faol qatnashadigan muhit",
        bullet_points=[
            "Monitorda real vaqt rejimida chizish va izohlash",
            "Kichik shriftli formula va jadvallarni yaqinlashtirish (Zoom)",
            "Noutbukdagi videolarni ovozi bilan birga to'g'ridan-to'g'ri ko'rsatish",
            "Savol-javoblar va jamoaviy yechimlar tahlili"
        ],
        slide_num=3,
        total_slides=4,
        quote="«Eng yaxshi dars — o'quvchi o'zini qatnashchi his qilgan darsdir»"
    )

    # Slide 4: Motivation & Excellence
    slide4_path = starter_dir / "slide_4.webp"
    render_creative_smart_slide(
        output_path=slide4_path,
        badge_tag="💡 ILM VA RIVOJLANISH",
        badge_color=(245, 158, 11),
        main_title="O'rganishdan To'xtamang!",
        subtitle="Doimiy Harakat — Katta Zafarlar Kaliti",
        bullet_points=[
            "Katta orzular qiling va ularga qadam-baqadam erishing",
            "Xatolardan o'rganish — eng tez rivojlanish usulidir",
            "Jamoada ishlash va yangi g'oyalarni qo'rqmasdan sinash",
            "Bugungi intilish va mehnat ertangi yutuqlaringiz poydevoridir"
        ],
        slide_num=4,
        total_slides=4,
        quote="«O'rganishdan to'xtagan odam — kelajakdan ortda qoladi»"
    )

    return [
        SlideItem(
            id="ddds_s1",
            index=0,
            title="1. Simsiz Interaktiv Dars Platformasi",
            image_url=f"/cache/{room_id}/starter_deck/slide_1.webp",
            speaker_notes="Kirish: DDDS Smart Platformasiga xush kelibsiz! Bugungi darsimiz zamonaviy interaktiv texnologiyalar bilan o'tadi.",
            slide_type="pptx_card"
        ),
        SlideItem(
            id="ddds_s2",
            index=1,
            title="2. Sun'iy Intellekt va Yangi Imkoniyatlar",
            image_url=f"/cache/{room_id}/starter_deck/slide_2.webp",
            speaker_notes="2-Mavzu: Zamonaviy dunyoda AI va raqamli texnologiyalarning amaliy qo'llanilishi haqida fikr almashamiz.",
            slide_type="pptx_card"
        ),
        SlideItem(
            id="ddds_s3",
            index=2,
            title="3. Qiziqarli Munozara va Jonli Tahlil",
            image_url=f"/cache/{room_id}/starter_deck/slide_3.webp",
            speaker_notes="3-Qism: Ekranda chizish va Zoom imkoniyati bilan formulalarni birgalikda tahlil qilamiz.",
            slide_type="pptx_card"
        ),
        SlideItem(
            id="ddds_s4",
            index=3,
            title="4. O'rganishdan To'xtamang!",
            image_url=f"/cache/{room_id}/starter_deck/slide_4.webp",
            speaker_notes="Xulosa: Har doim o'rganishda davom eting! Savollaringiz bo'lsa marhamat.",
            slide_type="pptx_card"
        )
    ]


def get_whiteboard_permanent_slides(room_id: str) -> List[SlideItem]:
    """
    Generates 3 pristine whiteboard canvases (Clean White, Math Dot-Grid, Dark Academic)
    that stay permanently in the room portfolio for free drawing and formulas.
    """
    _, room_cache = ensure_room_dirs(room_id)
    wb_dir = room_cache / "whiteboard_deck"
    wb_dir.mkdir(parents=True, exist_ok=True)

    # 1. Toza Oq Doska
    p1 = wb_dir / "board_1.webp"
    if not p1.exists():
        render_whiteboard_canvas(p1, bg_color=(255, 255, 255), is_grid=False, title="TOZA OQ DOSKA")

    # 2. Katakli Matematik Doska (Grid)
    p2 = wb_dir / "board_2.webp"
    if not p2.exists():
        render_whiteboard_canvas(p2, bg_color=(252, 253, 255), is_grid=True, title="KATAKLI DOSKA (GRID)")

    # 3. Qora Akademik Doska
    p3 = wb_dir / "board_3.webp"
    if not p3.exists():
        render_whiteboard_canvas(p3, bg_color=(15, 23, 42), is_grid=False, title="QORA AKADEMIK DOSKA", is_dark=True)

    return [
        SlideItem(
            id="wb_p1",
            index=0,
            title="📋 1. Toza Oq Doska",
            image_url=f"/cache/{room_id}/whiteboard_deck/board_1.webp",
            speaker_notes="Toza oq doska: qalam yoki marker orqali formulalar va erkin chizish uchun.",
            slide_type="whiteboard_page"
        ),
        SlideItem(
            id="wb_p2",
            index=1,
            title="📐 2. Katakli Doska (Matematika & Grafik)",
            image_url=f"/cache/{room_id}/whiteboard_deck/board_2.webp",
            speaker_notes="Katakli doska: grafiklar, jadvallar va geometrik chizmalar uchun qulay.",
            slide_type="whiteboard_page"
        ),
        SlideItem(
            id="wb_p3",
            index=2,
            title="🎓 3. Qora Akademik Doska",
            image_url=f"/cache/{room_id}/whiteboard_deck/board_3.webp",
            speaker_notes="Qora fonli akademik doska: kontrastli ranglarda chizish uchun.",
            slide_type="whiteboard_page"
        )
    ]


def render_creative_smart_slide(output_path: Path, badge_tag: str, badge_color: tuple,
                                main_title: str, subtitle: str, bullet_points: list,
                                slide_num: int, total_slides: int, quote: str):
    """
    Renders an Ultra-HD (1920x1080) modern educational presentation slide
    with rich futuristic cyber-indigo styling, glowing pill tags, and sleek cards.
    """
    width, height = 1920, 1080
    # Futuristic deep cyber-indigo canvas
    img = Image.new("RGB", (width, height), color=(10, 15, 29))
    draw = ImageDraw.Draw(img)

    try:
        font_badge = ImageFont.truetype("arial.ttf", 26)
        font_title = ImageFont.truetype("arial.ttf", 62)
        font_sub = ImageFont.truetype("arial.ttf", 34)
        font_bullet = ImageFont.truetype("arial.ttf", 32)
        font_quote = ImageFont.truetype("arial.ttf", 28)
        font_footer = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font_badge = ImageFont.load_default()
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        font_bullet = ImageFont.load_default()
        font_quote = ImageFont.load_default()
        font_footer = ImageFont.load_default()

    # Subtle background accent card
    draw.rounded_rectangle([80, 60, width - 80, height - 60], radius=28, fill=(16, 24, 46), outline=(30, 45, 80), width=2)

    # Top Glowing Pill Tag
    tag_w = len(badge_tag) * 16 + 40
    draw.rounded_rectangle([130, 110, 130 + tag_w, 160], radius=25, fill=(badge_color[0]//4, badge_color[1]//4, badge_color[2]//4), outline=badge_color, width=2)
    draw.text((150, 122), badge_tag, fill=badge_color, font=font_badge)

    # Main Title & Subtitle
    draw.text((130, 190), main_title, fill=(255, 255, 255), font=font_title)
    draw.text((130, 275), subtitle, fill=(148, 163, 184), font=font_sub)

    # Horizontal glowing separator
    draw.line([(130, 335), (width - 130, 335)], fill=(30, 50, 90), width=2)

    # Bullet Points (with glowing indicators)
    curr_y = 380
    for idx, pt in enumerate(bullet_points):
        # Card background for bullet
        draw.rounded_rectangle([130, curr_y, width - 130, curr_y + 70], radius=14, fill=(22, 32, 60), outline=(38, 54, 98), width=1)
        # Bullet badge
        draw.rounded_rectangle([150, curr_y + 16, 188, curr_y + 54], radius=10, fill=badge_color)
        draw.text((163, curr_y + 20), str(idx + 1), fill=(255, 255, 255), font=font_badge)
        # Bullet text
        draw.text((210, curr_y + 18), pt, fill=(241, 245, 249), font=font_bullet)
        curr_y += 92

    # Bottom Quote Box
    draw.rounded_rectangle([130, height - 190, width - 130, height - 120], radius=14, fill=(15, 23, 42), outline=(40, 60, 100), width=1)
    draw.text((160, height - 165), quote, fill=(203, 213, 225), font=font_quote)

    # Footer
    draw.text((130, height - 95), "DDDS Cloud • Smart Classroom Platform", fill=(100, 116, 139), font=font_footer)
    draw.text((width - 240, height - 95), f"Slayd {slide_num} / {total_slides}", fill=(148, 163, 184), font=font_footer)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "WEBP", quality=98, method=6)


def render_whiteboard_canvas(output_path: Path, bg_color: tuple, is_grid: bool = False,
                            title: str = "OQ DOSKA", is_dark: bool = False):
    """Generates an Ultra-HD 1920x1080 whiteboard slide canvas with optional math grid dots."""
    width, height = 1920, 1080
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    try:
        font_header = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font_header = ImageFont.load_default()

    # Optional Math / Coordinate Grid
    if is_grid:
        grid_step = 60
        dot_color = (210, 220, 235) if not is_dark else (40, 55, 85)
        for x in range(60, width - 60, grid_step):
            for y in range(60, height - 60, grid_step):
                draw.rectangle([x - 1, y - 1, x + 1, y + 1], fill=dot_color)

    # Subtle discrete header badge at top right
    badge_bg = (235, 240, 250) if not is_dark else (25, 35, 60)
    badge_fg = (100, 116, 139) if not is_dark else (148, 163, 184)
    draw.rounded_rectangle([width - 320, 24, width - 40, 64], radius=12, fill=badge_bg)
    draw.text((width - 300, 34), f"DDDS • {title}", fill=badge_fg, font=font_header)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "WEBP", quality=95, method=6)
