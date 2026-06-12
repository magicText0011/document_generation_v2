# # конвертация в docx
# import argparse
# import io
# from typing import List, Mapping
# from pathlib import Path
#
# import numpy as np
# from PIL import Image, UnidentifiedImageError
# import easyocr
# from PyPDF2 import PdfReader
# from PyPDF2.errors import EmptyFileError
# from pdf2image import convert_from_bytes  # OCR fallback для PDF
# from docx import Document  # <- импорт для DOCX
#
# # OCR-движок (русский + английский)
# READER = easyocr.Reader(['ru', 'en'])
#
#
# def image_to_text(raw: bytes) -> str:
#     """OCR для JPG/PNG → текст."""
#     if not raw:
#         return "(ошибка: пустой файл изображения)"
#     try:
#         img = Image.open(io.BytesIO(raw))
#     except UnidentifiedImageError:
#         return "(ошибка: файл не является изображением)"
#     except Exception as e:
#         return f"(ошибка: изображение повреждено: {e})"
#
#     results = _get_reader().readtext(np.array(img), detail=0)
#     lines = [str(line).strip() for line in results if str(line).strip()]
#     return "\n".join(lines).strip() if lines else "(пустой документ / нет текста)"
#
#
# def pdf_to_text(raw: bytes) -> str:
#     """
#     Извлечение текста из PDF → текст.
#     1) Пытаемся вытащить текст через PyPDF2.
#     2) Если текста нет (скан), делаем OCR каждой страницы через easyocr.
#     """
#     if not raw:
#         return "(ошибка: пустой PDF-файл)"
#
#     buf = io.BytesIO(raw)
#     try:
#         reader = PdfReader(buf)
#     except EmptyFileError:
#         return "(ошибка: PDF пустой)"
#     except Exception as e:
#         return f"(ошибка: PDF повреждён: {e})"
#
#     texts: List[str] = []
#     # Пытаемся сначала обычное текстовое извлечение
#     for i, page in enumerate(reader.pages):
#         try:
#             t = page.extract_text() or ""
#         except Exception as e:
#             texts.append(f"[ошибка чтения страницы {i + 1}: {e}]")
#             continue
#
#         if t.strip():
#             texts.append(t.strip())
#
#     pure_text = "\n\n".join(texts).strip() if texts else ""
#
#     # Если что-то удалось вытащить — возвращаем
#     if pure_text:
#         return pure_text
#
#     # Fallback: PDF, похожий на скан → OCR
#     try:
#         images = convert_from_bytes(raw)
#     except Exception as e:
#         return f"(ошибка OCR PDF (конвертация в изображения): {e})"
#
#     ocr_pages: List[str] = []
#     for img in images:
#         try:
#             results = _get_reader().readtext(np.array(img), detail=0)
#             lines = [str(line).strip() for line in results if str(line).strip()]
#             page_text = "\n".join(lines).strip()
#             if page_text:
#                 ocr_pages.append(page_text)
#         except Exception as e:
#             ocr_pages.append(f"[ошибка OCR страницы: {e}]")
#
#     ocr_text = "\n\n".join(ocr_pages).strip()
#     return ocr_text if ocr_text else "(пустой документ / нет текста)"
#
#
# def docx_to_text(raw: bytes) -> str:
#     """Извлечение текста из DOCX → текст."""
#     if not raw:
#         return "(ошибка: пустой DOCX-файл)"
#
#     try:
#         buf = io.BytesIO(raw)
#         doc = Document(buf)
#     except Exception as e:
#         return f"(ошибка: DOCX повреждён или не читается: {e})"
#
#     lines: List[str] = []
#     for p in doc.paragraphs:
#         text = (p.text or "").strip()
#         if text:
#             lines.append(text)
#
#     return "\n".join(lines).strip() if lines else "(пустой документ / нет текста)"
#
#
# def write_txt_and_docx(text: str, base_path: Path) -> None:
#     """
#     Вспомогательная функция: сохраняет текст в .txt и .docx.
#     base_path — путь без суффикса (например out_dir / 'file_stem').
#     """
#     txt_path = base_path.with_suffix('.txt')
#     docx_path = base_path.with_suffix('.docx')
#
#     # Запись TXT
#     try:
#         txt_path.write_text(text, encoding="utf-8")
#     except Exception as e:
#         print(f"[ERROR] Не удалось записать TXT {txt_path}: {e}")
#
#     # Создание DOCX
#     try:
#         doc = Document()
#         # Разбиваем по двойным переводам строки как логические блоки
#         blocks = text.split("\n\n")
#         for i, block in enumerate(blocks):
#             # Внутри блока сохраняем переносы строк как отдельные параграфы
#             lines = block.splitlines()
#             if not lines:
#                 # пустой блок — добавим пустой параграф
#                 doc.add_paragraph()
#             else:
#                 for line in lines:
#                     doc.add_paragraph(line)
#             # между блоками добавляем пустой параграф (чтобы сохранить визуальное разделение)
#             if i != len(blocks) - 1:
#                 doc.add_paragraph()
#         doc.save(docx_path)
#     except Exception as e:
#         print(f"[ERROR] Не удалось записать DOCX {docx_path}: {e}")
#
#
# def process_file(path: Path, out_dir: Path) -> None:
#     """Обработка одного файла: извлечение текста или пропуск.
#     По умолчанию сохраняет результат в TXT и DOCX (если возможно).
#     Сигнатура и поведение функции сохранены для совместимости с импортом.
#     """
#     if not path.is_file():
#         print(f"[SKIP] {path} не файл")
#         return
#
#     suffix = path.suffix.lower()
#     raw = path.read_bytes()
#     out_dir = Path(out_dir)
#     out_dir.mkdir(parents=True, exist_ok=True)
#     base_out = out_dir / path.stem
#
#     if suffix in [".jpg", ".jpeg", ".png"]:
#         print(f"[INFO] OCR image -> TXT/DOCX: {path}")
#         text = image_to_text(raw)
#         write_txt_and_docx(text, base_out)
#         print(f"[OK] {path} -> {base_out.with_suffix('.txt')}, {base_out.with_suffix('.docx')}")
#
#     elif suffix == ".pdf":
#         print(f"[INFO] PDF -> TXT/DOCX: {path}")
#         text = pdf_to_text(raw)
#         write_txt_and_docx(text, base_out)
#         print(f"[OK] {path} -> {base_out.with_suffix('.txt')}, {base_out.with_suffix('.docx')}")
#
#     elif suffix == ".docx":
#         print(f"[INFO] DOCX -> TXT/DOCX: {path}")
#         text = docx_to_text(raw)
#         write_txt_and_docx(text, base_out)
#         print(f"[OK] {path} -> {base_out.with_suffix('.txt')}, {base_out.with_suffix('.docx')}")
#
#     elif suffix == ".txt":
#         # Сохраняем исходный TXT и создаём DOCX
#         print(f"[INFO] COPY TXT -> TXT/DOCX: {path}")
#         try:
#             text = path.read_text(encoding="utf-8")
#         except Exception:
#             text = path.read_text(encoding="utf-8", errors="ignore")
#         write_txt_and_docx(text, base_out)
#         print(f"[OK] {path} -> {base_out.with_suffix('.txt')}, {base_out.with_suffix('.docx')}")
#
#     else:
#         print(f"[SKIP] {path} (неподдерживаемый формат)")
#
#
# def convert_uploaded_files(files: Mapping[str, "FileStorage"], out_dir: Path) -> List[str]:
#     """
#     Обработка файлов из Flask `request.files`.
#     JPG/PNG/PDF/DOCX -> TXT (и DOCX), TXT копируем и создаём DOCX.
#     Возвращает список сохранённых имён (как раньше — теперь включает .docx рядом с .txt).
#     Сигнатура сохранена для совместимости.
#     """
#     out_dir = Path(out_dir)
#     out_dir.mkdir(parents=True, exist_ok=True)
#
#     saved: List[str] = []
#
#     for field_name, file in files.items():
#         filename = getattr(file, "filename", "") or ""
#         if not filename:
#             continue
#
#         suffix = Path(filename).suffix.lower()
#
#         # Читаем байты; если вдруг поток уже читали раньше — пробуем отмотать и перечитать.
#         raw = file.read()
#         if not raw:
#             try:
#                 file.stream.seek(0)
#                 raw = file.read()
#             except Exception:
#                 raw = b""
#
#         base_name = Path(filename).stem
#         base_out = out_dir / base_name
#
#         if suffix in [".jpg", ".jpeg", ".png"]:
#             text = image_to_text(raw)
#             write_txt_and_docx(text, base_out)
#             saved.append(f"{base_name}.txt")
#             saved.append(f"{base_name}.docx")
#
#         elif suffix == ".pdf":
#             text = pdf_to_text(raw)
#             write_txt_and_docx(text, base_out)
#             saved.append(f"{base_name}.txt")
#             saved.append(f"{base_name}.docx")
#
#         elif suffix == ".docx":
#             text = docx_to_text(raw)
#             write_txt_and_docx(text, base_out)
#             saved.append(f"{base_name}.txt")
#             saved.append(f"{base_name}.docx")
#
#         elif suffix == ".txt":
#             # Сохраняем исходный TXT и создаём DOCX
#             txt_path = out_dir / f"{base_name}.txt"
#             try:
#                 txt_path.write_bytes(raw)
#             except Exception as e:
#                 print(f"[ERROR] Не удалось записать загруженный TXT {txt_path}: {e}")
#                 continue
#             try:
#                 text = raw.decode("utf-8")
#             except Exception:
#                 text = txt_path.read_text(encoding="utf-8", errors="ignore")
#             write_txt_and_docx(text, base_out)
#             saved.append(f"{base_name}.txt")
#             saved.append(f"{base_name}.docx")
#
#         else:
#             # неизвестные форматы игнорируем
#             continue
#
#     return saved
#
#
# def main():
#     parser = argparse.ArgumentParser(description="Конвертация JPG/PNG/PDF/DOCX в TXT и DOCX")
#     parser.add_argument("inputs", nargs="+", help="Файлы для обработки")
#     parser.add_argument(
#         "-o", "--out-dir",
#         default="out",
#         help="Папка для сохранения результатов (по умолчанию: out)",
#     )
#     args = parser.parse_args()
#
#     out_dir = Path(args.out_dir)
#     out_dir.mkdir(parents=True, exist_ok=True)
#
#     for inp in args.inputs:
#         process_file(Path(inp), out_dir)
#
#
# if __name__ == "__main__":
#     main()


#

# конвертация в txt

import argparse
import io
from typing import List, Mapping
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

# OCR-движок (easyocr/torch) грузим лениво: он тяжёлый и нужен только для
# картинок/PDF. Для DOCX/TXT он не требуется, поэтому не импортируем на старте.
READER = None


def _get_reader():
    global READER
    if READER is None:
        import easyocr
        READER = easyocr.Reader(['ru', 'en'])
    return READER


def image_to_text(raw: bytes) -> str:
    """OCR для JPG/PNG → текст."""
    if not raw:
        return "(ошибка: пустой файл изображения)"
    try:
        img = Image.open(io.BytesIO(raw))
    except UnidentifiedImageError:
        return "(ошибка: файл не является изображением)"
    except Exception as e:
        return f"(ошибка: изображение повреждено: {e})"

    results = _get_reader().readtext(np.array(img), detail=0)
    lines = [str(line).strip() for line in results if str(line).strip()]
    return "\n".join(lines).strip() if lines else "(пустой документ / нет текста)"


def pdf_to_text(raw: bytes) -> str:
    """
    Извлечение текста из PDF → текст.
    1) Пытаемся вытащить текст через PyPDF2.
    2) Если текста нет (скан), делаем OCR каждой страницы через easyocr.
    """
    if not raw:
        return "(ошибка: пустой PDF-файл)"

    from PyPDF2 import PdfReader
    from PyPDF2.errors import EmptyFileError
    from pdf2image import convert_from_bytes  # OCR fallback для PDF

    buf = io.BytesIO(raw)
    try:
        reader = PdfReader(buf)
    except EmptyFileError:
        return "(ошибка: PDF пустой)"
    except Exception as e:
        return f"(ошибка: PDF повреждён: {e})"

    texts: List[str] = []
    # Пытаемся сначала обычное текстовое извлечение
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
        except Exception as e:
            texts.append(f"[ошибка чтения страницы {i + 1}: {e}]")
            continue

        if t.strip():
            texts.append(t.strip())

    pure_text = "\n\n".join(texts).strip() if texts else ""

    # Если что-то удалось вытащить — возвращаем
    if pure_text:
        return pure_text

    # Fallback: PDF, похожий на скан → OCR
    try:
        images = convert_from_bytes(raw)
    except Exception as e:
        return f"(ошибка OCR PDF (конвертация в изображения): {e})"

    ocr_pages: List[str] = []
    for img in images:
        try:
            results = _get_reader().readtext(np.array(img), detail=0)
            lines = [str(line).strip() for line in results if str(line).strip()]
            page_text = "\n".join(lines).strip()
            if page_text:
                ocr_pages.append(page_text)
        except Exception as e:
            ocr_pages.append(f"[ошибка OCR страницы: {e}]")

    ocr_text = "\n\n".join(ocr_pages).strip()
    return ocr_text if ocr_text else "(пустой документ / нет текста)"


def docx_to_text(raw: bytes) -> str:
    """Извлечение текста из DOCX → текст.

    Берём ВСЕ абзацы (w:p), включая находящиеся в таблицах, в порядке документа.
    doc.paragraphs (python-docx) пропускает текст внутри таблиц, где лежат ФИО,
    паспортные данные и суммы — поэтому читаем XML напрямую (как делал n8n).
    """
    if not raw:
        return "(ошибка: пустой DOCX-файл)"

    import re
    import zipfile
    import xml.etree.ElementTree as ET
    W = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            root = ET.fromstring(z.read("word/document.xml"))
    except Exception as e:
        return f"(ошибка: DOCX повреждён или не читается: {e})"

    lines: List[str] = []
    for p in root.findall(".//w:p", W):
        parts: List[str] = []
        for el in p.iter():
            tag = el.tag.split("}")[-1]
            if tag == "t":
                parts.append(el.text or "")
            elif tag == "tab":
                parts.append("\t")
            elif tag == "br":
                parts.append("\n")
        lines.append(re.sub(r"[ \t]+\n", "\n", "".join(parts)).strip())

    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text if text else "(пустой документ / нет текста)"


def process_file(path: Path, out_dir: Path) -> None:
    """Обработка одного файла: извлечение текста или пропуск."""
    if not path.is_file():
        print(f"[SKIP] {path} не файл")
        return

    suffix = path.suffix.lower()
    raw = path.read_bytes()
    out_name = path.stem + ".txt"
    out_path = out_dir / out_name

    if suffix in [".jpg", ".jpeg", ".png"]:
        print(f"[INFO] OCR image -> TXT: {path}")
        text = image_to_text(raw)
        out_path.write_text(text, encoding="utf-8")
        print(f"[OK] {path} -> {out_path}")

    elif suffix == ".pdf":
        print(f"[INFO] PDF -> TXT: {path}")
        text = pdf_to_text(raw)
        out_path.write_text(text, encoding="utf-8")
        print(f"[OK] {path} -> {out_path}")

    elif suffix == ".docx":
        print(f"[INFO] DOCX -> TXT: {path}")
        text = docx_to_text(raw)
        out_path.write_text(text, encoding="utf-8")
        print(f"[OK] {path} -> {out_path}")

    elif suffix == ".txt":
        # Можно просто скопировать, чтобы всё было в одном месте
        print(f"[INFO] COPY TXT: {path}")
        out_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[OK] {path} -> {out_path}")

    else:
        print(f"[SKIP] {path} (неподдерживаемый формат)")


def convert_uploaded_files(files: Mapping[str, "FileStorage"], out_dir: Path) -> List[str]:
    """
    Обработка файлов из Flask `request.files`.
    JPG/PNG/PDF/DOCX → TXT, TXT копируем как есть.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    saved: List[str] = []

    for field_name, file in files.items():
        filename = getattr(file, "filename", "") or ""
        if not filename:
            continue

        suffix = Path(filename).suffix.lower()

        # Читаем байты; если вдруг поток уже читали раньше — пробуем отмотать и перечитать.
        raw = file.read()
        if not raw:
            try:
                file.stream.seek(0)
                raw = file.read()
            except Exception:
                raw = b""

        # базовое имя для txt
        txt_name = f"{Path(filename).stem}.txt"
        txt_path = out_dir / txt_name

        if suffix in [".jpg", ".jpeg", ".png"]:
            text = image_to_text(raw)
            txt_path.write_text(text, encoding="utf-8")
            saved.append(txt_name)

        elif suffix == ".pdf":
            text = pdf_to_text(raw)
            txt_path.write_text(text, encoding="utf-8")
            saved.append(txt_name)

        elif suffix == ".docx":
            text = docx_to_text(raw)
            txt_path.write_text(text, encoding="utf-8")
            saved.append(txt_name)

        elif suffix == ".txt":
            out_path = out_dir / filename
            out_path.write_bytes(raw)
            saved.append(filename)

        else:
            # неизвестные форматы игнорируем
            continue

    return saved


def main():
    parser = argparse.ArgumentParser(description="Конвертация JPG/PNG/PDF/DOCX в TXT")
    parser.add_argument("inputs", nargs="+", help="Файлы для обработки")
    parser.add_argument(
        "-o", "--out-dir",
        default="out_txt",
        help="Папка для сохранения TXT (по умолчанию: out_txt)",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for inp in args.inputs:
        process_file(Path(inp), out_dir)


if __name__ == "__main__":
    main()
