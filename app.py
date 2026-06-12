
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
from flask import after_this_request, got_request_exception
import shutil

from config import get_delay_seconds
from app_log import log_event, log_exception, read_events, clear_events

# создаём экземпляр приложения


app = Flask(__name__)

BASE_DIR = Path(__file__).parent.resolve()
INDEX_PATH = BASE_DIR / "templates" / "index.html"
####вставка
OUT_JSON = BASE_DIR / "out_txt" / "out_txt.json"
####вставка
register_placeholders_routes(app, OUT_JSON)



app.secret_key = "my-secret-key-123456789"


# ===== Сквозное логирование событий и ошибок =====
# Шумные/частые служебные запросы в лог не пишем (поллинг, статика, сами страницы логов).
_LOG_SKIP_PATHS = {"/get-placeholders", "/api/logs", "/logs", "/logs/clear", "/runs", "/favicon.ico"}


def _skip_log(path: str) -> bool:
    return path in _LOG_SKIP_PATHS or path.startswith("/static")


@app.before_request
def _log_request_start():
    if not _skip_log(request.path):
        log_event("request", message=f"{request.method} {request.path}")


@app.after_request
def _log_request_end(response):
    if not _skip_log(request.path):
        level = "WARNING" if response.status_code >= 400 else "INFO"
        log_event("response", level=level,
                  message=f"{request.method} {request.path} -> {response.status_code}")
    return response


def _log_unhandled(sender, exception, **extra):
    # Логируем любое необработанное исключение, не меняя поведение Flask (в debug
    # остаётся интерактивный трейсбэк).
    try:
        log_exception("unhandled_error", exception, path=request.path, method=request.method)
    except Exception:
        log_exception("unhandled_error", exception)


got_request_exception.connect(_log_unhandled, app)

log_event("startup", message="Приложение запущено")

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

    # задержка обработки документов (из config.json) -> в JS как миллисекунды
    delay_ms = int(get_delay_seconds() * 1000)
    text = text.replace("__PROCESSING_DELAY_MS__", str(delay_ms))

    return Response(text, mimetype="text/html; charset=utf-8")


# импорт файла ввод-данных
@app.route('/generate-txt', methods=['POST'])
def generate_txt():
    form_data = request.form.to_dict()
    filepath = save_txt(form_data)
    log_event("save_txt", message=f"Сохранён файл ввода данных: {filepath}")
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
        log_event("convert", level="WARNING", message="Не получено ни одного файла")
        return redirect(url_for('index'))

    # здесь вся магия: конвертация и отправка, как было в старой версии
    log_event("convert_start", message=f"Конвертация документов, файлов: {len(files)}", files=len(files))
    try:
        result = save_and_forward(files)
    except Exception as e:
        log_exception("convert_failed", e, files=len(files))
        raise
    log_event("convert_done", message=f"Конвертация завершена, файлов: {len(files)}", files=len(files))

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
    log_event("pipeline_start", message="Запуск конвейера извлечения плейсхолдеров")
    try:
        result = run_pipeline()
    except Exception as e:
        log_exception("pipeline_failed", e)
        raise
    log_event("pipeline_done", message=f"Извлечено плейсхолдеров: {len(result)}", placeholders=len(result))
    return jsonify(result)


EVENTS_PAGE_TEMPLATE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Логи событий приложения</title>
<style>
 body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:24px;background:#f6f7f9;color:#1c1e21}
 h1{font-size:20px;margin:0 0 4px}
 .sub{color:#65676b;font-size:13px;margin:0 0 16px}
 .toolbar{display:flex;gap:8px;align-items:center;margin-bottom:14px;flex-wrap:wrap}
 .btn{display:inline-block;padding:6px 12px;border:1px solid #d0d0d6;background:#fff;border-radius:6px;cursor:pointer;font-size:13px;color:#222;text-decoration:none}
 .btn:hover{background:#f0f0f3}
 .btn.danger{color:#b00;border-color:#e0b0b0}
 .count{margin-left:auto;color:#666;font-size:13px}
 table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #dcdfe3;border-radius:8px;overflow:hidden;font-size:13px}
 th,td{border-bottom:1px solid #eef0f2;padding:7px 10px;text-align:left;vertical-align:top}
 th{background:#f0f2f5;font-weight:600;position:sticky;top:0}
 td.ts{font-family:ui-monospace,monospace;color:#555;white-space:nowrap}
 td.ev{font-family:ui-monospace,monospace;color:#1c1e21;white-space:nowrap}
 tr.ERROR{background:#fff7f7}
 tr.WARNING{background:#fffdf3}
 .pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600}
 .pill.INFO{background:#e8f0fe;color:#1a56c4}
 .pill.WARNING{background:#fef3c7;color:#92600a}
 .pill.ERROR{background:#fdecec;color:#b00020}
 .err{color:#b00020;white-space:pre-wrap;font-family:ui-monospace,monospace;font-size:12px;margin-top:6px}
 details summary{cursor:pointer;color:#1a73e8}
 .empty{color:#65676b;font-size:15px;padding:30px 0}
</style></head><body>
<h1>Логи событий</h1>
<p class="sub">Все события работы приложения и ошибки (новые сверху). Детализация по шагам конвейера — на <a href="/runs">/runs</a>.</p>
<div class="toolbar">
 <a class="btn" href="/logs">↻ Обновить</a>
 <form method="post" action="/logs/clear" style="display:inline" onsubmit="return confirm('Очистить весь лог?')">
   <button class="btn danger" type="submit">Очистить лог</button>
 </form>
 <span class="count">событий: {{ events|length }}</span>
</div>
{% if not events %}<p class="empty">Событий пока нет.</p>{% else %}
<table>
 <tr><th>Время</th><th>Уровень</th><th>Событие</th><th>Сообщение</th></tr>
 {% for e in events %}
 <tr class="{{ e.level }}">
  <td class="ts">{{ e.ts }}</td>
  <td><span class="pill {{ e.level }}">{{ e.level }}</span></td>
  <td class="ev">{{ e.event }}</td>
  <td>{{ e.message }}{% if e.error %}<details><summary>трейсбэк</summary><div class="err">{{ e.error }}</div></details>{% endif %}</td>
 </tr>
 {% endfor %}
</table>
{% endif %}
</body></html>"""


@app.route("/logs", methods=["GET"])
def logs_page():
    """Страница со сквозными логами событий приложения (новые сверху)."""
    return render_template_string(EVENTS_PAGE_TEMPLATE, events=read_events(500))


@app.route("/logs/clear", methods=["POST"])
def logs_clear():
    clear_events()
    log_event("logs_cleared", message="Лог событий очищен вручную")
    return redirect(url_for("logs_page"))


@app.route("/api/logs", methods=["GET"])
def api_logs():
    """Отдаёт последние запуски конвейера из runs.jsonl (новые сверху)."""
    from pipeline import RUNS_LOG
    if not RUNS_LOG.exists():
        return jsonify({"ok": True, "runs": []})
    runs = []
    try:
        for line in RUNS_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                runs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    runs.reverse()
    return jsonify({"ok": True, "runs": runs})


# Отдельная человекочитаемая страница логов запусков (тот же runs.jsonl, что и
# /api/logs; сосуществует с /logs). Self-contained: server-side рендер, без JS/шаблонов.
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
   <span class="muted">LLM: {{ r.ai_elapsed }} c</span>
   <span class="muted">токены: in {{ r.usage.get('prompt_tokens', r.usage.get('input_tokens', '—')) }} / out {{ r.usage.get('completion_tokens', r.usage.get('output_tokens', '—')) }}</span>
   <span class="muted">${{ '%.6f'|format(r.cost_usd or 0) }}</span>
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


@app.route("/runs", methods=["GET"])
def runs_page():
    """Человекочитаемая страница логов запусков из runs.jsonl (новые сверху)."""
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
    try:
        updated = process_and_update(json_data)
    except Exception as e:
        log_exception("morph_fio_failed", e)
        raise
    log_event("morph_fio", message="Склонения ФИО добавлены")

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
        log_event("generate_docs", message=f"Документы сформированы: {zip_path.name}")
        flash(f"Документы сформированы: {zip_path.name}")
    except Exception as e:
        log_exception("generate_docs_failed", e)
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
                log_event("cleanup", message="Рабочие папки очищены после скачивания")
            except Exception as e:
                log_exception("cleanup_failed", e)
            return response

        log_event("download_docs", message=f"Отдан архив: {zip_path.name}")
        return send_file(
            zip_path,
            as_attachment=True,
            download_name=zip_path.name,
            mimetype="application/zip",
        )

    except Exception as e:
        log_exception("download_docs_failed", e)
        flash(f"Ошибка при скачивании: {e}")
        return redirect(url_for("index"))


# точка входа
if __name__ == '__main__':
    # debug=True — для разработки, автоматически перезапускает сервер при изменениях
    app.run(host='0.0.0.0', port=8000, debug=True)


#
#
#
#
