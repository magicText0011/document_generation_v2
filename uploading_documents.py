
# import os
from werkzeug.datastructures import FileStorage
# from document_processing import process_documents
from app_converter import convert_uploaded_files   # импортируем конвертер
from pathlib import Path

UPLOAD_FOLDER = "out_txt"  # сохраняем в папку out_txt

# def save_and_forward(files: dict) -> str:
#     """
#     Сохраняет загруженные файлы и передаёт их в document_processing.py.
#     Возвращает статус или путь к результату.
#     """
#     os.makedirs(UPLOAD_FOLDER, exist_ok=True)
#     saved_paths = []
#
#     for key, file in files.items():
#         if isinstance(file, FileStorage) and file.filename:
#             filename = f"{key}_{file.filename}"
#             filepath = os.path.join(UPLOAD_FOLDER, filename)
#             file.save(filepath)
#             saved_paths.append(filepath)
#
#
#     result_files = convert_uploaded_files(files, Path(UPLOAD_FOLDER))
#
#     return result_files
def save_and_forward(files: dict):
    """
    Передаёт загруженные файлы в общий обработчик.
    Возвращает результат конвертации.
    """
    # просто вызываем конвертер, без ручного сохранения
    result_files = convert_uploaded_files(files, Path(UPLOAD_FOLDER))
    return result_files

#
#
# from werkzeug.datastructures import FileStorage
# # from document_processing import process_documents
#
# UPLOAD_FOLDER = "uploaded_docs"
#
# def save_and_forward(files: dict) -> str:
#     """
#     Сохраняет загруженные файлы и передаёт их в document_processing.py.
#     Возвращает статус или путь к результату.
#     """
#     os.makedirs(UPLOAD_FOLDER, exist_ok=True)
#     saved_paths = []
#
#     for key, file in files.items():
#         if isinstance(file, FileStorage) and file.filename:
#             filename = f"{key}_{file.filename}"
#             filepath = os.path.join(UPLOAD_FOLDER, filename)
#             file.save(filepath)
#             saved_paths.append(filepath)
#
#     # передаём список путей в обработчик
#     # result = process_documents(saved_paths)
#     result = 1
#     return result
