

import os
from datetime import datetime


def fmt_date(raw: str) -> str:
    """
    Превратить дату из HTML (YYYY-MM-DD) в формат dd.mm.yyyy.
    Если не получилось распарсить — вернуть как есть.
    """
    if not raw:
        return ""
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d")
        # если нужны точки:
        return dt.strftime("%d.%m.%Y")

        # return dt.strftime("%d;%m;%Y")
    except ValueError:
        return raw


def save_txt(data: dict, output_folder: str = "out_txt") -> str:
    """
    Принимает словарь с данными и сохраняет файл vvod_dannyh.txt в указанной папке.
    Возвращает путь к созданному файлу.
    """
    os.makedirs(output_folder, exist_ok=True)
    filepath = os.path.join(output_folder, "vvod_dannyh.txt")
    # добавление (г.) перед Минском во "ввод данных"
    city = (data.get("city") or "").strip()
    if city:
        city_out = f"г. {city}"
    else:
        city_out = ""


    # обработка должности судьи
    position = (data.get("judge_position") or "").strip()
    # Для "третейский судья" (базовая позиция), её род. падежа и ярлыка "Должность судьи"
    # значение обнуляем. В documents.py пустые ключи JUDGE_POSITION_* заменяются на
    # один пробел — в тексте останется лишний пробел вместо значения.
    if position.lower() in ("третейский судья", "третейского судьи", "должность судьи"):
        position_out = ""
    else:
        position_out = position

    screenshots_date = data.get("screenshots_sent_date")



    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"Город: {city_out}\n")
        # f.write(f"Город: {data.get('г.''city')}\n")
        f.write(f"Номер дела: {data.get('case_number')}\n")
        f.write(f"Дата вынесения определения: {fmt_date(data.get('decision_date'))}\n")
        f.write(f"ФИО судьи: {data.get('judge_name')}\n")
        # f.write(f"Должность судьи: {data.get('judge_position')}\n")
        # Для "Третейский судья" position_out=="" → строка с пробелом после двоеточия.
        # Это даёт LLM явный сигнал, что значение — пустое/пробел, иначе он
        # вытащит "третейский судья" из других документов в combined-тексте.
        f.write(f"Должность судьи: {position_out}\n")
        f.write(f"Адрес третейского суда: {data.get('court_address')}\n")
        f.write(f"Номер свидетельства СОЗ: {data.get('soz_certificate_number')}\n")
        f.write(f"Дата свидетельства СОЗ: {fmt_date(data.get('soz_certificate_date'))}\n")
        f.write(f"Дата направления скриншотов: {fmt_date(data.get('screenshots_sent_date'))}\n")
        f.write(f"Дата заседания: {fmt_date(data.get('session_date'))}\n")
        f.write(f"Время заседания: {data.get('session_time')}\n")
        f.write(f"Крайний срок подачи документов: {fmt_date(data.get('deadline_date'))}\n")
        f.write(f"Электронная почта суда: {data.get('court_email')}\n")
        f.write(f"Дата вынесения решения: {fmt_date(data.get('resolution_date'))}\n")
        f.write(f"Сумма арбитражного сбора: {data.get('fee_amount')}\n")

    return filepath

