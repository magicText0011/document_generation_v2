import json
import os

import pymorphy3
from pytrovich.enums import NamePart, Gender, Case
from pytrovich.maker import PetrovichDeclinationMaker
from pytrovich.detector import PetrovichGenderDetector

# pymorphy3 оставлен ТОЛЬКО для склонения должности судьи (это не ФИО).
# Склонение самих ФИО переведено на pytrovich: он специализирован под антропонимы
# и определяет пол, поэтому корректно склоняет женские ФИО (напр. «Валерия» →
# «Валерии/Валерией»), где pymorphy3 ошибочно давал мужские формы.
morph = pymorphy3.MorphAnalyzer(lang="ru")

_maker = PetrovichDeclinationMaker()
_detector = PetrovichGenderDetector()

# ФИО во FULL-полях идут в порядке: Фамилия Имя Отчество.
_ROLE_BY_POS = [NamePart.LASTNAME, NamePart.FIRSTNAME, NamePart.MIDDLENAME]

# Падежи проекта -> падежи pytrovich.
_FIO_CASES = {
    "gent": Case.GENITIVE,    # родительный
    "datv": Case.DATIVE,      # дательный
    "ablt": Case.INSTRUMENTAL,  # творительный
}

# --- Должность судьи: pymorphy3 (без изменений логики) -----------------------

CASE_TAGS = {
    "nomn": "nomn",  # Именительный
    "gent": "gent",  # Родительный
    "datv": "datv",  # Дательный
    "ablt": "ablt",  # Творительный
}

def _inflect_word(word: str, gram_case: str) -> str:
    """Склоняет ОДНО слово в указанный падеж через pymorphy3.

    Используется только для должности судьи («заместитель председателя …»).
    """
    if not word:
        return word
    tag = CASE_TAGS.get(gram_case)
    if not tag:
        return word
    parses = morph.parse(word)
    if not parses:
        return word

    def score(p):
        s = 0
        t = p.tag
        if "Surn" in t: s += 3
        if "Name" in t: s += 2
        if "Patr" in t: s += 2
        if "sing" in t: s += 1
        if "plur" in t: s -= 2
        return s

    p = max(parses, key=score)
    inf = p.inflect({tag})
    if not inf:
        return word
    w = inf.word
    if w.lower() == word.lower():
        return word
    if word[0].isupper():
        w = w.capitalize()
    return w

def inflect_phrase(text: str, gram_case: str) -> str:
    if not text:
        return text
    parts = text.split()
    inflected_parts = [_inflect_word(p, gram_case) for p in parts]
    return " ".join(inflected_parts)

# --- ФИО: pytrovich ----------------------------------------------------------

def _detect_gender(tokens: list[str]) -> Gender:
    """Определяет пол по ФИО. Приоритет — отчество (самый надёжный признак),
    иначе — встроенный детектор pytrovich.
    """
    last = tokens[0] if len(tokens) > 0 else ""
    first = tokens[1] if len(tokens) > 1 else ""
    middle = tokens[2] if len(tokens) > 2 else ""

    ml = middle.lower()
    if ml.endswith(("вна", "ична", "инична")):
        return Gender.FEMALE
    if ml.endswith(("вич", "ич")):
        return Gender.MALE

    try:
        g = _detector.detect(firstname=first or None,
                             middlename=middle or None,
                             lastname=last or None)
    except Exception:
        g = Gender.ANDROGYNOUS
    return g if g in (Gender.MALE, Gender.FEMALE) else Gender.MALE

def inflect_fio(full_name: str, gram_case: str) -> str:
    """Склоняет ФИО (Фамилия Имя Отчество) в падеж через pytrovich.

    Токены с точкой (инициалы) и однобуквенные не склоняются. Неизвестный падеж
    или ошибка склонения слова — слово остаётся как есть.
    """
    full_name = (full_name or "").strip()
    if not full_name:
        return full_name
    case = _FIO_CASES.get(gram_case)
    if case is None:
        return full_name

    tokens = full_name.split()
    gender = _detect_gender(tokens)

    out = []
    role_idx = 0
    for tok in tokens:
        if "." in tok or len(tok) <= 1 or role_idx >= len(_ROLE_BY_POS):
            out.append(tok)
            continue
        part = _ROLE_BY_POS[role_idx]
        role_idx += 1
        try:
            out.append(_maker.make(part, gender, case, tok))
        except Exception:
            out.append(tok)
    return " ".join(out)

# --- Сборка форм -------------------------------------------------------------

def build_judge_forms(judge_name_nom: str, judge_position_nom: str) -> dict:
    judge_name_nom = (judge_name_nom or "").strip()
    judge_position_nom = (judge_position_nom or "").strip()

    judge_name_gent = inflect_fio(judge_name_nom, "gent")
    name_fixed = (judge_name_gent == judge_name_nom)

    judge_pos_gent = inflect_phrase(judge_position_nom, "gent") if judge_position_nom else ""
    return {
        "JUDGE_NAME": judge_name_nom,
        "JUDGE_POSITION": judge_position_nom,
        "JUDGE_NAME_GENT": judge_name_gent,
        "JUDGE_POSITION_GENT": judge_pos_gent,
        "JUDGE_NAME_INDECLINABLE": name_fixed,
    }

def _build_party_forms(name_nom: str, prefix: str) -> dict:
    name_nom = (name_nom or "").strip()
    if not name_nom:
        return {
            f"{prefix}_NAME": "",
            f"{prefix}_NAME_GENT": "",
            f"{prefix}_NAME_DAT": "",
            f"{prefix}_NAME_ABLT": "",
            f"{prefix}_NAME_INDECLINABLE": True,
        }
    gent = inflect_fio(name_nom, "gent")
    dat = inflect_fio(name_nom, "datv")
    ablt = inflect_fio(name_nom, "ablt")
    indeclinable = (gent == name_nom and dat == name_nom and ablt == name_nom)
    return {
        f"{prefix}_NAME": name_nom,
        f"{prefix}_NAME_GENT": gent,
        f"{prefix}_NAME_DAT": dat,
        f"{prefix}_NAME_ABLT": ablt,
        f"{prefix}_NAME_INDECLINABLE": indeclinable,
    }

def build_all_forms(judge_name_nom: str, judge_position_nom: str,
                    plaintiff_name_nom: str, defendant_name_nom: str) -> dict:
    data = {}
    data.update(build_judge_forms(judge_name_nom, judge_position_nom))
    data.update(_build_party_forms(plaintiff_name_nom, "PLAINTIFF"))
    data.update(_build_party_forms(defendant_name_nom, "DEFENDANT"))
    return data

def process_and_update(json_data: dict, save_path: str = "out_txt/out_txt.json") -> dict:
    # вытягиваем исходные значения
    judge_name = json_data.get("{{JUDGE_FULL}}", "")
    judge_position = json_data.get("{{JUDGE_POSITION}}", "")
    plaintiff_name = json_data.get("{{PLAINTIFF_FULL}}", "")
    defendant_name = json_data.get("{{DEFENDANT_FULL}}", "")

    # получаем формы
    forms = build_all_forms(judge_name, judge_position, plaintiff_name, defendant_name)

    # оборачиваем ключи в {{...}}
    forms_with_placeholders = {f"{{{k}}}": v for k, v in forms.items()}

    # дописываем новые ключи в исходный JSON
    json_data.update(forms_with_placeholders)

    # УДАЛЯЕМ исходный плейсхолдер должности судьи
    json_data.pop("{{JUDGE_POSITION}}", None)

    # сохраняем обновлённый JSON
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    return json_data
