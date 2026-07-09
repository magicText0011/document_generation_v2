#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py — извлечение плейсхолдеров БЕЗ n8n и БЕЗ LLM.

Все значения извлекаются детерминированно (regex/правила), потому что входные
документы — машинно-сгенерированные шаблоны сервиса «Капуста» (договор займа,
претензия, исковое заявление, свидетельство СОЗ) и vvod_dannyh.txt (генерируется
data_entry.py). Подписи полей и форматы дат/чисел стабильны.

  out_txt/*.txt  ->  склейка  ->  нормализация текста
                 ->  extract_vvod_dannyh   (ручной ввод: город, судья, суд, даты)
                 ->  extract_documents     (стороны, займ, суммы, ставки, график)
                 ->  extract_from_certificate (адреса, дата/сумма займа из СОЗ)
                 ->  extract_strict_markers (дата претензии, период пеней)
                 ->  нормализация ФИО/адресов/паспорта
                 ->  правка регистра адресных меток
                 ->  вычисление формул
                 ->  out_txt/out_txt.json   (словарь {"{{KEY}}": "value", ...})

Дальше morph_fio.py и documents.py работают как раньше.

Зависимости: только стандартная библиотека.
"""
from __future__ import annotations

import math
import os
import re
import json
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

# --- настройки ---

BASE_DIR = Path(__file__).parent.resolve()
OUT_DIR = BASE_DIR / "out_txt"
OUT_JSON = OUT_DIR / "out_txt.json"
RUNS_LOG = BASE_DIR / "runs.jsonl"
RUNS_LOG_MAX = 25  # хранить последние N запусков (ротация при записи)


# ============================================================
# 1. Чтение и склейка текстов
# ============================================================

def _decode_text(raw: bytes) -> str:
    """Декодирует байты txt-файла устойчиво к ОС/редактору.

    Windows-Блокнот пишет cp1251 (ANSI), UTF-8 с BOM или UTF-16 — старая
    логика "только utf-8 + errors=ignore" разрушала кириллицу. Здесь:
    BOM-детект -> строгий utf-8 -> cp1251 -> latin-1 (последний резерв, не падает).
    """
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8-sig"),
                     (b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"),
                     (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if raw.startswith(bom):
            text = raw.decode(enc, errors="ignore")
            break
    else:
        for enc in ("utf-8", "cp1251", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    return text.lstrip("﻿")


def read_source_texts(out_dir: Path = OUT_DIR) -> list[tuple[str, str]]:
    """Читает все *.txt из out_dir (кроме служебного out_txt.json). -> [(имя, текст)]."""
    items: list[tuple[str, str]] = []
    for p in sorted(out_dir.glob("*.txt")):
        body = _decode_text(p.read_bytes())
        items.append((p.name, body))
    return items


def combine_texts(items: list[tuple[str, str]]) -> str:
    parts = [f"==== {name} ====\n{body}".strip() for name, body in items]
    return "\n\n".join(parts).strip()


# ============================================================
# 2. Нормализация склеенного текста
# ============================================================

def normalize_combined(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)

    lines = text.split("\n")
    normalized_lines: list[str] = []
    buffer = ""
    for line in lines:
        clean_line = line.strip()
        if not clean_line:
            continue
        if re.match(r"^\d+\.", clean_line) or re.match(r"^[А-ЯЁ]{2,}", clean_line):
            if buffer:
                normalized_lines.append(buffer.strip())
                buffer = ""
            normalized_lines.append(clean_line)
        else:
            buffer += " " + clean_line
    if buffer:
        normalized_lines.append(buffer.strip())

    return "\n".join(normalized_lines)


_DATE = r"\d{2}\.\d{2}\.\d{4}"


def _flatten(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


# ============================================================
# 3. Нормализаторы ФИО/адресов/паспорта
# ============================================================

ABBRS = {"BYN", "ООО", "ОАО", "ЗАО", "ИП", "УНП", "UNP", "ID", "РУВД", "РОВД", "ОВД", "МР"}

NAME_KEYS = {"PLAINTIFF_FULL", "DEFENDANT_FULL"}
ADDRESS_KEYS = {"PLAINTIFF_ADDRESS", "DEFENDANT_ADDRESS"}


def smart_cap_word(w: str, keep_upper: bool = False) -> str:
    if not w:
        return w
    if keep_upper or w in ABBRS:
        return w
    if re.match(r"^\d", w):
        return w
    if re.match(r"^[A-Za-zА-Яа-яЁё]\.$", w) or re.match(r"^[A-Za-zА-Яа-яЁё]\.[A-Za-zА-Яа-яЁё]\.$", w):
        return w.upper()
    if "-" in w:
        return "-".join(smart_cap_word(part) for part in w.split("-"))
    return w[:1].upper() + w[1:].lower()


def normalize_name(s: str) -> str:
    toks = re.split(r"\s+", str(s))
    return re.sub(r"\s+", " ", " ".join(smart_cap_word(t) for t in toks)).strip()


def normalize_address(s: str) -> str:
    t = str(s).strip()
    # "д.1"/"кв.1" без пробела -> "д. 1"/"кв. 1", иначе маркер не распознаётся и слипшийся токен капитализируется
    t = re.sub(r"(?i)\b(д|кв|корп|пом|стр|оф)\.\s*(?=\d)", lambda m: m.group(1).lower() + ". ", t)
    # одиночная "Д" перед названием населённого пункта — сокращение от "Деревня"
    # (после PDF-склейки бывает "Кормянский Район, Д Семёновка, ..." без точки).
    t = re.sub(r"\bД\s+(?=[А-ЯЁ][А-Яа-яЁё]{2,})", "д. ", t)
    repls = [
        (r"\bРЕСПУБЛИКА\s+БЕЛАРУСЬ\b", "Республика Беларусь"),
        (r"\b(ГОРОД)\b", "город"),
        (r"\b(ОБЛАСТЬ)\b", "область"),
        (r"\b(РАЙОН|Р-Н)\b", "район"),
        (r"\b(УЛИЦА)\b", "улица"),
        (r"\b(ПРОСПЕКТ|ПР-Т)\b", "проспект"),
        (r"\b(ПЕРЕУЛОК|ПЕР\.)\b", "переулок"),
        (r"\b(Г\.)\b", "г."),
        (r"\b(ОБЛ\.)\b", "обл."),
        (r"\b(УЛ\.)\b", "ул."),
        (r"\b(ДОМ|Д\.)\b", "д."),
        (r"\b(КВАРТИРА|КВ\.)\b", "кв."),
        (r"\b(КОРПУС|КОРП\.)\b", "корп."),
        (r"\b(ПОМЕЩЕНИЕ|ПОМ\.)\b", "пом."),
    ]
    for pat, rep in repls:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)

    marker_re = re.compile(
        r"^(город|область|район|р-н|улица|проспект|переулок|пер\.|г\.|обл\.|ул\.|д\.|кв\.|корп\.|пом\.)([,:;.]*)$",
        re.IGNORECASE,
    )
    tokens: list[str] = []
    for tok in re.split(r"\s+", t):
        m = marker_re.match(tok)
        if m:
            tokens.append(m.group(1).lower() + m.group(2))
        elif tok in ABBRS or (re.match(r"^[A-ZА-ЯЁ]{2,4}$", tok) and not re.search(r"\d", tok)):
            tokens.append(tok.upper())
        elif re.match(r"^\d", tok):
            tokens.append(tok)
        else:
            tokens.append(smart_cap_word(tok))

    lead_markers = re.compile(
        r"^(город|г\.|область|обл\.|район|р-н|улица|ул\.|проспект|переулок|пер\.)$", re.IGNORECASE
    )
    for i in range(len(tokens) - 1):
        if lead_markers.match(tokens[i]) and re.match(r"^[A-Za-zА-Яа-яЁё-]+$", tokens[i + 1]):
            tokens[i + 1] = smart_cap_word(tokens[i + 1])

    return re.sub(r"\s+", " ", " ".join(tokens)).strip()


def _apply_normalizers(fields: dict) -> dict:
    """Применяет нормализаторы ФИО/адресов по имени ключа.
    Ключи приходят в форме '{{KEY}}'."""
    out: dict[str, str] = {}
    for key, val in fields.items():
        key_upper = key.strip().lstrip("{").rstrip("}").strip().upper()
        val = str(val).strip()
        if not val:
            continue
        if key_upper in NAME_KEYS:
            val = normalize_name(val)
        elif key_upper in ADDRESS_KEYS:
            val = normalize_address(val)
        out[f"{{{{{key_upper}}}}}"] = val
    return out


# ============================================================
# 4. Разбиение склейки на разделы документов
# ============================================================

# Заголовок раздела от конвертера: "==== имя.txt ====" / "===== имя.txt =====".
_SECTION_RE = re.compile(r"={3,}\s*([^=\n]+?)\s*={3,}")


def split_sections(raw: str) -> list[tuple[str, str]]:
    """Делит склеенный текст на разделы по заголовкам '==== имя ===='. -> [(имя, тело)]."""
    matches = list(_SECTION_RE.finditer(raw))
    sections: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        sections.append((name, raw[start:end]))
    return sections


def _find_section(sections: list[tuple[str, str]], *needles: str) -> str:
    """Возвращает тело первого раздела, в имени или содержимом которого есть один из needle (lowercase)."""
    for name, body in sections:
        hay = (name + " " + body).lower()
        if any(n in hay for n in needles):
            return body
    return ""


# ============================================================
# 5. Извлечение полей ручного ввода (vvod_dannyh.txt)
#    Файл генерируется data_entry.py с фиксированными метками,
#    поэтому парсим строго "Метка: значение".
# ============================================================

# (метка в файле, ключ плейсхолдера) — порядок как в data_entry.save_txt.
_VVOD_FIELDS = [
    ("Город", "CITY"),
    ("Номер дела", "CASE_NO"),
    ("Дата вынесения определения", "ORDER_DATE"),
    ("ФИО судьи", "JUDGE_FULL"),
    ("Должность судьи", "JUDGE_POSITION"),
    ("Адрес третейского суда", "VENUE_ADDRESS"),
    ("Номер свидетельства СОЗ", "CERTIFICATE_NUMBER"),
    ("Дата свидетельства СОЗ", "CERTIFICATE_DATE"),
    ("Дата направления скриншотов", "SCREENSHOTS_DATE"),
    ("Дата заседания", "HEARING_DATE"),
    ("Время заседания", "HEARING_TIME"),
    ("Крайний срок подачи документов", "DOCS_DUE_DATE"),
    ("Электронная почта суда", "COURT_EMAIL"),
    ("Дата вынесения решения", "DECISION_DATE"),
    ("Сумма арбитражного сбора", "ARBITRATION_FEE"),
]

# Лукахед, обрывающий значение перед следующей известной меткой (любой из списка).
_VVOD_NEXT = r"(?:" + "|".join(re.escape(lbl) for lbl, _ in _VVOD_FIELDS) + r")\s*:"


def extract_vvod_dannyh(raw_text: str) -> dict:
    """Парсит vvod_dannyh.txt: для каждой метки берёт текст до следующей метки/конца."""
    body = _find_section(split_sections(raw_text), "vvod_dannyh")
    src = body if body else raw_text  # если раздел не выделился — ищем во всём тексте

    out: dict[str, str] = {}
    for label, key in _VVOD_FIELDS:
        m = re.search(
            re.escape(label) + r"\s*:\s*(.*?)\s*(?=" + _VVOD_NEXT + r"|$)",
            src, re.IGNORECASE | re.DOTALL,
        )
        if not m:
            continue
        val = _flatten(m.group(1))
        if val:  # пустое значение (например, пустая должность судьи) — пропускаем
            out[f"{{{{{key}}}}}"] = val
    return out


# ============================================================
# 6. Извлечение полей из документов (договор/претензия/исковое/СОЗ)
#    Якоря — по фиксированным фразам шаблонов, по содержимому (не по
#    имени файла). Числа/даты копируются дословно.
# ============================================================

def _search(pattern: str, text: str, group=1, flags=re.IGNORECASE | re.DOTALL):
    m = re.search(pattern, text, flags)
    if not m:
        return None
    return _flatten(m.group(group))


def extract_documents(raw_text: str) -> dict:
    out: dict[str, str] = {}

    # --- Стороны: "Между <ФИО> (...Заимодавец) и <ФИО> (...Заёмщик)".
    #     Сами ФИО в документы не идут, но из них morph_fio строит склонения. ---
    # Захват ФИО ограничен (без скобок/ёлочек/цифр/переносов и не длиннее 80 симв.),
    # чтобы ленивый матч не «расползался» на весь договор: в преамбуле договора есть
    # стороннее «между Оператором и Клиентом … (в рамках …)», и обычный `.+?` проедал
    # текст до первой настоящей «(Заимодавец)» далеко внизу, утаскивая весь корпус в ФИО.
    m = re.search(
        r"Между\s+([^()«»\d]{3,80}?)\s*\(\s*(?:Истец[,\s]*)?Заимодавец\s*\)\s*и\s+([^()«»\d]{3,80}?)\s*\(\s*(?:Ответчик[,\s]*)?За[ёе]мщик",
        raw_text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        out["{{PLAINTIFF_FULL}}"] = _flatten(m.group(1))
        out["{{DEFENDANT_FULL}}"] = _flatten(m.group(2))

    # --- Договор займа: номер и дата из заголовка ---
    m = re.search(r"Договор\s+займа\s*№\s*([0-9/]+)\s+от\s+(" + _DATE + r")", raw_text, re.IGNORECASE)
    if m:
        out["{{LOAN_NO}}"] = m.group(1)
        out["{{LOAN_DATE}}"] = m.group(2)

    # --- Условия займа (фиксированные подписи в "Сведениях о займе") ---
    v = _search(r"Дата\s+погашения\s+займа\s*[:\s]+(" + _DATE + r")", raw_text)
    if v:
        out["{{LOANDATE_END}}"] = v
    v = _search(r"Срок\s+займа\s*\(\s*дней\s*\)\s*[:\s]*(\d+)", raw_text)
    if v:
        out["{{LOAN_TERM_DAYS}}"] = v
    v = _search(r"Ставка\s+за\s+пользование\s+займ\w*[^0-9]*?(\d+)", raw_text)
    if v:
        out["{{RATE}}"] = v

    # --- График платежей: первая строка таблицы (дата, сумма, осн.долг, проценты) ---
    m = re.search(
        r"Граф\w*\s+платеж\w*\s*:?\s*Номер\s+платежа\s+Дата\s+платежа\s+Сумма\s+платежа.*?проценты\s+"
        r"(\d+)\s*(" + _DATE + r")\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)",
        raw_text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        _, pay_date, pay_sum, principal, interest = (g.strip() for g in m.groups())
        out["{{PAYMENT_DATE}}"] = pay_date
        out["{{PAYMENT_SUM}}"] = pay_sum
        out["{{PRINCIPAL}}"] = principal
        out["{{INTEREST}}"] = interest

    # --- Суммы из ИСКОВОГО ЗАЯВЛЕНИЯ (приоритет над претензией: слово "искового заявления"
    #     отсекает аналогичные фразы претензии "настоящей Претензии") ---
    v = _search(r"искового\s+заявления\s+размер\s+основного\s+долга.*?составляет\s*([\d.,]+)", raw_text)
    if v:
        out["{{LOAN_PRINCIPAL}}"] = v
    v = _search(r"искового\s+заявления\s+размер\s+подлежащих\s+уплате\s+процентов.*?составляет\s*([\d.,]+)", raw_text)
    if v:
        out["{{INTEREST_SUM}}"] = v
    v = _search(r"искового\s+заявления\s+размер\s+подлежащей\s+уплате\s+неустойки\s*\(пени\)\s*составляет\s*([\d.,]+)", raw_text)
    if v:
        out["{{PENALTY_SUM}}"] = v

    return out


# ============================================================
# 7. Детерминированное извлечение из Свидетельства СОЗ.
#    Документ строго структурирован (метка -> значение).
# ============================================================

def extract_from_certificate(raw_text: str) -> dict:
    """Ищет поля по СОДЕРЖИМОМУ (не по имени файла), на СЫРОМ тексте с сохранёнными
    переносами строк. Работает и когда документы склеены в один файл (out_txt.txt)."""
    out: dict[str, str] = {}

    # LOANDATE_START — "DD.MM.YYYY заключили сделку займа ..." / "DD.MM.YYYY заключили договор займа"
    m = re.search(r"(\d{2}\.\d{2}\.\d{4})\s+заключили\s+(?:сделку|договор\s+займа)", raw_text)
    if m:
        out["{{LOANDATE_START}}"] = m.group(1)

    # LOAN_AMOUNT — "Сумма займа\n<число>" (старый формат) / "Сумма займа<число>" (новый формат)
    m = re.search(r"Сумма\s+займа\s*\n?\s*(\d+[.,]\d+)", raw_text, re.IGNORECASE)
    if m:
        out["{{LOAN_AMOUNT}}"] = m.group(1).strip()

    # Адреса — блок "Зарегистрирован <addr> Проживает <addr>".
    # Терпим к вариантам формата конвертера:
    #   - метки на отдельной строке (PDF/DOCX в чистом виде)
    #   - метки с двоеточием в одной строке с адресом
    #   - женский род ("Зарегистрирована")
    #   - адрес разорван на несколько строк (PDF-перенос внутри строки)
    # Захват жадно собирает строки адреса до маркера конца блока
    # ("являющийся"/"являющаяся"/"в качестве"). Внутренние переносы
    # склеиваются в один пробел при нормализации.
    # \b после "Зарегистрирован[а]?" отсекает слова вроде "зарегистрированное"
    # (определение в глоссарии договора, не относится к адресу стороны).
    addr_re = re.compile(
        r"Зарегистрирован[а]?\b[\s:.]+"
        r"(?P<reg>.+?)"
        r"\s+Проживает\b[\s:.]+"
        r"(?P<liv>.+?)"
        r"(?=\s*(?:являющ|в\s+качестве))",
        re.IGNORECASE | re.DOTALL,
    )

    for m in addr_re.finditer(raw_text):
        reg = normalize_address(_flatten(m.group("reg")))
        live = normalize_address(_flatten(m.group("liv")))
        window = raw_text[m.end():m.end() + 400].upper()
        # роль = ближайшее ключевое слово, иначе блок следующей стороны может ошибочно
        # подобрать "ЗАЕМЩИК" из своего текста дальше по документу.
        pos_def = window.find("ЗАЕМЩИК")
        pos_pla = window.find("ЗАЙМОДАВ")
        if pos_def == -1 and pos_pla == -1:
            continue
        if pos_pla == -1 or (pos_def != -1 and pos_def < pos_pla):
            key = "DEFENDANT_ADDRESS"
        else:
            key = "PLAINTIFF_ADDRESS"
        out[f"{{{{{key}}}}}"] = f"место регистрации: {reg}, место жительства: {live}"

    return out


# ============================================================
# 8. Детерминированное извлечение по строгим маркерам.
#    Метки и формат даты (DD.MM.YYYY) постоянны; от формата исходного
#    документа меняется лишь раскладка txt (переносы, пробелы), поэтому
#    регексы терпимы к пробелам/переносам, а пени ищутся по контексту,
#    а не по точному расположению строк.
# ============================================================

def extract_strict_markers(raw_text: str) -> dict:
    out: dict[str, str] = {}

    # PRETENSION_DATE — дата у метки "Дата направления" в претензии.
    # (?!\s*скриншот) отсекает "Дата направления скриншотов:" (это SCREENSHOTS_DATE).
    # \s*:?\s* терпит дату на той же или следующей строке, с двоеточием или без.
    m = re.search(r"Дата\s+направления(?!\s*скриншот)\s*:?\s*(" + _DATE + r")", raw_text, re.IGNORECASE)
    if m:
        out["{{PRETENSION_DATE}}"] = m.group(1)

    # PENALTY_TO — дата после "по" в паре "с <дата> по <дата>", относящейся к пеням.
    # У документа две такие пары: период процентов и период пеней. Берём ту, перед
    # которой БЛИЖЕ стоит "пен"/"неустойк", чем "процент" — так пара процентов
    # отсекается даже если оба блока идут вплотную. Контекстный поиск не зависит
    # от точного расположения строк, устойчив к смене раскладки txt.
    # (?<![а-яёa-z]) — в Python 3 \w включает кириллицу, поэтому \b не отсекает
    # предшествующую букву ("процентовс"). Проверяем, что перед «с» нет буквы.
    pair_re = re.compile(r"(?<![а-яёa-z])с\s*(" + _DATE + r")\s+по\s*(" + _DATE + r")", re.IGNORECASE)
    for m in pair_re.finditer(raw_text):
        ctx = raw_text[max(0, m.start() - 150):m.start()].lower()
        pen = max(ctx.rfind("пен"), ctx.rfind("неустойк"))
        pct = ctx.rfind("процент")
        if pen > pct:
            out["{{PENALTY_TO}}"] = m.group(2)
            break

    return out


# ============================================================
# 9. Вычисление формул (производные плейсхолдеры)
# ============================================================

def _brace(k: str) -> str:
    kk = str(k).strip()
    if kk.startswith("{{"):
        kk = kk.lstrip("{").strip()
    if kk.endswith("}}"):
        kk = kk.rstrip("}").strip()
    return "{{" + kk + "}}"


def _get_s(map_: dict, key: str) -> str:
    b = _brace(key)
    if b in map_:
        return str(map_[b]).strip()
    if key in map_:
        return str(map_[key]).strip()
    return ""


def _parse_byn(s: str) -> float:
    if not s:
        return math.nan
    clean = "".join(ch for ch in str(s) if ch.isdigit() or ch in ",.-").replace(",", ".")
    try:
        return float(clean)
    except ValueError:
        return math.nan


def _format_byn(n) -> str:
    try:
        v = float(n)
    except (TypeError, ValueError):
        v = 0.0
    if not math.isfinite(v):
        v = 0.0
    return f"{v:.2f} BYN"


def _parse_date_dmy(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(str(s).strip(), "%d.%m.%Y")
    except ValueError:
        return None


def _to_dmy(d: datetime) -> str:
    return d.strftime("%d.%m.%Y")


def _date_add_days_dmy(dmy: str, days: int) -> str:
    d = _parse_date_dmy(dmy)
    if not d:
        return dmy or "___"
    return _to_dmy(d + timedelta(days=days))


def _initials(full: str) -> str:
    if not full:
        return "___"
    parts = str(full).strip().split()
    if len(parts) < 2:
        return full
    last = parts[0]
    first = parts[1] if len(parts) >= 2 else ""
    middle = parts[2] if len(parts) >= 3 else ""
    i1 = (first[0].upper() + ".") if first else ""
    i2 = (middle[0].upper() + ".") if middle else ""
    return (i1 + i2 + " " + last).strip()


def compute_formulas(data: dict) -> dict:
    in_map = {_brace(k): v for k, v in data.items() if isinstance(k, str)}

    loan_principal_s = _get_s(in_map, "LOAN_PRINCIPAL")
    loandate_start = _get_s(in_map, "LOANDATE_START")
    loandate_end = _get_s(in_map, "LOANDATE_END")
    judge_full = _get_s(in_map, "JUDGE_FULL")

    loan_principal_n = _parse_byn(loan_principal_s)
    interest_sum_n = _parse_byn(_get_s(in_map, "INTEREST_SUM"))
    penalty_sum_n = _parse_byn(_get_s(in_map, "PENALTY_SUM"))

    out: dict[str, str] = {}
    out["{{PRINCIPAL_SUM}}"] = _format_byn(loan_principal_n) if math.isfinite(loan_principal_n) else (loan_principal_s or "___")

    # {{TOTAL_SUM}} = основной долг + проценты + неустойка (число, "бел. руб." добавляет шаблон).
    if all(math.isfinite(x) for x in (loan_principal_n, interest_sum_n, penalty_sum_n)):
        out["{{TOTAL_SUM}}"] = f"{loan_principal_n + interest_sum_n + penalty_sum_n:.2f}"

    d_from = _parse_date_dmy(loandate_start)
    out["{{INTEREST_FROM}}"] = _to_dmy(d_from) if d_from else "___"
    d_to = _parse_date_dmy(loandate_end)
    out["{{INTEREST_TO}}"] = _to_dmy(d_to) if d_to else "___"

    out["{{PENALTY_FROM}}"] = _date_add_days_dmy(loandate_end, 1) if loandate_end else "___"
    # PENALTY_TO извлекается из Приложения иска (extract_strict_markers) — не перезаписываем.

    out["{{JUDGE_INITIALS}}"] = _initials(judge_full)

    # {{JUDGE_POSITION_WITH_DASH}} — должность судьи с тире впереди для строки подписи.
    judge_position = _get_s(in_map, "JUDGE_POSITION")
    out["{{JUDGE_POSITION_WITH_DASH}}"] = ("– " + judge_position) if judge_position else ""

    # CITY: гарантируем префикс "г. ".
    city = _get_s(in_map, "CITY")
    if city:
        bare = re.sub(r"^(?:г\.|город)\s*", "", city, flags=re.IGNORECASE).strip()
        if bare:
            out["{{CITY}}"] = f"г. {bare}"

    return out


# ============================================================
# 10. Правка регистра адресных меток
# ============================================================

def _fix_address_labels(text: str) -> str:
    if text is None:
        return text
    s = str(text)
    s = s.replace("Место Регистрации:", "место регистрации:")
    s = s.replace("Место Жительства:", "место жительства:")
    s = re.sub(r"\bпос[её]лок\s+городского\s+типа\b", "поселок городского типа", s, flags=re.IGNORECASE)
    s = re.sub(r"\bаг\.\s*", "аг. ", s, flags=re.IGNORECASE)
    s = re.sub(r"\bАгрогородок\b", "агрогородок", s)
    s = re.sub(r"\bагрогородок\b", "агрогородок", s)
    s = re.sub(r"\bДеревня\b", "деревня", s)
    s = re.sub(r"\bдеревня\b", "деревня", s)
    s = re.sub(r"\bбульвар\b", "бульвар", s, flags=re.IGNORECASE)
    s = re.sub(r"\bКорп.\b", "корп.", s)
    s = re.sub(r"\bкорп.\b", "корп.", s)
    return s


def fix_address_casing(data: dict) -> dict:
    triggers = ("место регистрации", "место жительства", "агрогородок", "деревня",
                "поселок городского типа", "посёлок городского типа", "аг.", "бульвар")
    for key, value in list(data.items()):
        if isinstance(value, str) and any(t in value.lower() for t in triggers):
            data[key] = _fix_address_labels(value)
    return data


# ============================================================
# Логирование запусков
# ============================================================

def _next_run_number_today(today: str) -> int:
    """Считает запуски за указанный день (YYYY-MM-DD) в runs.jsonl и возвращает следующий №."""
    if not RUNS_LOG.exists():
        return 1
    try:
        n = 0
        for line in RUNS_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(entry.get("started_at", "")).startswith(today):
                n += 1
        return n + 1
    except OSError:
        return 1


def _append_run_log(entry: dict) -> None:
    """Дописывает запись запуска в runs.jsonl и обрезает файл до RUNS_LOG_MAX строк."""
    try:
        RUNS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with RUNS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        try:
            with RUNS_LOG.open("r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > RUNS_LOG_MAX:
                with RUNS_LOG.open("w", encoding="utf-8") as f:
                    f.writelines(lines[-RUNS_LOG_MAX:])
        except OSError:
            pass
    except OSError:
        pass


# ============================================================
# Оркестрация
# ============================================================

def run_pipeline() -> dict:
    """Полный конвейер. Пишет out_txt/out_txt.json и возвращает словарь плейсхолдеров.

    Структурированный лог по шагам пишется в runs.jsonl (в корне проекта).
    Все значения извлекаются кодом — внешних вызовов нет.
    """
    error: str | None = None
    error_trace: str | None = None
    steps: list[dict] = []
    run_started_at = datetime.now()
    run_t0 = time.monotonic()

    def step(name: str, fn):
        """Выполняет шаг, замеряет время, ловит исключение и пишет в steps."""
        t0 = time.monotonic()
        st = {"name": name, "ok": True, "elapsed": 0.0, "info": None, "error": None}
        try:
            result = fn()
            st["elapsed"] = time.monotonic() - t0
            steps.append(st)
            return result
        except Exception as e:
            st["elapsed"] = time.monotonic() - t0
            st["ok"] = False
            st["error"] = f"{type(e).__name__}: {e}"
            steps.append(st)
            raise

    try:
        items = step("read_source_texts", lambda: read_source_texts())
        names = [n for n, _ in items]
        steps[-1]["info"] = f"files ({len(items)}): {', '.join(names) if names else '—'}"

        raw_combined = step("combine_texts", lambda: combine_texts(items))
        steps[-1]["info"] = f"chars: {len(raw_combined)}"

        combined = step("normalize_combined", lambda: normalize_combined(raw_combined))
        steps[-1]["info"] = f"chars: {len(combined)}"
        # Диагностический снимок входа (переживает clear_work_dirs(), как раньше).
        try:
            (BASE_DIR / "last_input.txt").write_text(combined, encoding="utf-8")
        except OSError:
            pass

        # Извлечение полей кодом. Каждое поле, не найденное регуляркой, просто
        # не попадает в результат (прогон не падает) — documents.py подставит пробел.
        placeholders: dict[str, str] = {}

        vvod = step("extract_vvod_dannyh", lambda: extract_vvod_dannyh(raw_combined))
        steps[-1]["info"] = f"keys: {len(vvod)}"
        placeholders.update(vvod)

        docs = step("extract_documents", lambda: extract_documents(raw_combined))
        steps[-1]["info"] = f"keys: {len(docs)}"
        placeholders.update(docs)

        # Нормализация ФИО/адресов/паспорта по именам ключей.
        placeholders = step("normalize_fields", lambda: _apply_normalizers(placeholders))
        steps[-1]["info"] = f"keys: {len(placeholders)}"

        cert = step("extract_from_certificate", lambda: extract_from_certificate(raw_combined))
        steps[-1]["info"] = f"overrides: {len(cert)}"
        placeholders.update(cert)

        strict = step("extract_strict_markers", lambda: extract_strict_markers(raw_combined))
        steps[-1]["info"] = f"overrides: {len(strict)}"
        placeholders.update(strict)

        placeholders = step("fix_address_casing", lambda: fix_address_casing(placeholders))
        formulas = step("compute_formulas", lambda: compute_formulas(placeholders))
        steps[-1]["info"] = f"computed: {len(formulas)}"

        def _save():
            result = {**placeholders, **formulas}
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        result = step("save_out_json", _save)
        steps[-1]["info"] = f"keys: {len(result)}"
        return result
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        error_trace = traceback.format_exc()
        traceback.print_exc()
        raise
    finally:
        total_elapsed = time.monotonic() - run_t0
        today = run_started_at.strftime("%Y-%m-%d")
        _append_run_log({
            "started_at": run_started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "num_today": _next_run_number_today(today),
            "ok": error is None,
            "total_elapsed": round(total_elapsed, 3),
            "error": error,
            "error_trace": error_trace,
            "steps": [
                {
                    "name": s["name"],
                    "ok": s["ok"],
                    "elapsed": round(s["elapsed"], 3),
                    "info": s["info"],
                    "error": s["error"],
                } for s in steps
            ],
        })


if __name__ == "__main__":
    out = run_pipeline()
    print(f"Извлечено плейсхолдеров: {len(out)} -> {OUT_JSON}")
