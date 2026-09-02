# AGENTS.md

## Commands

```bash
# Run full pipeline standalone (reads out_txt/*.txt, writes out_txt/out_txt.json)
python3 pipeline.py

# Run Flask dev server
python3 app.py

# Run doc gen standalone
python3 documents.py

# Convert files to txt (CLI)
python3 app_converter.py -o out_txt <files...>

# Docker (production)
docker compose up -d --build        # build & start
docker compose -f docker-compose-dev.yml up -d   # dev (port 8899)

# .env changes require container recreate (not restart)
docker compose up -d
```

## Architecture (see `CLAUDE.md` for full flow)

**No tests, no linting, no typechecking** — none exist. Do not look for them.

`app.py` endpoints in user flow order:
`/convert-and-send` (upload files) → `/generate-txt` (form) → `/run-n8n` (pipeline) → `/morph-fio` (inflect) → `/generate-docs` (docx) → `/download-docs` (+ cleanup)

`/download-docs` runs `clear_work_dirs()` after sending zip — **deletes `out_txt/` and `out_docs/`** including `last_input.txt` and `runs.jsonl`.

## Gotchas

- **CLAUDE.md** is the existing instruction source — keep it in sync.
- `app_converter.py` and `documents.py` have large **commented-out old code** at the top; active code is the second half of the file.
- `app_converter.py:docx_to_text()` reads DOCX via **raw XML** (not python-docx paragraphs) to capture table text.
- OCR (easyocr) is **lazy-loaded** (`_get_reader()`) — first image/PDF scan is slow.
- `morph_fio.py:process_and_update()` **removes `{{JUDGE_POSITION}}`** after processing (replaced by `JUDGE_POSITION_GENT`, `JUDGE_POSITION_WITH_DASH`).
- Pipeline keys use `{{KEY}}` format in `out_txt.json`; `documents.py:build_mapping()` also generates `{KEY}` and bare `KEY` variants for template matching.
- **Read order of out_txt/*.txt is alphabetical** (sorted glob) — `vvod_dannyh.txt` must come first in sort order.
- Extractors are regex-tied to Kapusta template phrasing; changing extractors risks breaking all document types.
- `placeholders_api.py` provides manual placeholder editing (`GET /get-placeholders`, `POST /update-placeholders`) with atomic JSON writes.
- When editing template `.docx` files in `templates/`, remember `build_mapping()` matches `{{KEY}}`, `{KEY}`, and bare `KEY`.
