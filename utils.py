# #  объединение в общий docx
# from pathlib import Path
# from docx import Document
#
# def pack_out_txt_only():
#     out_dir = Path("out_txt")
#     merged_path = out_dir / "out_txt.docx"
#
#     out_dir.mkdir(parents=True, exist_ok=True)
#
#     merged_doc = Document()
#
#     # Собираем список файлов .docx, исключая будущий объединённый файл
#     files = sorted([f for f in out_dir.glob("*.docx") if f.name != merged_path.name])
#
#     for i, file in enumerate(files):
#         # Заголовок с именем файла (жирный)
#         hdr = merged_doc.add_paragraph()
#         run = hdr.add_run(f"===== {file.name} =====")
#         run.bold = True
#
#         # Копируем параграфы из исходного DOCX
#         try:
#             src = Document(file)
#             for p in src.paragraphs:
#                 # Добавляем текст параграфа (сохраняем переносы)
#                 merged_doc.add_paragraph(p.text)
#         except Exception as e:
#             # Если не удалось прочитать файл, добавим заметку об ошибке
#             merged_doc.add_paragraph(f"[ошибка чтения {file.name}: {e}]")
#
#         # Разделитель между файлами (пустой параграф), кроме последнего
#         if i != len(files) - 1:
#             merged_doc.add_paragraph()
#
#     # Сохраняем объединённый DOCX
#     merged_doc.save(merged_path)
#
#     # Удаляем все исходные .docx кроме объединённого
#     for file in out_dir.glob("*.docx"):
#         if file.name != merged_path.name:
#             try:
#                 file.unlink()
#             except Exception:
#                 # если не удалось удалить — пропускаем
#                 pass
#
#     return merged_path


# # объединение в общий txt

from pathlib import Path

def pack_out_txt_only():
    out_dir = Path("out_txt")
    merged_path = out_dir / "out_txt.txt"

    # открываем итоговый файл для записи
    with merged_path.open("w", encoding="utf-8") as outfile:
        for file in out_dir.glob("*.txt"):
            if file.name != "out_txt.txt":  # не включаем сам объединённый файл
                # читаем содержимое
                content = file.read_text(encoding="utf-8")
                # пишем имя файла как заголовок
                outfile.write(f"===== {file.name} =====\n")
                outfile.write(content + "\n\n")

    # удаляем все остальные txt кроме объединённого
    for file in out_dir.glob("*.txt"):
        if file.name != "out_txt.txt":
            file.unlink()

    return merged_path
