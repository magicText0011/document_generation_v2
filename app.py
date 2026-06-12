
import os

from flask import (
    Flask,
    request,
    render_template,
    jsonify,
    send_from_directory,
    render_template_string,
    session,
    redirect,
    url_for,
    Response,
    flash,
    send_file,
)


from uploading_documents import save_and_forward
from data_entry import save_txt
from utils import pack_out_txt_only
from pathlib import Path

from placeholders_api import register_placeholders_routes

from documents import generate_documents, OUTPUT_DIR, ZIP_NAME

import json
from morph_fio import process_and_update   # импортируем твою функцию
from flask import after_this_request
import shutil

from config import get_delay_seconds

# создаём экземпляр приложения


app = Flask(__name__)

BASE_DIR = Path(__file__).parent.resolve()
INDEX_PATH = BASE_DIR / "templates" / "index.html"
####вставка
OUT_JSON = BASE_DIR / "out_txt" / "out_txt.json"
####вставка
register_placeholders_routes(app, OUT_JSON)



app.secret_key = "my-secret-key-123456789"

# простой маршрут для проверки
# @app.route('/')
# def index():
#     text = INDEX_PATH.read_text(encoding="utf-8")
#
#     app_url = os.getenv("APP_URL", "http://localhost:5678")
#     text = text.replace("http://localhost:5678", app_url)
#
#     return Response(text, mimetype="text/html; charset=utf-8")

@app.route('/')
def index():
    text = INDEX_PATH.read_text(encoding="utf-8")

    app_url = os.getenv("APP_URL", "http://localhost:56782")
    text = text.replace("http://localhost:56782", app_url)

    # задержка обработки документов (из .env) -> в JS как миллисекунды
    delay_ms = int(get_delay_seconds() * 1000)
    text = text.replace("__PROCESSING_DELAY_MS__", str(delay_ms))

    return Response(text, mimetype="text/html; charset=utf-8")


# импорт файла ввод-данных
@app.route('/generate-txt', methods=['POST'])
def generate_txt():
    form_data = request.form.to_dict()
    filepath = save_txt(form_data)
    print(f"Файл сохранён: {filepath}")
    return redirect(url_for('index'))  # или вернуть сообщение об успехе

# @app.route('/convert-and-send', methods=['POST'])
# def convert_and_send():
#     files = {
#         'file1': request.files.get('file1'),
#         'file2': request.files.get('file2'),
#         'file3': request.files.get('file3'),
#         'file4': request.files.get('file4'),
#         'file5': request.files.get('file5'),
#     }
#     result = save_and_forward(files)
#     print(result)
#     return redirect(url_for('index'))

@app.route('/convert-and-send', methods=['POST'])
def convert_and_send():
    """
    Принимаем несколько файлов из поля name="files"
    и собираем словарь в формате file1..file4,
    как раньше, чтобы save_and_forward продолжал работать.
    """
    uploaded_files = request.files.getlist('files')  # все выбранные файлы

    files = {}
    idx = 1
    for f in uploaded_files:
        if not f or not f.filename:
            continue

        key = f'file{idx}'
        files[key] = f
        idx += 1
        # если твой save_and_forward рассчитан максимум на 4 файла — ограничиваем
        if idx > 4:
            break

    # если ничего не пришло — просто назад на главную
    if not files:
        print("convert-and-send: не получено ни одного файла")
        return redirect(url_for('index'))

    # здесь вся магия: конвертация и отправка, как было в старой версии
    result = save_and_forward(files)
    print("convert-and-send result:", result)

    # возвращаемся на главную страницу, как раньше
    return redirect(url_for('index'))




@app.route("/upload", methods=["POST"])
def upload_files():
    files = request.files.getlist("files")
    out_dir = Path("out_txt")
    out_dir.mkdir(exist_ok=True)

    # сохраняем загруженные файлы
    for f in files:
        f.save(out_dir / f.filename)

@app.route("/pack-zip", methods=["POST"])
def pack_zip():
    zip_path = pack_out_txt_only()
    return jsonify({"status": "ok", "zip_file": str(zip_path)})



@app.route("/run-n8n", methods=["POST"])
def run_n8n():
    # Извлечение плейсхолдеров теперь выполняется локально на Python (без n8n).
    from pipeline import run_pipeline
    result = run_pipeline()
    return jsonify(result)


# Человекочитаемая страница логов запусков из runs.jsonl. Self-contained:
# server-side рендер, без JS/шаблонов.
RUNS_PAGE_TEMPLATE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Логи запусков — runs.json</title>
<style>
 body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:24px;background:#f6f7f9;color:#1c1e21}
 h1{font-size:20px;margin:0 0 16px}
 .run{background:#fff;border:1px solid #dcdfe3;border-radius:8px;margin-bottom:14px;padding:12px 14px}
 .run.bad{border-color:#e0b4b4;background:#fff7f7}
 .hdr{display:flex;flex-wrap:wrap;gap:14px;align-items:center;font-size:14px}
 .st-ok{color:#137333;font-weight:600}
 .st-bad{color:#c5221f;font-weight:600}
 .muted{color:#65676b}
 .err{color:#c5221f;white-space:pre-wrap;margin-top:8px;font-family:ui-monospace,monospace;font-size:12px}
 table.steps{border-collapse:collapse;width:100%;margin-top:10px;font-size:13px}
 table.steps th,table.steps td{border:1px solid #e3e6ea;padding:4px 8px;text-align:left;vertical-align:top}
 table.steps th{background:#f0f2f5}
 .empty{color:#65676b;font-size:15px}
 details summary{cursor:pointer;color:#1a73e8;font-size:13px;margin-top:8px}
</style></head><body>
<h1>Логи запусков — runs.json ({{ runs|length }})</h1>
{% if not runs %}<p class="empty">Логов пока нет.</p>{% endif %}
{% for r in runs %}
 <div class="run {{ '' if r.ok else 'bad' }}">
  <div class="hdr">
   <span class="{{ 'st-ok' if r.ok else 'st-bad' }}">{{ '✓ OK' if r.ok else '✗ ОШИБКА' }}</span>
   <span>{{ r.started_at }}</span>
   <span class="muted">№ за день: {{ r.num_today }}</span>
   <span class="muted">всего: {{ r.total_elapsed }} c</span>
  </div>
  {% if r.error %}<div class="err">{{ r.error }}</div>{% endif %}
  {% if r.steps %}
  <details><summary>шаги ({{ r.steps|length }})</summary>
   <table class="steps">
    <tr><th>шаг</th><th>ok</th><th>время, c</th><th>info</th><th>ошибка</th></tr>
    {% for s in r.steps %}
    <tr><td>{{ s.name }}</td><td>{{ '✓' if s.ok else '✗' }}</td><td>{{ s.elapsed }}</td><td>{{ s.info or '' }}</td><td class="err" style="margin:0">{{ s.error or '' }}</td></tr>
    {% endfor %}
   </table>
  </details>
  {% endif %}
 </div>
{% endfor %}
</body></html>"""


@app.route("/logs", methods=["GET"])
def logs_page():
    """Страница логов запусков конвейера из runs.jsonl (новые сверху)."""
    from pipeline import RUNS_LOG
    runs = []
    if RUNS_LOG.exists():
        try:
            for line in RUNS_LOG.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    runs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass
        runs.reverse()
    return render_template_string(RUNS_PAGE_TEMPLATE, runs=runs)


@app.route("/morph-fio", methods=["POST"])
def morph_fio_endpoint():
    # путь к JSON в папке out_txt
    file_path = os.path.join("out_txt", "out_txt.json")  # например, data.json

    # читаем файл
    with open(file_path, "r", encoding="utf-8") as f:
        json_data = json.load(f)

    # обрабатываем и дополняем склонениями
    updated = process_and_update(json_data)

    # возвращаем обновлённый JSON
    return jsonify(updated)

####вставка
@app.get("/get-placeholders")
def get_placeholders():
    if not OUT_JSON.exists():
        return jsonify({"ok": False, "error": "out_txt/out_txt.json not found"}), 404
    try:
        data = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        return jsonify({"ok": True, "placeholders": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
###вставка

@app.route("/generate-docs", methods=["POST"])
def generate_docs():
    """
    Кнопка 'Сформировать документы':
    запускает generate_documents() из documents.py
    """
    try:
        zip_path = generate_documents()
        flash(f"Документы сформированы: {zip_path.name}")
    except Exception as e:
        flash(f"Ошибка при генерации документов: {e}")
    # если твой основной роут называется не index, поставь его имя
    return redirect(url_for("index"))
# функцию очистки
def clear_work_dirs():
    dirs_to_clear = [
        Path("out_txt"),
        OUTPUT_DIR,   # out_docs
    ]

    for d in dirs_to_clear:
        if d.exists() and d.is_dir():
            shutil.rmtree(d)
            d.mkdir(exist_ok=True)

    # также можно удалить zip, если нужно
    zip_path = OUTPUT_DIR / ZIP_NAME
    if zip_path.exists():
        try:
            zip_path.unlink()
        except Exception:
            pass



#
# @app.route("/download-docs", methods=["GET"])
# def download_docs():
#     """
#     Кнопка 'Скачать документы':
#     отдаёт архив documents.zip
#     """
#     zip_path = OUTPUT_DIR / ZIP_NAME
#     try:
#         # если архива ещё нет — сначала сгенерировать
#         if not zip_path.exists():
#             zip_path = generate_documents()
#
#         return send_file(
#             zip_path,
#             as_attachment=True,
#             download_name=zip_path.name,
#             mimetype="application/zip",
#         )
#     except Exception as e:
#         flash(f"Ошибка при скачивании: {e}")
#         return redirect(url_for("index"))

@app.route("/download-docs", methods=["GET"])
def download_docs():
    """
    Кнопка 'Скачать документы':
    отдаёт архив documents.zip
    и ПОСЛЕ СКАЧИВАНИЯ очищает все рабочие папки
    """
    zip_path = OUTPUT_DIR / ZIP_NAME

    try:
        # если архива ещё нет — сначала сгенерировать
        if not zip_path.exists():
            zip_path = generate_documents()

        @after_this_request
        def cleanup(response):
            try:
                clear_work_dirs()
                print("✅ Все рабочие папки очищены")
            except Exception as e:
                print("❌ Ошибка очистки:", e)
            return response

        return send_file(
            zip_path,
            as_attachment=True,
            download_name=zip_path.name,
            mimetype="application/zip",
        )

    except Exception as e:
        flash(f"Ошибка при скачивании: {e}")
        return redirect(url_for("index"))


# точка входа
if __name__ == '__main__':
    # debug=True — для разработки, автоматически перезапускает сервер при изменениях
    app.run(host='0.0.0.0', port=8000, debug=True)
