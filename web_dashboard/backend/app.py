"""
app.py — Backend del dashboard web: Flask + Flask-SocketIO + MQTT bridge.

Expone:
  GET  /              — Sirve el frontend HTML
  POST /api/login     — Autenticación (retorna token de sesión)
  GET  /api/events    — Últimos N eventos de acceso (requiere auth)
  GET  /api/whitelist — Lista de placas autorizadas (requiere auth)
  POST /api/whitelist — Agrega/actualiza placa (requiere admin)
  POST /api/barrier   — Override manual de barrera (requiere operator)
  WS   /ws            — Socket.IO: emite eventos en tiempo real al cliente

Variables de entorno:
    DASHBOARD_PORT          — default: 8080
    DASHBOARD_SECRET_KEY    — clave de sesión Flask (cambiar en producción)
    DB_PATH                 — ruta a la base de datos SQLite
    MQTT_BROKER_HOST        — default: localhost
    MQTT_BROKER_PORT        — default: 1883
    LOG_LEVEL               — default: INFO
"""

import json
import logging
import os
import sys
import threading
import uuid
from functools import wraps
from typing import Any, Dict

import paho.mqtt.client as mqtt
from flask import Flask, jsonify, request, send_from_directory, session
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename

from web_dashboard.backend.auth import authenticate, has_permission

logging.basicConfig(
    level=logging.getLevelName(os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)s [dashboard] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("web-dashboard")

# ── Flask app ─────────────────────────────────────────────────────────────────
_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "../frontend")
app = Flask(__name__, static_folder=_FRONTEND_DIR)
app.secret_key = os.getenv("DASHBOARD_SECRET_KEY", "dev-secret-change-in-production")

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    path="/ws",
)

# ── Base de datos (lazy SQLite) ───────────────────────────────────────────────
_DB_PATH = os.getenv("DB_PATH", "/var/lib/parking/parking.db")

# ── Evidencia de cámara (frames que el vision-service preserva) ────────────────
# Debe coincidir con EVIDENCE_PATH del vision-service (capture.py).
_EVIDENCE_PATH = os.getenv("EVIDENCE_PATH", "/tmp/parking_evidence")


def _get_db():
    import sqlite3
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Auth decorator ────────────────────────────────────────────────────────────
def require_auth(permission: str = "read"):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = session.get("user")
            if not user:
                return jsonify({"error": "No autenticado"}), 401
            if not has_permission(user["role"], permission):
                return jsonify({"error": "Permisos insuficientes"}), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorator


# ── REST API ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(_FRONTEND_DIR, "index.html")


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "")
    password = data.get("password", "")
    user = authenticate(username, password)
    if not user:
        logger.warning("Login fallido | username=%s ip=%s", username, request.remote_addr)
        return jsonify({"error": "Credenciales inválidas"}), 401
    session["user"] = user
    logger.info("Login exitoso | username=%s role=%s", username, user["role"])
    return jsonify({"username": username, "role": user["role"]})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.pop("user", None)
    return jsonify({"ok": True})


@app.route("/api/events")
@require_auth("read")
def get_events():
    limit = min(int(request.args.get("limit", 50)), 200)
    try:
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM access_events ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as exc:
        logger.error("Error consultando eventos: %s", exc)
        return jsonify({"error": "Error de base de datos"}), 500


@app.route("/api/payments")
@require_auth("read")
def get_payments():
    """
    Últimos pagos: qué placas pagaron y cuáles no, según la tabla payment_events.

    Robusto a las dos variantes de esquema del proyecto (schema.sql usa
    created_at/provider_tx_id; el fallback inline usa paid_at/transaction_id):
    se hace SELECT * y se normalizan los campos.
    """
    limit = min(int(request.args.get("limit", 50)), 200)
    try:
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM payment_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            out.append({
                "plate":      d.get("plate"),
                "amount_cop": d.get("amount_cop"),
                "status":     d.get("status"),
                "tx":         d.get("provider_tx_id") or d.get("transaction_id"),
                "created_at": d.get("created_at") or d.get("paid_at") or d.get("processed_at"),
            })
        return jsonify(out)
    except Exception as exc:
        logger.error("Error consultando pagos: %s", exc)
        return jsonify({"error": "Error de base de datos"}), 500


@app.route("/api/captures")
@require_auth("read")
def list_captures():
    """
    Lista las capturas de cámara preservadas por el vision-service, de la más
    reciente a la más antigua. El frontend muestra la última y una galería.
    """
    limit = min(int(request.args.get("limit", 12)), 60)
    try:
        if not os.path.isdir(_EVIDENCE_PATH):
            return jsonify([])
        items = []
        for name in os.listdir(_EVIDENCE_PATH):
            if not name.lower().endswith(".jpg") or name == "latest.jpg":
                continue
            path = os.path.join(_EVIDENCE_PATH, name)
            items.append({"file": name, "mtime": os.path.getmtime(path)})
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return jsonify(items[:limit])
    except Exception as exc:
        logger.error("Error listando capturas: %s", exc)
        return jsonify({"error": "Error leyendo capturas"}), 500


@app.route("/api/captures/<path:filename>")
@require_auth("read")
def serve_capture(filename):
    """Sirve un JPEG de evidencia. Protegido contra path traversal."""
    safe = secure_filename(filename)
    if not safe.lower().endswith(".jpg"):
        return jsonify({"error": "Archivo no permitido"}), 400
    full = os.path.join(_EVIDENCE_PATH, safe)
    if not os.path.isfile(full):
        return jsonify({"error": "No encontrado"}), 404
    return send_from_directory(_EVIDENCE_PATH, safe, mimetype="image/jpeg")


@app.route("/api/whitelist", methods=["GET"])
@require_auth("read")
def get_whitelist():
    try:
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT plate, owner_name, valid_from, valid_until, created_at "
                "FROM whitelist ORDER BY plate"
            ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as exc:
        logger.error("Error consultando whitelist: %s", exc)
        return jsonify({"error": "Error de base de datos"}), 500


@app.route("/api/whitelist", methods=["POST"])
@require_auth("whitelist")
def add_whitelist():
    data = request.get_json(silent=True) or {}
    plate       = data.get("plate", "").upper().strip()
    owner_name  = data.get("owner_name", "")
    valid_from  = data.get("valid_from", "")
    valid_until = data.get("valid_until", "")

    if not plate or not valid_from or not valid_until:
        return jsonify({"error": "plate, valid_from y valid_until son obligatorios"}), 400

    try:
        with _get_db() as conn:
            conn.execute(
                """INSERT INTO whitelist (plate, owner_name, valid_from, valid_until)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(plate) DO UPDATE SET
                       owner_name  = excluded.owner_name,
                       valid_from  = excluded.valid_from,
                       valid_until = excluded.valid_until""",
                (plate, owner_name, valid_from, valid_until),
            )
            conn.commit()
        logger.info("Whitelist actualizado | plate=%s", plate)
        return jsonify({"ok": True, "plate": plate})
    except Exception as exc:
        logger.error("Error actualizando whitelist: %s", exc)
        return jsonify({"error": "Error de base de datos"}), 500


@app.route("/api/barrier", methods=["POST"])
@require_auth("override")
def manual_barrier():
    data   = request.get_json(silent=True) or {}
    action = data.get("action", "").upper()
    if action not in ("OPEN", "CLOSE", "STOP"):
        return jsonify({"error": "Acción debe ser OPEN, CLOSE o STOP"}), 400

    trace_id = str(uuid.uuid4())
    user     = session.get("user", {})
    logger.warning("Override manual | action=%s user=%s trace_id=%s",
                   action, user.get("username"), trace_id)

    _mqtt_publish("parking/commands/barrier", {
        "trace_id":  trace_id,
        "event_type": "barrier_command",
        "source":    "web-dashboard",
        "payload": {
            "action": action,
            "source": f"manual:{user.get('username', 'unknown')}",
        },
    })
    return jsonify({"ok": True, "trace_id": trace_id})


# ── MQTT bridge ────────────────────────────────────────────────────────────────

_mqtt_client: mqtt.Client = None

_TOPICS_TO_FORWARD = [
    "parking/events/#",
    "parking/commands/#",
]


def _mqtt_publish(topic: str, payload: Dict[str, Any]) -> None:
    if _mqtt_client and _mqtt_client.is_connected():
        _mqtt_client.publish(topic, json.dumps(payload))


def _setup_mqtt() -> None:
    global _mqtt_client
    host = os.getenv("MQTT_BROKER_HOST", "localhost")
    port = int(os.getenv("MQTT_BROKER_PORT", "1883"))

    client = mqtt.Client(client_id="web-dashboard")

    def on_connect(c, userdata, flags, rc):
        if rc == 0:
            logger.info("Dashboard conectado a MQTT broker.")
            for topic in _TOPICS_TO_FORWARD:
                c.subscribe(topic)
        else:
            logger.warning("MQTT connect error: rc=%d", rc)

    def on_message(c, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            payload = {"raw": msg.payload.decode("utf-8", errors="replace")}

        socketio.emit("mqtt_event", {
            "topic":   msg.topic,
            "payload": payload,
        })

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(host, port, keepalive=60)
        client.loop_start()
        _mqtt_client = client
        logger.info("MQTT bridge iniciado | broker=%s:%d", host, port)
    except Exception as exc:
        logger.warning("No se pudo conectar al broker MQTT: %s (dashboard sin eventos en tiempo real)", exc)


# ── WebSocket events ──────────────────────────────────────────────────────────

@socketio.on("connect")
def on_ws_connect():
    logger.debug("Cliente WebSocket conectado.")


@socketio.on("disconnect")
def on_ws_disconnect():
    logger.debug("Cliente WebSocket desconectado.")


# ── Entrada ───────────────────────────────────────────────────────────────────

def main() -> None:
    _setup_mqtt()
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    logger.info("Dashboard iniciando en puerto %d...", port)
    socketio.run(app, host="0.0.0.0", port=port, use_reloader=False)


if __name__ == "__main__":
    main()
