#!/usr/bin/env python3
"""
WhiteoutProjectOS -- Multi-Bot Web Control Panel
Serves on PORT env var (default 8080). Run as root.
"""
import fcntl
import hashlib
import json
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONFIG_FILE = "/etc/wp-os/config.env"

def load_config():
    cfg = {}
    try:
        with open(CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    cfg[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return cfg

CFG = load_config()
BOTS_DIR   = Path(CFG.get("BOTS_DIR", "/home/wp-os-user/bots"))
WSERVER    = CFG.get("WEBSERVER_DIR", "/opt/wp-os-webserver")
PORT       = int(os.environ.get("PORT", CFG.get("WEBSERVER_PORT", "8080")))
OS_USER    = CFG.get("OS_USERNAME", "wp-os-user")

REGISTRY   = BOTS_DIR / ".registry.json"
VAULT      = BOTS_DIR / ".vault.json"
INSTALL_SCRIPT = "/usr/local/bin/wp-os-install-bot.sh"

API_GROUPS = {"wos-py": "wos", "wos-js": "wos", "kingshot": "kingshot", "voicechat": "voicechat"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def sha256t(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def mask(token: str) -> str:
    if not token:
        return "[none]"
    return f"[....{token[-4:]}]"

def _read_json(path: Path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default

def _write_json(path: Path, data):
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(data, f, indent=2)
        fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    os.chown(path, 0, 0)

def registry_get() -> dict:
    return _read_json(REGISTRY, {"tokens": {}})

def registry_save(reg: dict):
    _write_json(REGISTRY, reg)

def vault_get() -> dict:
    return _read_json(VAULT, {"tokens": []})

def vault_save(v: dict):
    _write_json(VAULT, v)

def svc_status(slot_id: str) -> str:
    try:
        r = subprocess.run(
            ["systemctl", "is-active", f"wp-os-bot@{slot_id}"],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() or "inactive"
    except Exception:
        return "unknown"

def svc_run(action: str, slot_id: str):
    subprocess.run(
        ["systemctl", action, f"wp-os-bot@{slot_id}"],
        timeout=10, check=False
    )

def read_token(slot_id: str) -> str:
    try:
        return (BOTS_DIR / slot_id / "token.txt").read_text().strip()
    except Exception:
        return ""

def write_token(slot_id: str, token: str):
    p = BOTS_DIR / slot_id / "token.txt"
    p.write_text(token)
    os.chmod(p, 0o600)
    os.chown(p, 0, 0)

def list_slots():
    slots = []
    if not BOTS_DIR.exists():
        return slots
    for d in sorted(BOTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        meta_f = d / ".meta.json"
        if not meta_f.exists():
            continue
        meta = _read_json(meta_f, {})
        slot_id = d.name
        tok = read_token(slot_id)
        slots.append({
            "slot_id": slot_id,
            "type": meta.get("type", "?"),
            "label": meta.get("label", slot_id),
            "installed": meta.get("installed", False),
            "created": meta.get("created", ""),
            "service_status": svc_status(slot_id),
            "has_token": bool(tok),
            "token_mask": mask(tok),
        })
    return slots

def get_wos_count(exclude_slot=None):
    count = 0
    for d in BOTS_DIR.iterdir():
        if not d.is_dir(): continue
        meta_f = d / ".meta.json"
        if not meta_f.exists(): continue
        meta = _read_json(meta_f, {})
        if d.name == exclude_slot: continue
        if meta.get("type") in ("wos-py", "wos-js"):
            count += 1
    return count

def get_type_count(bot_type, exclude_slot=None):
    count = 0
    for d in BOTS_DIR.iterdir():
        if not d.is_dir(): continue
        meta_f = d / ".meta.json"
        if not meta_f.exists(): continue
        meta = _read_json(meta_f, {})
        if d.name == exclude_slot: continue
        if meta.get("type") == bot_type:
            count += 1
    return count

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
_install_procs: dict = {}  # slot_id -> subprocess.Popen

# ---------------------------------------------------------------------------
# Slot API
# ---------------------------------------------------------------------------
@app.route("/api/slots", methods=["GET"])
def api_slots_list():
    return jsonify(list_slots())

@app.route("/api/slots", methods=["POST"])
def api_slots_create():
    data = request.json or {}
    slot_id = data.get("slot_id", "").strip()
    bot_type = data.get("type", "").strip()
    label = data.get("label", slot_id).strip()

    if not slot_id or not bot_type:
        return jsonify({"error": "slot_id and type are required"}), 400
    if not re.match(r'^[a-zA-Z0-9_-]+$', slot_id):
        return jsonify({"error": "slot_id may only contain letters, numbers, hyphens, underscores"}), 400
    if bot_type not in API_GROUPS:
        return jsonify({"error": f"Unknown bot type: {bot_type}"}), 400

    slot_dir = BOTS_DIR / slot_id
    if slot_dir.exists():
        return jsonify({"error": f"Slot already exists: {slot_id}"}), 400

    warnings = []
    if bot_type in ("wos-py", "wos-js") and get_wos_count() > 0:
        warnings.append("WOS bots share the same API — running multiple may cause rate limiting")
    if bot_type == "kingshot" and get_type_count("kingshot") > 0:
        warnings.append("Multiple Kingshot bots share the same API — rate limiting may occur")

    (slot_dir / "app").mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {"type": bot_type, "label": label, "created": now, "installed": False}
    meta_f = slot_dir / ".meta.json"
    meta_f.write_text(json.dumps(meta))
    os.chmod(meta_f, 0o644)
    os.chown(meta_f, 0, 0)
    tok_f = slot_dir / "token.txt"
    tok_f.touch()
    os.chmod(tok_f, 0o600)
    os.chown(tok_f, 0, 0)

    subprocess.run(["systemctl", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "enable", f"wp-os-bot@{slot_id}"], check=False)

    return jsonify({"ok": True, "slot_id": slot_id, "warnings": warnings})

@app.route("/api/slots/<slot_id>", methods=["DELETE"])
def api_slots_remove(slot_id):
    slot_dir = BOTS_DIR / slot_id
    if not slot_dir.exists():
        return jsonify({"error": "Slot not found"}), 404

    tok = read_token(slot_id)
    if tok:
        reg = registry_get()
        h = sha256t(tok)
        reg["tokens"].pop(h, None)
        registry_save(reg)

    subprocess.run(["systemctl", "stop",    f"wp-os-bot@{slot_id}"], check=False)
    subprocess.run(["systemctl", "disable", f"wp-os-bot@{slot_id}"], check=False)

    import shutil
    shutil.rmtree(slot_dir, ignore_errors=True)
    return jsonify({"ok": True})

@app.route("/api/slots/<slot_id>/start", methods=["POST"])
def api_slot_start(slot_id):
    svc_run("start", slot_id)
    return jsonify({"ok": True, "status": svc_status(slot_id)})

@app.route("/api/slots/<slot_id>/stop", methods=["POST"])
def api_slot_stop(slot_id):
    svc_run("stop", slot_id)
    return jsonify({"ok": True, "status": svc_status(slot_id)})

@app.route("/api/slots/<slot_id>/restart", methods=["POST"])
def api_slot_restart(slot_id):
    svc_run("restart", slot_id)
    return jsonify({"ok": True, "status": svc_status(slot_id)})

@app.route("/api/slots/<slot_id>/install", methods=["POST"])
def api_slot_install(slot_id):
    slot_dir = BOTS_DIR / slot_id
    if not slot_dir.exists():
        return jsonify({"error": "Slot not found"}), 404
    meta = _read_json(slot_dir / ".meta.json", {})
    bot_type = meta.get("type")
    if not bot_type:
        return jsonify({"error": "No type in meta.json"}), 400
    if slot_id in _install_procs and _install_procs[slot_id].poll() is None:
        return jsonify({"error": "Install already running"}), 400

    log_file = f"/tmp/wp-os-install-{slot_id}.log"
    with open(log_file, "w") as lf:
        proc = subprocess.Popen(
            [INSTALL_SCRIPT, slot_id, bot_type],
            stdout=lf, stderr=subprocess.STDOUT
        )
    _install_procs[slot_id] = proc

    def _wait():
        proc.wait()
        if proc.returncode == 0:
            meta_f = slot_dir / ".meta.json"
            m = _read_json(meta_f, {})
            m["installed"] = True
            meta_f.write_text(json.dumps(m))
            os.chmod(meta_f, 0o644)
            os.chown(meta_f, 0, 0)

    threading.Thread(target=_wait, daemon=True).start()
    return jsonify({"ok": True, "log": log_file})

@app.route("/api/slots/<slot_id>/status", methods=["GET"])
def api_slot_status(slot_id):
    slot_dir = BOTS_DIR / slot_id
    if not slot_dir.exists():
        return jsonify({"error": "Slot not found"}), 404
    meta = _read_json(slot_dir / ".meta.json", {})
    installing = slot_id in _install_procs and _install_procs[slot_id].poll() is None
    return jsonify({
        "installed": meta.get("installed", False),
        "service_status": svc_status(slot_id),
        "installing": installing,
    })

@app.route("/api/install-log/<slot_id>", methods=["GET"])
def api_install_log(slot_id):
    log_file = f"/tmp/wp-os-install-{slot_id}.log"
    try:
        with open(log_file) as f:
            lines = f.readlines()
        n = int(request.args.get("n", 100))
        return jsonify({"lines": [l.rstrip() for l in lines[-n:]]})
    except FileNotFoundError:
        return jsonify({"lines": []})

# ---------------------------------------------------------------------------
# Token API
# ---------------------------------------------------------------------------
@app.route("/api/tokens", methods=["GET"])
def api_tokens():
    reg = registry_get()
    v = vault_get()
    active = []
    for s in list_slots():
        tok = read_token(s["slot_id"])
        active.append({
            "slot_id": s["slot_id"],
            "type": s["type"],
            "label": s["label"],
            "has_token": bool(tok),
            "token_mask": mask(tok),
        })
    vault_entries = []
    for entry in v.get("tokens", []):
        t = entry.get("token", "")
        vault_entries.append({
            "token_hash": sha256t(t),
            "token_mask": mask(t),
            "comment": entry.get("comment", ""),
            "added": entry.get("added", ""),
        })
    return jsonify({"active": active, "vault": vault_entries})

@app.route("/api/tokens/set", methods=["POST"])
def api_token_set():
    data = request.json or {}
    slot_id = data.get("slot_id", "").strip()
    token = data.get("token", "").strip()
    if not slot_id or not token:
        return jsonify({"error": "slot_id and token required"}), 400
    if not (BOTS_DIR / slot_id).exists():
        return jsonify({"error": "Slot not found"}), 404

    h = sha256t(token)
    reg = registry_get()
    existing = reg["tokens"].get(h)
    if existing and existing != slot_id:
        return jsonify({"error": f"Token already in use by slot: {existing}"}), 400

    old = read_token(slot_id)
    if old:
        reg["tokens"].pop(sha256t(old), None)

    write_token(slot_id, token)
    reg["tokens"][h] = slot_id
    registry_save(reg)
    svc_run("restart", slot_id)
    return jsonify({"ok": True})

@app.route("/api/tokens/clear", methods=["POST"])
def api_token_clear():
    data = request.json or {}
    slot_id = data.get("slot_id", "").strip()
    if not slot_id:
        return jsonify({"error": "slot_id required"}), 400
    old = read_token(slot_id)
    if old:
        reg = registry_get()
        reg["tokens"].pop(sha256t(old), None)
        registry_save(reg)
    write_token(slot_id, "")
    svc_run("stop", slot_id)
    return jsonify({"ok": True})

@app.route("/api/tokens/migrate", methods=["POST"])
def api_token_migrate():
    data = request.json or {}
    src = data.get("from_slot", "").strip()
    dst = data.get("to_slot", "").strip()
    if not src or not dst:
        return jsonify({"error": "from_slot and to_slot required"}), 400
    tok = read_token(src)
    if not tok:
        return jsonify({"error": f"No token on source slot {src}"}), 400
    if not (BOTS_DIR / dst).exists():
        return jsonify({"error": f"Destination slot not found: {dst}"}), 404

    h = sha256t(tok)
    reg = registry_get()
    existing = reg["tokens"].get(h)
    if existing and existing != src:
        return jsonify({"error": f"Token already in use by: {existing}"}), 400

    dst_old = read_token(dst)
    if dst_old:
        reg["tokens"].pop(sha256t(dst_old), None)

    write_token(dst, tok)
    reg["tokens"][h] = dst
    write_token(src, "")
    registry_save(reg)
    svc_run("stop", src)
    svc_run("restart", dst)
    return jsonify({"ok": True})

@app.route("/api/vault/add", methods=["POST"])
def api_vault_add():
    data = request.json or {}
    token = data.get("token", "").strip()
    comment = data.get("comment", "").strip()
    if not token:
        return jsonify({"error": "token required"}), 400

    h = sha256t(token)
    reg = registry_get()
    if h in reg["tokens"]:
        return jsonify({"error": f"Token already in use by slot: {reg['tokens'][h]}"}), 400

    v = vault_get()
    for entry in v["tokens"]:
        if sha256t(entry.get("token", "")) == h:
            return jsonify({"error": "Token already in vault"}), 400

    v["tokens"].append({
        "token": token,
        "comment": comment,
        "added": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    vault_save(v)
    return jsonify({"ok": True})

@app.route("/api/vault/<token_hash>", methods=["DELETE"])
def api_vault_remove(token_hash):
    v = vault_get()
    before = len(v["tokens"])
    v["tokens"] = [e for e in v["tokens"] if sha256t(e.get("token","")) != token_hash]
    if len(v["tokens"]) == before:
        return jsonify({"error": "Token not found in vault"}), 404
    vault_save(v)
    return jsonify({"ok": True})

@app.route("/api/vault/assign", methods=["POST"])
def api_vault_assign():
    data = request.json or {}
    token_hash = data.get("token_hash", "").strip()
    slot_id = data.get("slot_id", "").strip()
    if not token_hash or not slot_id:
        return jsonify({"error": "token_hash and slot_id required"}), 400
    if not (BOTS_DIR / slot_id).exists():
        return jsonify({"error": "Slot not found"}), 404

    v = vault_get()
    token = None
    for entry in v["tokens"]:
        if sha256t(entry.get("token","")) == token_hash:
            token = entry["token"]
            break
    if not token:
        return jsonify({"error": "Token not found in vault"}), 404

    h = sha256t(token)
    reg = registry_get()
    existing = reg["tokens"].get(h)
    if existing and existing != slot_id:
        return jsonify({"error": f"Token already in use by slot: {existing}"}), 400

    old = read_token(slot_id)
    if old:
        reg["tokens"].pop(sha256t(old), None)

    write_token(slot_id, token)
    reg["tokens"][h] = slot_id
    registry_save(reg)

    v["tokens"] = [e for e in v["tokens"] if sha256t(e.get("token","")) != token_hash]
    vault_save(v)

    svc_run("restart", slot_id)
    return jsonify({"ok": True})

# ---------------------------------------------------------------------------
# System API
# ---------------------------------------------------------------------------
@app.route("/api/system", methods=["GET"])
def api_system():
    import socket
    hostname = socket.gethostname()
    try:
        ip = socket.gethostbyname(hostname)
    except Exception:
        ip = "unknown"

    try:
        uptime_s = float(Path("/proc/uptime").read_text().split()[0])
        h, rem = divmod(int(uptime_s), 3600)
        m, s = divmod(rem, 60)
        uptime = f"{h}h {m}m {s}s"
    except Exception:
        uptime = "unknown"

    try:
        log_lines = Path("/var/log/wp-os-setup.log").read_text().splitlines()[-50:]
    except Exception:
        log_lines = []

    services = []
    for d in sorted(BOTS_DIR.iterdir()) if BOTS_DIR.exists() else []:
        if d.is_dir() and (d / ".meta.json").exists():
            services.append({
                "slot_id": d.name,
                "status": svc_status(d.name),
            })

    return jsonify({
        "hostname": hostname,
        "ip": ip,
        "uptime": uptime,
        "services": services,
        "log_tail": log_lines,
    })

@app.route("/api/system/restart-all", methods=["POST"])
def api_restart_all():
    restarted = []
    if BOTS_DIR.exists():
        for d in BOTS_DIR.iterdir():
            if d.is_dir() and (d / ".meta.json").exists():
                svc_run("restart", d.name)
                restarted.append(d.name)
    return jsonify({"ok": True, "restarted": restarted})

# ---------------------------------------------------------------------------
# SPA
# ---------------------------------------------------------------------------
SINGLE_PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WhiteoutProjectOS Control Panel</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0f1117;color:#e2e8f0;min-height:100vh}
header{background:#1a1d27;border-bottom:1px solid #2d3148;padding:14px 24px;display:flex;align-items:center;gap:16px}
header h1{font-size:1.1rem;font-weight:600;color:#7c85f5}
header span{font-size:.8rem;color:#64748b}
nav{display:flex;gap:4px;padding:12px 24px;background:#13151f;border-bottom:1px solid #1e2135}
nav button{padding:7px 18px;border:none;border-radius:6px;cursor:pointer;font-size:.9rem;background:transparent;color:#94a3b8;transition:.15s}
nav button.active{background:#2d3148;color:#e2e8f0}
nav button:hover:not(.active){background:#1e2135;color:#e2e8f0}
.page{display:none;padding:24px;max-width:1100px}
.page.active{display:block}
h2{font-size:1rem;font-weight:600;margin-bottom:16px;color:#c7d2fe}
.card{background:#1a1d27;border:1px solid #2d3148;border-radius:10px;padding:18px;margin-bottom:16px}
.slot-header{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.slot-id{font-weight:700;font-size:.95rem}
.badge{padding:2px 8px;border-radius:4px;font-size:.75rem;font-weight:600}
.badge-wos-py{background:#1e3a5f;color:#60a5fa}
.badge-wos-js{background:#1a3a2a;color:#4ade80}
.badge-kingshot{background:#3a1a1a;color:#f87171}
.badge-voicechat{background:#2a1a3a;color:#c084fc}
.badge-active{background:#14532d;color:#4ade80}
.badge-inactive{background:#1c1c1c;color:#6b7280}
.badge-failed{background:#450a0a;color:#f87171}
.badge-unknown{background:#1c1c1c;color:#6b7280}
.slot-label{color:#94a3b8;font-size:.9rem}
.slot-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
button{padding:6px 14px;border:none;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:500;transition:.15s}
.btn-primary{background:#4f46e5;color:#fff}
.btn-primary:hover{background:#4338ca}
.btn-success{background:#16a34a;color:#fff}
.btn-success:hover{background:#15803d}
.btn-danger{background:#dc2626;color:#fff}
.btn-danger:hover{background:#b91c1c}
.btn-warning{background:#d97706;color:#fff}
.btn-warning:hover{background:#b45309}
.btn-secondary{background:#374151;color:#e2e8f0}
.btn-secondary:hover{background:#4b5563}
.btn-sm{padding:4px 10px;font-size:.78rem}
.warn-banner{background:#422006;border:1px solid #854d0e;color:#fcd34d;border-radius:8px;padding:10px 14px;margin-bottom:14px;font-size:.85rem}
.err-banner{background:#450a0a;border:1px solid #991b1b;color:#fca5a5;border-radius:8px;padding:10px 14px;margin-bottom:14px;font-size:.85rem}
.ok-banner{background:#052e16;border:1px solid #166534;color:#86efac;border-radius:8px;padding:10px 14px;margin-bottom:14px;font-size:.85rem}
form{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-top:12px}
label{font-size:.82rem;color:#94a3b8;display:flex;flex-direction:column;gap:4px}
input,select,textarea{background:#0f1117;border:1px solid #2d3148;border-radius:6px;color:#e2e8f0;padding:7px 10px;font-size:.88rem;min-width:160px}
input:focus,select:focus,textarea:focus{outline:none;border-color:#4f46e5}
table{width:100%;border-collapse:collapse;font-size:.88rem}
th{text-align:left;padding:8px 12px;color:#64748b;font-weight:500;border-bottom:1px solid #2d3148}
td{padding:8px 12px;border-bottom:1px solid #1e2135}
tr:last-child td{border-bottom:none}
.log-box{background:#070a0f;border:1px solid #1e2135;border-radius:8px;padding:12px;font-family:'Courier New',monospace;font-size:.78rem;color:#94a3b8;max-height:340px;overflow-y:auto;white-space:pre-wrap;word-break:break-all}
.install-log{margin-top:10px}
.spinner{display:inline-block;width:12px;height:12px;border:2px solid #4f46e5;border-top-color:transparent;border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.sys-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:20px}
.sys-card{background:#13151f;border:1px solid #2d3148;border-radius:8px;padding:14px}
.sys-card .label{font-size:.78rem;color:#64748b;margin-bottom:4px}
.sys-card .value{font-size:1rem;font-weight:600;color:#e2e8f0}
.section-title{font-size:.9rem;font-weight:600;color:#94a3b8;margin:18px 0 10px;border-bottom:1px solid #2d3148;padding-bottom:6px}
</style>
</head>
<body>
<header>
  <h1>WhiteoutProjectOS</h1>
  <span>Control Panel</span>
</header>
<nav>
  <button class="active" onclick="showTab('bots',this)">Bots</button>
  <button onclick="showTab('tokens',this)">Tokens</button>
  <button onclick="showTab('system',this)">System</button>
</nav>

<div id="bots" class="page active">
  <h2>Bot Slots</h2>
  <div id="bots-banners"></div>
  <div id="bots-list"></div>
  <div class="card">
    <div style="font-weight:600;margin-bottom:12px;color:#c7d2fe">Add New Slot</div>
    <div id="add-slot-warn"></div>
    <form id="add-slot-form" onsubmit="createSlot(event)">
      <label>Slot ID<input id="new-sid" placeholder="wos-2, kingshot-1…" required></label>
      <label>Bot Type
        <select id="new-type" onchange="suggestSlotId()">
          <option value="wos-py">WOS Python (wos-py)</option>
          <option value="wos-js">WOS JavaScript (wos-js)</option>
          <option value="kingshot">Kingshot</option>
          <option value="voicechat">VoiceChat Counter</option>
        </select>
      </label>
      <label>Label<input id="new-label" placeholder="My Bot" required></label>
      <button type="submit" class="btn-primary">Create Slot</button>
    </form>
  </div>
</div>

<div id="tokens" class="page">
  <h2>Token Management</h2>
  <div id="tokens-msg"></div>
  <div class="section-title">Active Tokens</div>
  <div class="card"><table id="active-tokens-table">
    <thead><tr><th>Slot</th><th>Type</th><th>Label</th><th>Token</th><th>Actions</th></tr></thead>
    <tbody id="active-tokens-body"></tbody>
  </table></div>
  <div class="section-title">Token Vault</div>
  <div class="card">
    <form id="vault-add-form" onsubmit="vaultAdd(event)" style="margin-bottom:16px">
      <label>Token<input id="vault-token" type="password" placeholder="Discord bot token" required></label>
      <label>Comment<input id="vault-comment" placeholder="Optional note"></label>
      <button type="submit" class="btn-success">Add to Vault</button>
    </form>
    <table id="vault-table">
      <thead><tr><th>Token</th><th>Comment</th><th>Added</th><th>Actions</th></tr></thead>
      <tbody id="vault-body"></tbody>
    </table>
  </div>
</div>

<div id="system" class="page">
  <h2>System</h2>
  <div class="sys-grid" id="sys-info"></div>
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
    <div class="section-title" style="margin:0">Service Status</div>
    <button class="btn-warning btn-sm" onclick="restartAll()">Restart All Bots</button>
  </div>
  <div class="card"><table>
    <thead><tr><th>Slot</th><th>Status</th></tr></thead>
    <tbody id="sys-services"></tbody>
  </table></div>
  <div class="section-title">Setup Log (last 50 lines)</div>
  <div class="log-box" id="sys-log"></div>
</div>

<script>
let _slots=[], _allSlots=[];

function showTab(id,btn){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
  if(id==='bots') loadBots();
  if(id==='tokens') loadTokens();
  if(id==='system') loadSystem();
}

function badge(cls,text){return `<span class="badge badge-${cls}">${text}</span>`}
function typeBadge(t){return badge(t,t)}
function statusBadge(s){return badge(s,s)}

async function api(method,path,body){
  const opts={method,headers:{'Content-Type':'application/json'}};
  if(body) opts.body=JSON.stringify(body);
  const r=await fetch('/api'+path,opts);
  return r.json();
}

async function loadBots(){
  _slots=await api('GET','/slots');
  _allSlots=[..._slots];
  const el=document.getElementById('bots-list');
  if(!_slots.length){el.innerHTML='<div class="card" style="color:#64748b">No slots yet.</div>';return;}
  el.innerHTML=_slots.map(s=>slotCard(s)).join('');
}

function slotCard(s){
  const installBtn=!s.installed?`<button class="btn-primary btn-sm" onclick="installSlot('${s.slot_id}','${s.type}')">Install</button>`:'';
  return `<div class="card" id="slot-${s.slot_id}">
  <div class="slot-header">
    <span class="slot-id">${s.slot_id}</span>
    ${typeBadge(s.type)}
    ${statusBadge(s.service_status)}
    <span class="slot-label">${s.label}</span>
    <span style="margin-left:auto;font-size:.78rem;color:${s.has_token?'#4ade80':'#ef4444'}">${s.token_mask}</span>
  </div>
  <div class="slot-actions">
    <button class="btn-success btn-sm" onclick="slotAct('${s.slot_id}','start')">Start</button>
    <button class="btn-secondary btn-sm" onclick="slotAct('${s.slot_id}','stop')">Stop</button>
    <button class="btn-warning btn-sm" onclick="slotAct('${s.slot_id}','restart')">Restart</button>
    ${installBtn}
    <button class="btn-danger btn-sm" onclick="removeSlot('${s.slot_id}')">Remove</button>
  </div>
  <div id="install-log-${s.slot_id}" class="install-log"></div>
</div>`;
}

async function slotAct(sid,action){
  await api('POST',`/slots/${sid}/${action}`);
  loadBots();
}

async function installSlot(sid,type){
  const logEl=document.getElementById(`install-log-${sid}`);
  logEl.innerHTML=`<div style="color:#94a3b8;font-size:.82rem;margin-top:8px"><span class="spinner"></span> Installing ${type}…</div><div class="log-box" id="ilog-${sid}"></div>`;
  await api('POST',`/slots/${sid}/install`);
  pollInstallLog(sid);
}

function pollInstallLog(sid){
  const poll=setInterval(async()=>{
    const d=await api('GET',`/install-log/${sid}`);
    const box=document.getElementById(`ilog-${sid}`);
    if(box) box.textContent=d.lines.join('\n');
    const st=await api('GET',`/slots/${sid}/status`);
    if(!st.installing){
      clearInterval(poll);
      loadBots();
    }
  },2000);
}

async function removeSlot(sid){
  if(!confirm(`Remove slot ${sid}? This deletes all bot files.`)) return;
  const r=await api('DELETE',`/slots/${sid}`);
  if(r.error) alert(r.error); else loadBots();
}

async function createSlot(e){
  e.preventDefault();
  const sid=document.getElementById('new-sid').value.trim();
  const type=document.getElementById('new-type').value;
  const label=document.getElementById('new-label').value.trim();
  const r=await api('POST','/slots',{slot_id:sid,type,label});
  const warn=document.getElementById('add-slot-warn');
  if(r.error){warn.innerHTML=`<div class="err-banner">${r.error}</div>`;return;}
  warn.innerHTML='';
  if(r.warnings&&r.warnings.length){
    warn.innerHTML=r.warnings.map(w=>`<div class="warn-banner">⚠ ${w}</div>`).join('');
  }
  document.getElementById('add-slot-form').reset();
  loadBots();
}

function suggestSlotId(){
  const type=document.getElementById('new-type').value;
  const prefix=type==='voicechat'?'vc':type.replace('-py','').replace('-js','');
  const existing=_allSlots.filter(s=>s.type===type||s.slot_id.startsWith(prefix+'-')).length;
  document.getElementById('new-sid').value=`${prefix}-${existing+1}`;
}

async function loadTokens(){
  const d=await api('GET','/tokens');
  const msg=document.getElementById('tokens-msg');
  // Active tokens
  const tbody=document.getElementById('active-tokens-body');
  tbody.innerHTML=d.active.map(t=>`<tr>
    <td>${t.slot_id}</td>
    <td>${typeBadge(t.type)}</td>
    <td>${t.label}</td>
    <td style="font-family:monospace;color:${t.has_token?'#4ade80':'#6b7280'}">${t.token_mask}</td>
    <td>
      <button class="btn-primary btn-sm" onclick="setTokenPrompt('${t.slot_id}')">Set</button>
      ${t.has_token?`<button class="btn-secondary btn-sm" onclick="migratePrompt('${t.slot_id}')">Move to…</button>
      <button class="btn-danger btn-sm" onclick="clearToken('${t.slot_id}')">Clear</button>`:''}
    </td>
  </tr>`).join('');

  // Vault
  const vbody=document.getElementById('vault-body');
  if(!d.vault.length){vbody.innerHTML='<tr><td colspan="4" style="color:#6b7280">No tokens in vault.</td></tr>';return;}
  const slotOpts=d.active.map(s=>`<option value="${s.slot_id}">${s.slot_id} (${s.type})</option>`).join('');
  vbody.innerHTML=d.vault.map(v=>`<tr>
    <td style="font-family:monospace">${v.token_mask}</td>
    <td>${v.comment||'—'}</td>
    <td style="font-size:.78rem;color:#64748b">${v.added.slice(0,10)}</td>
    <td>
      <select id="asgn-${v.token_hash}" style="min-width:120px"><option value="">Select slot…</option>${slotOpts}</select>
      <button class="btn-primary btn-sm" onclick="assignVault('${v.token_hash}')">Assign</button>
      <button class="btn-danger btn-sm" onclick="removeVault('${v.token_hash}')">Remove</button>
    </td>
  </tr>`).join('');
}

async function setTokenPrompt(sid){
  const tok=prompt(`Enter new token for slot ${sid}:`);
  if(!tok) return;
  const r=await api('POST','/tokens/set',{slot_id:sid,token:tok});
  showMsg(r);
  loadTokens();
}

async function clearToken(sid){
  if(!confirm(`Clear token for ${sid}? The bot will stop.`)) return;
  const r=await api('POST','/tokens/clear',{slot_id:sid});
  showMsg(r);
  loadTokens();
}

async function migratePrompt(src){
  const slots=_allSlots.filter(s=>s.slot_id!==src);
  if(!slots.length){alert('No other slots to migrate to.');return;}
  const dst=prompt(`Migrate token from ${src} to which slot?\n${slots.map(s=>s.slot_id).join(', ')}`);
  if(!dst) return;
  const r=await api('POST','/tokens/migrate',{from_slot:src,to_slot:dst});
  showMsg(r);
  loadTokens();
}

async function vaultAdd(e){
  e.preventDefault();
  const token=document.getElementById('vault-token').value.trim();
  const comment=document.getElementById('vault-comment').value.trim();
  const r=await api('POST','/vault/add',{token,comment});
  showMsg(r);
  document.getElementById('vault-add-form').reset();
  loadTokens();
}

async function removeVault(h){
  if(!confirm('Remove this token from vault?')) return;
  const r=await api('DELETE',`/vault/${h}`);
  showMsg(r);
  loadTokens();
}

async function assignVault(h){
  const sel=document.getElementById(`asgn-${h}`);
  const sid=sel.value;
  if(!sid){alert('Select a slot first.');return;}
  const r=await api('POST','/vault/assign',{token_hash:h,slot_id:sid});
  showMsg(r);
  loadTokens();
}

function showMsg(r){
  const el=document.getElementById('tokens-msg');
  if(r.error) el.innerHTML=`<div class="err-banner">${r.error}</div>`;
  else el.innerHTML=`<div class="ok-banner">Done.</div>`;
  setTimeout(()=>el.innerHTML='',3000);
}

async function loadSystem(){
  const d=await api('GET','/system');
  document.getElementById('sys-info').innerHTML=`
    <div class="sys-card"><div class="label">Hostname</div><div class="value">${d.hostname}</div></div>
    <div class="sys-card"><div class="label">IP Address</div><div class="value">${d.ip}</div></div>
    <div class="sys-card"><div class="label">Uptime</div><div class="value">${d.uptime}</div></div>`;
  document.getElementById('sys-services').innerHTML=d.services.map(s=>
    `<tr><td>${s.slot_id}</td><td>${statusBadge(s.status)}</td></tr>`
  ).join('')||'<tr><td colspan="2" style="color:#6b7280">No bot slots found.</td></tr>';
  document.getElementById('sys-log').textContent=d.log_tail.join('\n');
}

async function restartAll(){
  const r=await api('POST','/system/restart-all');
  alert(`Restarted: ${(r.restarted||[]).join(', ')||'none'}`);
  loadSystem();
}

// Init
loadBots();
suggestSlotId();
</script>
</body>
</html>"""

@app.route("/")
def index():
    return SINGLE_PAGE_HTML, 200, {"Content-Type": "text/html"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
