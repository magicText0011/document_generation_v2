#!/usr/bin/env python3
"""
documents.py

Берёт значения плейсхолдеров из out_txt.json,
подставляет их в шаблоны opredelenie.docx и reshenie.docx
из папки documents/, сохраняет готовые документы в out_docs/
и собирает их в documents.zip.

Зависимость:
    pip install python-docx
"""

import json
import re
import zipfile
from pathlib import Path
from docx import Document
from docx.shared import Pt, Mm
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# --- НАСТРОЙКИ ---

BASE_DIR = Path(__file__).parent.resolve()

TEMPLATES_DIR = BASE_DIR / "documents"
OUTPUT_DIR = BASE_DIR / "out_docs"
JSON_PATH = BASE_DIR / "out_txt" / "out_txt.json"

TEMPLATE_FILES = [
    "opredelenie.docx",
    "reshenie.docx",
]

ZIP_NAME = "documents.zip"

FONT_NAME = "Times New Roman"
FONT_SIZE_PT = 14


# --- УТИЛИТЫ ---

def strip_braces(key: str) -> str:
    """Убираем {{ }} и пробелы вокруг."""
    return re.sub(r"^\s*\{\{\s*|\s*\}\}\s*$", "", str(key)).strip()


def build_mapping(raw: dict) -> dict:
    """
    Строим маппинг плейсхолдеров. Шаблоны используют 3 формы:
        {{KEY}}  — двойные скобки (основной формат)
        {KEY}    — одинарные скобки (часть JUDGE_*_GENT, *_NAME_DAT и т.п.)
        KEY      — без скобок (JUDGE_POSITION_WITH_DASH в подписи)
    """
    mapping = {}
    for k, v in raw.items():
        if v is None:
            v = ""
        k_str = str(k)
        v_str = str(v)
        bare = strip_braces(k_str)
        mapping[f"{{{{{bare}}}}}"] = v_str   # {{KEY}}
        mapping[f"{{{bare}}}"] = v_str       # {KEY}
        mapping[bare] = v_str                # KEY

    # Если JUDGE_POSITION-производные пусты (выбрана базовая позиция "третейский судья"),
    # везде подставляем один пробел — и в шапке, и в подписи.
    for base in ("JUDGE_POSITION", "JUDGE_POSITION_GENT", "JUDGE_POSITION_WITH_DASH"):
        for form in (f"{{{{{base}}}}}", f"{{{base}}}", base):
            if not mapping.get(form):
                mapping[form] = " "
    return mapping


def apply_formatting_to_paragraph(paragraph):
    """Применяем форматирование к абзацу."""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    # одинарный интервал
    p_format = paragraph.paragraph_format
    p_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    # по желанию можно обнулить интервалы до/после
    # p_format.space_before = Pt(0)
    # p_format.space_after = Pt(0)

    for run in paragraph.runs:
        font = run.font
        font.name = FONT_NAME
        font.size = Pt(FONT_SIZE_PT)

def set_table_no_row_split(table):
    """
    Запрещаем разрывать строки таблицы между страницами.
    """
    for row in table.rows:
        tr = row._tr
        tr_pr = tr.get_or_add_trPr()
        cant_split = OxmlElement('w:cantSplit')
        tr_pr.append(cant_split)



def apply_formatting_recursive(obj):
    """Рекурсивно применяем форматирование к параграфам и таблицам."""
    # форматируем параграфы
    for paragraph in getattr(obj, "paragraphs", []):
        apply_formatting_to_paragraph(paragraph)

    # форматируем таблицы и запрещаем разрыв строк
    for table in getattr(obj, "tables", []):
        set_table_no_row_split(table)
        for row in table.rows:
            for cell in row.cells:
                apply_formatting_recursive(cell)


def replace_in_obj(obj, mapping: dict):
    """Рекурсивная замена плейсхолдеров в параграфах и таблицах."""
    for paragraph in getattr(obj, "paragraphs", []):
        if paragraph.text:
            text = paragraph.text
            # Длинные ключи — первыми, иначе короткий «голый» ключ (напр. INTEREST)
            # портит подстроку внутри длинного плейсхолдера ({{INTEREST_FROM}}).
            for key in sorted(mapping, key=len, reverse=True):
                if key in text:
                    text = text.replace(key, mapping[key])
            # Когда JUDGE_POSITION* пуст и заполняется одним пробелом, соседние
            # пробелы шаблона дают подряд 2-3 пробела — схлопываем в один.
            text = re.sub(r" {2,}", " ", text)
            paragraph.text = text
        apply_formatting_to_paragraph(paragraph)

    for table in getattr(obj, "tables", []):
        for row in table.rows:
            for cell in row.cells:
                replace_in_obj(cell, mapping)


def add_page_number_to_paragraph(paragraph):
    """
    Вставляет поле PAGE в абзац и центрирует его.
    """
    # убираем старый текст, если был
    paragraph.clear()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    run = paragraph.add_run()

    # <w:fldChar w:fldCharType="begin"/>
    fld_char_begin = OxmlElement('w:fldChar')
    fld_char_begin.set(qn('w:fldCharType'), 'begin')

    # <w:instrText xml:space="preserve"> PAGE </w:instrText>
    instr_text = OxmlElement('w:instrText')
    instr_text.set(qn('xml:space'), 'preserve')
    instr_text.text = ' PAGE '

    # <w:fldChar w:fldCharType="separate"/>
    fld_char_separate = OxmlElement('w:fldChar')
    fld_char_separate.set(qn('w:fldCharType'), 'separate')

    # <w:fldChar w:fldCharType="end"/>
    fld_char_end = OxmlElement('w:fldChar')
    fld_char_end.set(qn('w:fldCharType'), 'end')

    r = run._r
    r.append(fld_char_begin)
    r.append(instr_text)
    r.append(fld_char_separate)
    r.append(fld_char_end)

    # шрифт для номера страницы
    font = run.font
    font.name = FONT_NAME
    font.size = Pt(FONT_SIZE_PT)

def add_page_numbers_to_doc(doc: Document):
    """
    Вставляет нумерацию страниц (PAGE) в футер для всех секций документа
    и поднимает номер повыше от нижнего края.
    """
    for section in doc.sections:
        # поднимаем футер повыше (можешь поиграться значением 15–20)
        section.footer_distance = Mm(15)

        footer = section.footer
        # Берём существующий абзац футера или создаём новый
        if footer.paragraphs:
            p = footer.paragraphs[0]
        else:
            p = footer.add_paragraph()
        add_page_number_to_paragraph(p)


def replace_placeholders_in_docx(template_path: Path, mapping: dict, output_path: Path):
    """Открываем docx, заменяем плейсхолдеры и сохраняем."""
    doc = Document(str(template_path))
    replace_in_obj(doc, mapping)

    for section in doc.sections:
        if section.header:
            replace_in_obj(section.header, mapping)
        if section.footer:
            replace_in_obj(section.footer, mapping)

    # форматирование основного содержимого
    apply_formatting_recursive(doc)

    # номера страниц только для reshenie.docx
    if "reshenie" in template_path.name.lower():
        add_page_numbers_to_doc(doc)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))


def generate_documents(
    json_path: Path = JSON_PATH,
    templates_dir: Path = TEMPLATES_DIR,
    output_dir: Path = OUTPUT_DIR,
    template_files=None,
    zip_name: str = ZIP_NAME,
) -> Path:
    """
    Основная функция:
    - читает JSON с плейсхолдерами
    - обрабатывает шаблоны
    - возвращает путь к ZIP с готовыми документами
    """
    if template_files is None:
        template_files = TEMPLATE_FILES

    if not json_path.exists():
        raise FileNotFoundError(f"JSON с данными не найден: {json_path}")
    if not templates_dir.exists():
        raise FileNotFoundError(f"Папка с шаблонами не найдена: {templates_dir}")

    with json_path.open("r", encoding="utf-8") as f:
        raw_data = json.load(f)

    mapping = build_mapping(raw_data)

    output_dir.mkdir(parents=True, exist_ok=True)
    generated_files = []

    for name in template_files:
        tpl_path = templates_dir / name
        if not tpl_path.exists():
            raise FileNotFoundError(f"Шаблон не найден: {tpl_path}")
        out_path = output_dir / name
        replace_placeholders_in_docx(tpl_path, mapping, out_path)
        generated_files.append(out_path)

    zip_path = output_dir / zip_name
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in generated_files:
            zf.write(file_path, arcname=file_path.name)

    return zip_path


# --- CLI-запуск ---

if __name__ == "__main__":
    zip_path = generate_documents()
    print(f"Готово. Архив с документами: {zip_path}")



# #
# #!/usr/bin/env python3
# """
# documents.py
#
# Берёт значения плейсхолдеров из out_txt.json,
# подставляет их в шаблоны opredelenie.docx и reshenie.docx
# из папки documents/, сохраняет готовые документы в out_docs/
# и собирает их в documents.zip.
#
# Зависимость:
#     pip install python-docx
# """
#
# import json
# import re
# import zipfile
# from pathlib import Path
# from docx import Document
# from docx.shared import Pt
# from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
# # --- НАСТРОЙКИ ---
#
#
#
# BASE_DIR = Path(__file__).parent.resolve()
#
# TEMPLATES_DIR = BASE_DIR / "documents"
# OUTPUT_DIR = BASE_DIR / "out_docs"
# JSON_PATH = BASE_DIR / "out_txt" / "out_txt.json"
#
# TEMPLATE_FILES = [
#     "opredelenie.docx",
#     "reshenie.docx",
# ]
#
# ZIP_NAME = "documents.zip"
#
# FONT_NAME = "Times New Roman"
# FONT_SIZE_PT = 14
#
#
# # --- УТИЛИТЫ ---
#
# def strip_braces(key: str) -> str:
#     """Убираем {{ }} и пробелы вокруг."""
#     return re.sub(r"^\s*\{\{\s*|\s*\}\}\s*$", "", str(key)).strip()
#
#
# def build_mapping(raw: dict) -> dict:
#     """
#     Строим маппинг плейсхолдеров:
#     из {"{{CITY}}": "Минск"} сделаем:
#     {
#         "{{CITY}}": "Минск",
#         "CITY": "Минск"
#     }
#     """
#     mapping = {}
#     for k, v in raw.items():
#         if v is None:
#             v = ""
#         k_str = str(k)
#         v_str = str(v)
#         bare = strip_braces(k_str)
#         mapping[f"{{{{{bare}}}}}"] = v_str  # с фигурными скобками
#         mapping[bare] = v_str               # без скобок
#     return mapping
#
#
# # def apply_formatting_to_paragraph(paragraph):
# #     """Применяем форматирование к абзацу."""
# #     paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
# #     for run in paragraph.runs:
# #         font = run.font
# #         font.name = FONT_NAME
# #         font.size = Pt(FONT_SIZE_PT)
# def apply_formatting_to_paragraph(paragraph):
#     """Применяем форматирование к абзацу."""
#     paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
#
#     # межстрочный интервал 1.5
#     p_format = paragraph.paragraph_format
#     # одинарный интервал
#     p_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
#     # (по желанию можно обнулить интервалы до/после)
#     # p_format.space_before = Pt(0)
#     # p_format.space_after = Pt(0)
#
#     for run in paragraph.runs:
#         font = run.font
#         font.name = FONT_NAME
#         font.size = Pt(FONT_SIZE_PT)
#
#
#
# def apply_formatting_recursive(obj):
#     """Рекурсивно применяем форматирование к параграфам и таблицам."""
#     for paragraph in getattr(obj, "paragraphs", []):
#         apply_formatting_to_paragraph(paragraph)
#     for table in getattr(obj, "tables", []):
#         for row in table.rows:
#             for cell in row.cells:
#                 apply_formatting_recursive(cell)
#
#
# def replace_in_obj(obj, mapping: dict):
#     """Рекурсивная замена плейсхолдеров в параграфах и таблицах."""
#     for paragraph in getattr(obj, "paragraphs", []):
#         if paragraph.text:
#             text = paragraph.text
#             for key, value in mapping.items():
#                 if key in text:
#                     text = text.replace(key, value)
#             paragraph.text = text
#         apply_formatting_to_paragraph(paragraph)
#
#     for table in getattr(obj, "tables", []):
#         for row in table.rows:
#             for cell in row.cells:
#                 replace_in_obj(cell, mapping)
#
#
# def replace_placeholders_in_docx(template_path: Path, mapping: dict, output_path: Path):
#     """Открываем docx, заменяем плейсхолдеры и сохраняем."""
#     doc = Document(str(template_path))
#     replace_in_obj(doc, mapping)
#
#     for section in doc.sections:
#         if section.header:
#             replace_in_obj(section.header, mapping)
#         if section.footer:
#             replace_in_obj(section.footer, mapping)
#
#     apply_formatting_recursive(doc)
#
#     output_path.parent.mkdir(parents=True, exist_ok=True)
#     doc.save(str(output_path))
#
#
# def generate_documents(
#     json_path: Path = JSON_PATH,
#     templates_dir: Path = TEMPLATES_DIR,
#     output_dir: Path = OUTPUT_DIR,
#     template_files=None,
#     zip_name: str = ZIP_NAME,
# ) -> Path:
#     """
#     Основная функция:
#     - читает JSON с плейсхолдерами
#     - обрабатывает шаблоны
#     - возвращает путь к ZIP с готовыми документами
#     """
#     if template_files is None:
#         template_files = TEMPLATE_FILES
#
#     if not json_path.exists():
#         raise FileNotFoundError(f"JSON с данными не найден: {json_path}")
#     if not templates_dir.exists():
#         raise FileNotFoundError(f"Папка с шаблонами не найдена: {templates_dir}")
#
#     with json_path.open("r", encoding="utf-8") as f:
#         raw_data = json.load(f)
#
#     mapping = build_mapping(raw_data)
#
#     output_dir.mkdir(parents=True, exist_ok=True)
#     generated_files = []
#
#     for name in template_files:
#         tpl_path = templates_dir / name
#         if not tpl_path.exists():
#             raise FileNotFoundError(f"Шаблон не найден: {tpl_path}")
#         out_path = output_dir / name
#         replace_placeholders_in_docx(tpl_path, mapping, out_path)
#         generated_files.append(out_path)
#
#     zip_path = output_dir / zip_name
#     with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
#         for file_path in generated_files:
#             zf.write(file_path, arcname=file_path.name)
#
#     return zip_path
#
#
# # --- CLI-запуск ---
#
# if __name__ == "__main__":
#     zip_path = generate_documents()
#     print(f"Готово. Архив с документами: {zip_path}")
