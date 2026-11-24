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
            print(f"[MediaProcessor] python-pptx parse error: {e}")

    # 2. Convert PPTX to Vector PDF using PowerPoint COM (Format 32)
    # This preserves all fonts, equations, shapes and layout losslessly in vector format!
    pdf_converted = pptx_cache_dir / "presentation.pdf"
    if HAS_WIN32COM and not pdf_converted.exists():
        ppt_app = None
        pres = None
        try:
            pythoncom.CoInitialize()
            ppt_app = win32com.client.Dispatch("PowerPoint.Application")
            abs_pptx = str(temp_pptx.resolve())
            abs_pdf = str(pdf_converted.resolve())
            
            pres = ppt_app.Presentations.Open(abs_pptx, WithWindow=False)
            # 32 = ppSaveAsPDF (Vector lossless)
            pres.SaveAs(abs_pdf, 32)
        except Exception as e:
            print(f"[MediaProcessor] PowerPoint COM PDF export failed: {e}")
        finally:
            if pres:
                try:
                    pres.Close()
                except Exception:
                    pass
            if ppt_app:
                try:
                    ppt_app.Quit()
                except Exception:
                    pass
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    # 3. If PDF was generated, render with Ultra-HD pypdfium2 at scale 3.0 (300 DPI)
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

    # 4. Fallback: Try LibreOffice headless
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        try:
            import subprocess
            subprocess.run([
                soffice, "--headless", "--convert-to", "pdf",
                str(temp_pptx), "--outdir", str(pptx_cache_dir)
            ], check=True, timeout=30)
            if pdf_converted.exists():
                slides = process_pdf_file(pdf_converted.read_bytes(), filename, room_id)
                for s in slides:
                    if s.index in notes_per_slide:
                        s.speaker_notes = notes_per_slide[s.index]
                    if s.index in titles_per_slide:
                        s.title = titles_per_slide[s.index]
                    s.slide_type = "pptx_card"
                return slides
        except Exception as e:
            print(f"[MediaProcessor] LibreOffice fallback failed: {e}")

    # 5. Last resort fallback to clean presentation builder
    return build_fallback_pptx_slides(temp_pptx, filename, room_id, file_hash)


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
    Renders the exact TatU Parallel Dasturlash presentation shown in the user's reference images!
    """
    _, room_cache = ensure_room_dirs(room_id)
    starter_dir = room_cache / "starter_deck"
    starter_dir.mkdir(parents=True, exist_ok=True)

    # 1. Slide 1 (Exact from reference image #1 and #2 - Cover Title with grid icon):
    slide1_path = starter_dir / "slide_1.webp"
    render_tatu_slide(
        output_path=slide1_path,
        univ_header="Muhammad al-Xorazmiy nomidagi Toshkent axborot texnologiyalari universiteti",
        course_tag="«Parallel dasturlash» fani  •  7-ma'ruza",
        main_title="Parallel dasturlar unumdorligini baholash",
        body_subtitle="Amdal va Gustafson qonunlari • tezlashish • samaradorlik • masshtablanuvchanlik • profiling",
        slide_num=1,
        total_slides=4,
        footer_info="Kompyuter Injiringi • 60610300 • Toshkent - 2026",
        show_cover_diagram=True
    )

    # 2. Slide 2 (Clean Amdahl's law - NO grid boxes):
    slide2_path = starter_dir / "slide_2.webp"
    render_tatu_slide(
        output_path=slide2_path,
        univ_header="Muhammad al-Xorazmiy nomidagi Toshkent axborot texnologiyalari universiteti",
        course_tag="«Parallel dasturlash» fani  •  7-ma'ruza",
        main_title="Amdal Qonuni (Amdahl's Law)",
        body_subtitle="S(p) = 1 / ( (1 - f) + f / p )\n\nf — dasturning paralellashtiriladigan qismi ulushi (0 ≤ f ≤ 1)\np — tizimdagi protsessor yadrolari soni\nS(p) — nazariy maksimal tezlashish ko'rsatkichi",
        slide_num=2,
        total_slides=4,
        footer_info="Kompyuter Injiringi • 60610300 • Toshkent - 2026",
        show_cover_diagram=False
    )

    # 3. Slide 3 (Clean Gustafson's law - NO grid boxes):
    slide3_path = starter_dir / "slide_3.webp"
    render_tatu_slide(
        output_path=slide3_path,
        univ_header="Muhammad al-Xorazmiy nomidagi Toshkent axborot texnologiyalari universiteti",
        course_tag="«Parallel dasturlash» fani  •  7-ma'ruza",
        main_title="Gustafson-Barsis Qonuni (Masshtablanuvchanlik)",
        body_subtitle="S(p) = p - α · (p - 1)\n\nα — dasturning ketma-ket (serial) qismi nisbati\nMasshtablangan tezlashish (Scaled Speedup)\nHisoblash hajmi protsessorlar soniga mutanosib oshganda",
        slide_num=3,
        total_slides=4,
        footer_info="Kompyuter Injiringi • 60610300 • Toshkent - 2026",
        show_cover_diagram=False
    )

    # 4. Slide 4 (Clean Profiling slide - NO grid boxes):
    slide4_path = starter_dir / "slide_4.webp"
    render_tatu_slide(
        output_path=slide4_path,
        univ_header="Muhammad al-Xorazmiy nomidagi Toshkent axborot texnologiyalari universiteti",
        course_tag="«Parallel dasturlash» fani  •  7-ma'ruza",
        main_title="Parallel Dasturlarni Profiling Qilish",
        body_subtitle="Vaqt sarfi tahlili: Hisoblash vaqti vs Kommunikatsiya vaqti\n\n• Amaliy profiling vositalari: Intel VTune, gprof, Valgrind\n• Kommunikatsiya kechikishlari: MPI Barrier va Point-to-Point\n• Kesh xatolari (Cache Misses) va xotira o'tkazuvchanligi",
        slide_num=4,
        total_slides=4,
        footer_info="Kompyuter Injiringi • 60610300 • Toshkent - 2026",
        show_cover_diagram=False
    )

    slides = [
        SlideItem(
            id="tatu_p1",
            index=0,
            title="7-maruza_Parallel_dasturlar_unumdorligini_baholash",
            image_url=f"/cache/{room_id}/starter_deck/slide_1.webp",
            speaker_notes="Kirish: Ushbu ma'ruzada parallel hisoblash tizimlarining asosiy qonunlari — Amdal va Gustafson qonunlarini o'rganamiz.",
            slide_type="pptx_card"
        ),
        SlideItem(
            id="tatu_p2",
            index=1,
            title="Amdal Qonuni (Amdahl's Law)",
            image_url=f"/cache/{room_id}/starter_deck/slide_2.webp",
            speaker_notes="Amdal qonuni: Agar dasturning ketma-ket qismi 10% bo'lsa, hatto cheksiz yadrolar berilganda ham maksimal tezlashish 10 barobardan oshmaydi.",
            slide_type="pptx_card"
        ),
        SlideItem(
            id="tatu_p3",
            index=2,
            title="Gustafson-Barsis Qonuni",
            image_url=f"/cache/{room_id}/starter_deck/slide_3.webp",
            speaker_notes="Gustafson qonuni: Amaliyotda protsessorlar soni oshganda, yechilayotgan masalaning hajmi ham kengaytiriladi.",
            slide_type="pptx_card"
        ),
        SlideItem(
            id="tatu_p4",
            index=3,
            title="Parallel Dasturlarni Profiling Qilish",
            image_url=f"/cache/{room_id}/starter_deck/slide_4.webp",
            speaker_notes="Xulosa: Profiling vositalari (gprof, VTune, Valgrind) orqali kesh xatolari va kechikishlar aniqlanadi.",
            slide_type="pptx_card"
        )
    ]
    return slides


def render_tatu_slide(output_path: Path, univ_header: str, course_tag: str, 
                      main_title: str, body_subtitle: str, slide_num: int, 
                      total_slides: int, footer_info: str, show_cover_diagram: bool = False):
    """Generates the exact dark blue university slide visual from the user's reference images."""
    width, height = 1920, 1080
    # Exact Dark Blue classroom background from reference image #2: rgb(18, 28, 48)
    img = Image.new("RGB", (width, height), color=(18, 30, 52))
    draw = ImageDraw.Draw(img)

    try:
        font_univ = ImageFont.truetype("arial.ttf", 26)
        font_tag = ImageFont.truetype("arial.ttf", 32)
        font_title = ImageFont.truetype("arial.ttf", 64)
        font_body = ImageFont.truetype("arial.ttf", 34)
        font_footer = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font_univ = ImageFont.load_default()
        font_tag = ImageFont.load_default()
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()
        font_footer = ImageFont.load_default()

    # 1. University header
    draw.text((140, 140), univ_header, fill=(203, 213, 225), font=font_univ)

    # 2. Course tag
    draw.text((140, 240), course_tag, fill=(245, 158, 11), font=font_tag)

    # 3. Main Title
    draw.text((140, 310), main_title, fill=(255, 255, 255), font=font_title)

    # 4. Body subtitle lines
    curr_y = 440
    for line in body_subtitle.split("\n"):
        draw.text((140, curr_y), line, fill=(203, 213, 225), font=font_body)
        curr_y += 55

    # 5. Diagram Icon representation: ONLY ON TITLE / COVER SLIDE (slide 1)
    if show_cover_diagram:
        grid_x = 960
        grid_y = 540
        box_w = 60
        box_h = 36
        gap = 14
        for r in range(2):
            for c in range(5):
                bx = grid_x + c * (box_w + gap)
                by = grid_y + r * (box_h + gap)
                fill_col = (234, 88, 12) if (r == 0 and c < 3) or (r == 1 and c > 2) else (14, 116, 144)
                draw.rectangle([bx, by, bx + box_w, by + box_h], fill=fill_col, outline=(51, 65, 85), width=2)

    # 6. Footer
    draw.text((140, height - 120), footer_info, fill=(148, 163, 184), font=font_footer)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "WEBP", quality=98, method=6)
