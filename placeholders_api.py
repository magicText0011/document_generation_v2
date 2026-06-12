#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
placeholders_api.py

Flask routes to:
- GET  /get-placeholders        -> read out_txt/out_txt.json
- POST /update-placeholders     -> merge & persist updates to out_txt/out_txt.json (atomic write)

Usage (in app.py):

from pathlib import Path
from placeholders_api import register_placeholders_routes

BASE_DIR = Path(__file__).parent.resolve()
OUT_JSON = BASE_DIR / "out_txt" / "out_txt.json"

app = Flask(__name__)
register_placeholders_routes(app, OUT_JSON)

Notes:
- POST expects JSON: {"placeholders": {"KEY": "VALUE", ...}}
- Values can be string/number/bool/null; they will be saved as-is.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, Flask, jsonify, request


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON atomically and keep a best-effort .bak backup."""
    path.parent.mkdir(parents=True, exist_ok=True)

    # backup (best-effort)
    if path.exists():
        try:
            bak = path.with_suffix(path.suffix + ".bak")
            if bak.exists():
                bak.unlink()
            path.replace(bak)
        except Exception:
            pass

    fd, tmp_name = tempfile.mkstemp(prefix="out_txt_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, str(path))
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except Exception:
            pass


def create_placeholders_blueprint(out_json: Path) -> Blueprint:
    """Create a blueprint with placeholder routes bound to a конкретному out_json path."""
    bp = Blueprint("placeholders_api", __name__)

    @bp.get("/get-placeholders")
    def get_placeholders():
        if not out_json.exists():
            return jsonify({"ok": False, "error": f"{out_json.as_posix()} not found"}), 404
        try:
            data = json.loads(out_json.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return jsonify({"ok": True, "placeholders": data, "note": "out_json is not an object"}), 200
            return jsonify({"ok": True, "placeholders": data, "count": len(data)}), 200
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @bp.post("/update-placeholders")
    def update_placeholders():
        if not request.is_json:
            return jsonify({"ok": False, "error": "Expected JSON body"}), 400

        payload = request.get_json(silent=True) or {}
        placeholders = payload.get("placeholders")

        if not isinstance(placeholders, dict):
            return jsonify({"ok": False, "error": "Field 'placeholders' must be an object"}), 400

        try:
            # merge with existing to preserve keys that UI didn't render
            current: Dict[str, Any] = {}
            if out_json.exists():
                try:
                    loaded = json.loads(out_json.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        current = loaded
                except Exception:
                    current = {}

            # update/merge
            current.update(placeholders)

            _atomic_write_json(out_json, current)
            return jsonify({"ok": True, "count": len(current)}), 200
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    return bp


def register_placeholders_routes(app: Flask, out_json: Optional[Path] = None) -> None:
    """Register placeholder routes on an existing Flask app."""
    if out_json is None:
        base = Path(__file__).parent.resolve()
        out_json = base / "out_txt" / "out_txt.json"
    app.register_blueprint(create_placeholders_blueprint(out_json))


__all__ = ["register_placeholders_routes", "create_placeholders_blueprint"]
