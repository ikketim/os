#!/usr/bin/env python3
"""
WhiteoutProjectOS -- Multi-Bot Web Control Panel
Serves on PORT env var (default 8080). Run as root.
"""
import hashlib
import json
import logging
import os
import pwd
import re
import shutil
import subprocess
import threading
import certifi
import ssl
import urllib.request
import urllib.error
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

def _os_user_ids():
    try:
        pw = pwd.getpwnam(OS_USER)
        return pw.pw_uid, pw.pw_gid
    except KeyError:
        return 0, 0

def _read_json(path: Path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default

_json_lock = threading.Lock()
_procs_lock = threading.Lock()
_registry_lock = threading.Lock()  # Serialises read-modify-write on registry/vault

def _write_json(path: Path, data):
    tmp = str(path) + ".tmp"
    with _json_lock:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
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
    r = subprocess.run(
        ["systemctl", action, f"wp-os-bot@{slot_id}"],
        capture_output=True, text=True, timeout=10, check=False
    )
    if r.returncode != 0:
        logging.warning("systemctl %s wp-os-bot@%s failed (rc=%d): %s",
                        action, slot_id, r.returncode, r.stderr.strip())

def read_token(slot_id: str) -> str:
    try:
        return (BOTS_DIR / slot_id / "token.txt").read_text().strip()
    except Exception:
        return ""

def write_token(slot_id: str, token: str):
    p = BOTS_DIR / slot_id / "token.txt"
    tmp = str(p) + ".tmp"
    with _json_lock:
        with open(tmp, "w") as f:
            f.write(token)
        os.replace(tmp, p)
    os.chmod(p, 0o600)
    uid, gid = _os_user_ids()
    os.chown(p, uid, gid)

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
    if not BOTS_DIR.exists():
        return 0
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
    if not BOTS_DIR.exists():
        return 0
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

def get_discord_bot_name(token: str) -> str:
    try:
	# Force Python to use Mozilla's updated certificates
        secure_context = ssl.create_default_context(cafile=certifi.where())

        req = urllib.request.Request(
            "https://discord.com/api/v10/users/@me",
            headers={
                "Authorization": f"Bot {token}",
                "User-Agent": "WP-OS (wp-os, 1.0)"
            }
        )

        with urllib.request.urlopen(req, timeout=5,context=secure_context) as res:
            data = json.loads(res.read().decode())
            return data.get("username", "")

    except urllib.error.HTTPError as e:
        return ""

    except urllib.error.URLError as e:
        return ""

    except Exception as e:
        return ""

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
    _write_json(meta_f, meta)
    os.chmod(meta_f, 0o644)
    os.chown(meta_f, 0, 0)
    tok_f = slot_dir / "token.txt"
    tok_f.touch()
    os.chmod(tok_f, 0o600)
    uid, gid = _os_user_ids()
    os.chown(tok_f, uid, gid)

    for cmd, timeout in [
        (["systemctl", "daemon-reload"], 30),
        (["systemctl", "enable", f"wp-os-bot@{slot_id}"], 10),
    ]:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        if r.returncode != 0:
            logging.warning("systemctl command failed %s (rc=%d): %s",
                            cmd, r.returncode, r.stderr.strip())

    return jsonify({"ok": True, "slot_id": slot_id, "warnings": warnings})

@app.route("/api/slots/<slot_id>", methods=["DELETE"])
def api_slots_remove(slot_id):
    slot_dir = BOTS_DIR / slot_id
    if not slot_dir.exists():
        return jsonify({"error": "Slot not found"}), 404

    tok = read_token(slot_id)
    if tok:
        with _registry_lock:
            h = sha256t(tok)

            # Remove from registry
            reg = registry_get()
            reg["tokens"].pop(h, None)
            registry_save(reg)

            # Add back to vault (avoid duplicates)
            v = vault_get()
            exists = any(sha256t(e.get("token","")) == h for e in v["tokens"])

            if not exists:
                bot_name = get_discord_bot_name(tok)
                comment = bot_name if bot_name else f"Recovered from deleted slot {slot_id}"

                v["tokens"].append({
                    "token": tok,
                    "comment": comment,
                    "added": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                })
                vault_save(v)

    for action in ("stop", "disable"):
        r = subprocess.run(["systemctl", action, f"wp-os-bot@{slot_id}"],
                           capture_output=True, text=True, timeout=10, check=False)
        if r.returncode != 0:
            logging.warning("systemctl %s wp-os-bot@%s failed (rc=%d): %s",
                            action, slot_id, r.returncode, r.stderr.strip())

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
    if bot_type not in API_GROUPS:
        return jsonify({"error": f"Unknown bot type in meta.json: {bot_type}"}), 400
    log_file = f"/tmp/wp-os-install-{slot_id}.log"
    with _procs_lock:
        if slot_id in _install_procs and _install_procs[slot_id].poll() is None:
            return jsonify({"error": "Install already running"}), 400
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
            _write_json(meta_f, m)
            os.chmod(meta_f, 0o644)  # world-readable: wp-os-user reads this at bot start
        else:
            logging.warning("Install script for slot %s exited with rc=%d", slot_id, proc.returncode)
        with _procs_lock:
            _install_procs.pop(slot_id, None)

    threading.Thread(target=_wait, daemon=True).start()
    return jsonify({"ok": True, "log": log_file})

@app.route("/api/slots/<slot_id>/logs", methods=["GET"])
def api_slot_logs(slot_id):
    if not re.match(r'^[a-zA-Z0-9_-]+$', slot_id):
        return jsonify({"error": "Invalid slot ID"}), 400
    try:
        n = min(int(request.args.get("n", 100)), 500)
    except (ValueError, TypeError):
        n = 100
    try:
        r = subprocess.run(
            ["journalctl", "-u", f"wp-os-bot@{slot_id}",
             "-n", str(n), "--no-pager", "--output=short-iso"],
            capture_output=True, text=True, timeout=10, check=False
        )
        lines = r.stdout.splitlines()
        return jsonify({"lines": lines})
    except Exception as e:
        return jsonify({"error": str(e), "lines": []})

@app.route("/api/slots/<slot_id>/status", methods=["GET"])
def api_slot_status(slot_id):
    slot_dir = BOTS_DIR / slot_id
    if not slot_dir.exists():
        return jsonify({"error": "Slot not found"}), 404
    meta = _read_json(slot_dir / ".meta.json", {})
    with _procs_lock:
        installing = slot_id in _install_procs and _install_procs[slot_id].poll() is None
    return jsonify({
        "installed": meta.get("installed", False),
        "service_status": svc_status(slot_id),
        "installing": installing,
    })

@app.route("/api/slots/<slot_id>/voicechat-config", methods=["GET"])
def api_voicechat_config_get(slot_id):
    slot_dir = BOTS_DIR / slot_id
    if not slot_dir.exists():
        return jsonify({"error": "Slot not found"}), 404
    cfg = _read_json(slot_dir / ".config.json", {})
    return jsonify({
        "client_id": cfg.get("client_id", ""),
        "guild_id": cfg.get("guild_id", ""),
    })

@app.route("/api/slots/<slot_id>/voicechat-config", methods=["POST"])
def api_voicechat_config_set(slot_id):
    slot_dir = BOTS_DIR / slot_id
    if not slot_dir.exists():
        return jsonify({"error": "Slot not found"}), 404
    data = request.json or {}
    client_id = data.get("client_id", "").strip()
    guild_id = data.get("guild_id", "").strip()
    cfg = _read_json(slot_dir / ".config.json", {})
    cfg["client_id"] = client_id
    cfg["guild_id"] = guild_id
    cfg_path = slot_dir / ".config.json"
    _write_json(cfg_path, cfg)
    os.chmod(cfg_path, 0o600)
    uid, gid = _os_user_ids()
    os.chown(cfg_path, uid, gid)  # bot service runs as OS_USERNAME and reads this
    return jsonify({"ok": True})

@app.route("/api/install-log/<slot_id>", methods=["GET"])
def api_install_log(slot_id):
    log_file = f"/tmp/wp-os-install-{slot_id}.log"
    try:
        with open(log_file) as f:
            lines = f.readlines()
        try:
            n = int(request.args.get("n", 100))
        except (ValueError, TypeError):
            n = 100
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

    with _registry_lock:
        h = sha256t(token)
        reg = registry_get()
        existing = reg["tokens"].get(h)
        if existing and existing != slot_id:
            return jsonify({"error": f"Token already in use by slot: {existing}"}), 400

        old = read_token(slot_id)
        if old:
            reg["tokens"].pop(sha256t(old), None)
            # --- VAULT SAFETY ---
            v = vault_get()
            if not any(sha256t(e.get("token","")) == sha256t(old) for e in v["tokens"]):
                bot_name = get_discord_bot_name(old)
                comment = bot_name if bot_name and not bot_name.startswith("Failed:") else f"Overwritten on {slot_id}"
                v["tokens"].append({
                    "token": old,
                    "comment": comment,
                    "added": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                })
                vault_save(v)

        write_token(slot_id, token)
        reg["tokens"][h] = slot_id
        registry_save(reg)
    svc_run("restart", slot_id)
    return jsonify({"ok": True})

@app.route("/api/tokens/clear", methods=["POST"])
def api_token_clear():
    data = request.json or {}
    slot_id = data.get("slot_id", "").strip()
    mode = data.get("mode", "delete")  # "vault" or "delete"

    if not slot_id:
        return jsonify({"error": "slot_id required"}), 400

    slot_dir = BOTS_DIR / slot_id
    if not slot_dir.exists():
        return jsonify({"error": "Slot not found"}), 404

    token = read_token(slot_id)
    if not token:
        return jsonify({"ok": True})

    with _registry_lock:
        h = sha256t(token)

        # Remove from registry
        reg = registry_get()
        reg["tokens"].pop(h, None)
        registry_save(reg)

        # Return to vault if selected
        if mode == "vault":
            v = vault_get()
            exists = any(sha256t(e.get("token","")) == h for e in v["tokens"])

            if not exists:
                bot_name = get_discord_bot_name(token)
                comment = bot_name if bot_name else f"Returned from {slot_id}"

                v["tokens"].append({
                    "token": token,
                    "comment": comment,
                    "added": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                })
                vault_save(v)

        # Always clear slot
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

    with _registry_lock:
        h = sha256t(tok)
        reg = registry_get()
        existing = reg["tokens"].get(h)
        if existing and existing != src:
            return jsonify({"error": f"Token already in use by: {existing}"}), 400

        dst_old = read_token(dst)
        if dst_old:
            reg["tokens"].pop(sha256t(dst_old), None)
            # --- VAULT SAFETY ---
            v = vault_get()
            if not any(sha256t(e.get("token","")) == sha256t(dst_old) for e in v["tokens"]):
                bot_name = get_discord_bot_name(dst_old)
                comment = bot_name if bot_name and not bot_name.startswith("Failed:") else f"Bumped from {dst} by migration"
                v["tokens"].append({
                    "token": dst_old,
                    "comment": comment,
                    "added": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                })
                vault_save(v)

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
    comment = data.get("comment", "").strip()  # <- Explicitly grab the comment from the frontend
    
    # Check for the token FIRST before trying to do anything with it
    if not token:
        return jsonify({"error": "token required"}), 400

    # Auto-fill if empty
    if not comment:
        bot_name = get_discord_bot_name(token)
        if bot_name:
            comment = bot_name

    h = sha256t(token)
    reg = registry_get()
    
    # Check if token is already in use by an active slot
    if h in reg.get("tokens", {}):
        return jsonify({"error": f"Token already in use by slot: {reg['tokens'][h]}"}), 400

    v = vault_get()
    
    # Check if token is already in the vault
    for entry in v.get("tokens", []):
        if sha256t(entry.get("token", "")) == h:
            return jsonify({"error": "Token already in vault"}), 400

    # Add to vault
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

    with _registry_lock:
        h = sha256t(token)
        reg = registry_get()
        existing = reg["tokens"].get(h)
        if existing and existing != slot_id:
            return jsonify({"error": f"Token already in use by slot: {existing}"}), 400

        old = read_token(slot_id)
        if old:
            reg["tokens"].pop(sha256t(old), None)
            # --- VAULT SAFETY ---
            if not any(sha256t(e.get("token","")) == sha256t(old) for e in v["tokens"]):
                bot_name = get_discord_bot_name(old)
                comment = bot_name if bot_name and not bot_name.startswith("Failed:") else f"Bumped from {slot_id} by Vault assignment"
                v["tokens"].append({
                    "token": old,
                    "comment": comment,
                    "added": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                })

        write_token(slot_id, token)
        reg["tokens"][h] = slot_id
        registry_save(reg)

        v["tokens"] = [e for e in v["tokens"] if sha256t(e.get("token","")) != token_hash]
        vault_save(v)

    svc_run("restart", slot_id)
    return jsonify({"ok": True})

@app.route("/api/vault/return", methods=["POST"])
def api_vault_return():
    data = request.json or {}
    slot_id = data.get("slot_id", "").strip()

    if not slot_id:
        return jsonify({"error": "slot_id required"}), 400

    slot_dir = BOTS_DIR / slot_id
    if not slot_dir.exists():
        return jsonify({"error": "Slot not found"}), 404

    token = read_token(slot_id)
    if not token:
        return jsonify({"error": "No token on this slot"}), 400

    with _registry_lock:
        reg = registry_get()
        h = sha256t(token)

        # Remove from registry
        reg["tokens"].pop(h, None)
        registry_save(reg)

        # Add back to vault (avoid duplicates)
        v = vault_get()
        exists = any(sha256t(e.get("token","")) == h for e in v["tokens"])
        if not exists:
            bot_name = get_discord_bot_name(token)
            comment = bot_name if bot_name else f"Returned from {slot_id}"
            
            v["tokens"].append({
                "token": token,
                "comment": comment,
                "added": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            vault_save(v)

        # Clear token from slot
        write_token(slot_id, "")

    svc_run("stop", slot_id)

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

UPDATE_SCRIPT = "/usr/local/bin/wp-os-update.sh"
UPDATE_LOG    = "/tmp/wp-os-update.log"
_update_lock  = threading.Lock()
_update_proc  = None

@app.route("/api/system/update", methods=["POST"])
def api_system_update():
    global _update_proc
    if not Path(UPDATE_SCRIPT).exists():
        return jsonify({"error": "Update script not found"}), 500
    with _update_lock:
        if _update_proc is not None and _update_proc.poll() is None:
            return jsonify({"error": "Update already running"}), 400
        with open(UPDATE_LOG, "w") as lf:
            _update_proc = subprocess.Popen(
                [UPDATE_SCRIPT],
                stdout=lf, stderr=subprocess.STDOUT
            )
    def _wait():
        _update_proc.wait()
        if _update_proc.returncode != 0:
            logging.warning("Update script exited with rc=%d", _update_proc.returncode)
    threading.Thread(target=_wait, daemon=True).start()
    return jsonify({"ok": True, "log": UPDATE_LOG})

@app.route("/api/system/update-log", methods=["GET"])
def api_system_update_log():
    running = _update_proc is not None and _update_proc.poll() is None
    try:
        with open(UPDATE_LOG) as f:
            lines = f.readlines()
        try:
            n = int(request.args.get("n", 100))
        except (ValueError, TypeError):
            n = 100
        return jsonify({"lines": [l.rstrip() for l in lines[-n:]], "running": running})
    except FileNotFoundError:
        return jsonify({"lines": [], "running": running})

# ---------------------------------------------------------------------------
# SPA
# ---------------------------------------------------------------------------
SINGLE_PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WhiteoutProjectOS</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Exo+2:wght@300;400;600;700&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Exo 2',sans-serif;font-weight:300;background:#172643;color:#cdd6f4;min-height:100vh}
.wp-hdr{display:flex;align-items:center;justify-content:space-between;padding:16px 32px;background:#172643;position:relative}
.wp-hdr::after{content:'';position:absolute;bottom:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,#00c8ff,transparent)}
.wp-logo{display:flex;align-items:center;gap:12px}
.wp-logo-icon{width:48px;height:48px;border:1px solid #cdd6f4;border-radius:10px;display:grid;place-items:center;font-size:13px;color:#00c8ff;font-weight:700;font-family:'Share Tech Mono',monospace;letter-spacing:1px}
.wp-logo-text{font-size:17px;font-weight:600;letter-spacing:2px;color:#cdd6f4}
.wp-logo-text span{color:#00c8ff}
.wp-hdr-right{display:flex;align-items:center;gap:8px;font-size:13px;color:#25d79d}
.wp-dot{width:8px;height:8px;border-radius:50%;background:#00e676;box-shadow:0 0 8px #00e676;flex-shrink:0}
.wp-nav{display:flex;gap:4px;padding:14px 32px;background:#172643;border-bottom:1px solid #1e2a3a}
.wp-nav button{padding:8px 22px;border:none;border-radius:6px;cursor:pointer;font-family:'Exo 2',sans-serif;font-size:13px;font-weight:600;letter-spacing:1px;text-transform:uppercase;background:transparent;color:#6c7a96;transition:.15s}
.wp-nav button.active{background:#283d66;color:#cdd6f4;border:1px solid #1e2a3a}
.wp-nav button:hover:not(.active){color:#cdd6f4}
.wp-main{max-width:1100px;margin:0 auto;padding:28px 24px}
.wp-page{display:none}
.wp-page.active{display:block}
.wp-card{background:#283d66;border:1px solid #1e2a3a;border-radius:6px;padding:20px 22px;margin-bottom:16px;position:relative;overflow:hidden}
.wp-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,#00c8ff,transparent)}
.wp-card-title{font-size:11px;font-weight:700;letter-spacing:3px;color:#c2e9ff;text-transform:uppercase;margin-bottom:16px;display:flex;align-items:center;gap:7px}
.wp-ic{color:#00c8ff;font-size:14px}
.wp-pill{font-family:'Share Tech Mono',monospace;font-size:11px;padding:3px 9px;border-radius:20px;letter-spacing:1px}
.wp-pill-active{background:rgba(0,230,118,.14);color:#00e676}
.wp-pill-inactive{background:rgba(255,255,255,.06);color:#6c7a96}
.wp-pill-failed{background:rgba(255,23,68,.14);color:#ff1744}
.wp-pill-activating{background:rgba(255,107,53,.14);color:#ff6b35}
.wp-pill-unknown{background:rgba(255,255,255,.06);color:#6c7a96}
.wp-type-tag{font-size:10px;padding:2px 6px;border-radius:3px;font-family:'Share Tech Mono',monospace;letter-spacing:.5px}
.wp-tag-py{background:rgba(0,200,255,.14);color:#00c8ff}
.wp-tag-js{background:rgba(255,234,0,.12);color:#ffea00}
.wp-tag-ks{background:rgba(255,107,53,.14);color:#ff6b35}
.wp-tag-vc{background:rgba(200,130,255,.14);color:#c882ff}
.wp-token-mask{font-family:'Share Tech Mono',monospace;font-size:11px;color:#6c7a96;margin-left:auto}
.wp-token-mask.has-token{color:#00e676}
.wp-not-installed{background:rgba(255,107,53,.08);border:1px solid rgba(255,107,53,.3);border-radius:6px;padding:10px 14px;margin-bottom:12px;display:flex;align-items:center;gap:10px;font-size:12px;color:#ff9966}
.wp-not-installed span{flex:1}
.wp-btn-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px}
.wp-btn{display:inline-flex;align-items:center;justify-content:center;gap:5px;padding:7px 16px;border:none;border-radius:6px;font-family:'Exo 2',sans-serif;font-size:11px;font-weight:600;letter-spacing:1px;cursor:pointer;text-transform:uppercase;transition:.15s}
.wp-btn-success{background:#00e676;color:#000}
.wp-btn-success:hover{background:#00d068}
.wp-btn-danger{background:#ff1744;color:#fff}
.wp-btn-danger:hover{background:#e0102f}
.wp-btn-warn{background:#ff6b35;color:#000}
.wp-btn-warn:hover{background:#e55c28}
.wp-btn-primary{background:#00c8ff;color:#000}
.wp-btn-primary:hover{background:#00aee0}
.wp-btn-ghost{background:transparent;color:#cdd6f4;border:1px solid #1e2a3a}
.wp-btn-ghost:hover{border-color:#00c8ff;color:#00c8ff}
.wp-btn:disabled{opacity:.45;cursor:not-allowed}
.wp-inp{background:rgba(0,0,0,.35);border:1px solid #1e2a3a;border-radius:6px;color:#cdd6f4;padding:8px 12px;font-family:'Share Tech Mono',monospace;font-size:12px;width:100%}
.wp-inp:focus{outline:none;border-color:#00c8ff}
.wp-inp::placeholder{color:#3c4e6a}
/* Custom Dropdown Wrapper */
.wp-sel-wrap { position: relative; width: 100%; min-width: 140px; user-select: none; }
/* The visible click-box */
.wp-sel-box { background: rgba(0,0,0,.35); border: 1px solid #1e2a3a; border-radius: 6px; color: #cdd6f4; padding: 6px 32px 6px 12px; font-family: 'Share Tech Mono', monospace; font-size: 12px; cursor: pointer; transition: .15s; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%236c7a96' viewBox='0 0 16 16'%3E%3Cpath d='M7.247 11.14 2.451 5.658C1.885 5.013 2.345 4 3.204 4h9.592a1 1 0 0 1 .753 1.659l-4.796 5.48a1 1 0 0 1-1.506 0z'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 12px center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.wp-sel-box:hover { border-color: #00c8ff; }
/* The floating menu */
.wp-sel-menu { position: absolute; top: calc(100% + 4px); left: 0; right: 0; background: #283d66; border: 1px solid #00c8ff; border-radius: 6px; z-index: 100; display: none; overflow: hidden; box-shadow: 0 8px 16px rgba(0,0,0,.5); }
.wp-sel-menu.open { display: block; }
/* The items inside the menu */
.wp-sel-item { padding: 8px 12px; font-family: 'Share Tech Mono', monospace; font-size: 12px; color: #cdd6f4; cursor: pointer; transition: padding .15s, background .15s, color .15s; border-bottom: 1px solid #1e2a3a; }
.wp-sel-item:last-child { border-bottom: none; }
.wp-sel-item:hover { background: rgba(0,200,255,.14); color: #00c8ff; padding-left: 16px; } /* Sleek slide effect */
.wp-form-row{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-top:10px}
.wp-form-group{display:flex;flex-direction:column;gap:5px;min-width:140px}
.wp-form-label{font-size:11px;letter-spacing:2px;color:#6c7a96;text-transform:uppercase}
.wp-banner-err{background:rgba(255,23,68,.1);border:1px solid rgba(255,23,68,.3);color:#ff5a7a;border-radius:6px;padding:10px 14px;margin-bottom:12px;font-size:12px}
.wp-banner-ok{background:rgba(0,230,118,.08);border:1px solid rgba(0,230,118,.25);color:#00e676;border-radius:6px;padding:10px 14px;margin-bottom:12px;font-size:12px}
.wp-banner-warn{background:rgba(255,107,53,.08);border:1px solid rgba(255,107,53,.25);color:#ff9966;border-radius:6px;padding:10px 14px;margin-bottom:12px;font-size:12px}
.wp-log-box{background:rgba(5,8,16,.5);border:1px solid #1e2a3a;border-radius:6px;padding:12px;font-family:'Share Tech Mono',monospace;font-size:11.5px;line-height:1.6;color:#b6e8ff;overflow-y:auto;white-space:pre-wrap;word-break:break-all}
.wp-bot-log{display:none;margin-top:10px}
.wp-bot-log.open{display:block}
.wp-install-log{margin-top:10px}
.wp-table{width:100%;border-collapse:collapse;font-size:12px}
.wp-table th{text-align:left;padding:8px 12px;color:#6c7a96;font-weight:700;letter-spacing:2px;text-transform:uppercase;font-size:10px;border-bottom:1px solid #1e2a3a}
.wp-table td{padding:10px 12px;border-bottom:1px solid rgba(30,42,58,.5);vertical-align:middle}
.wp-table tr:last-child td{border-bottom:none}
.wp-sys-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin-bottom:20px}
.wp-sys-tile{background:rgba(0,0,0,.25);border:1px solid #1e2a3a;border-radius:6px;padding:14px}
.wp-sys-tile .lbl{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#6c7a96;margin-bottom:6px}
.wp-sys-tile .val{font-family:'Share Tech Mono',monospace;font-size:14px;color:#cdd6f4}
.wp-vc-section{margin-top:12px;padding-top:12px;border-top:1px solid #1e2a3a}
.wp-vc-label{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#6c7a96;margin-bottom:10px}
.wp-section-lbl{font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#6c7a96;margin:20px 0 10px;padding-bottom:8px;border-bottom:1px solid #1e2a3a}
.wp-bot-opt{display:flex;align-items:flex-start;gap:10px;padding:10px 13px;border:1px solid #1e2a3a;border-radius:6px;margin-bottom:8px;cursor:pointer;transition:.15s}
.wp-bot-opt:hover{border-color:#00c8ff;background:rgba(0,200,255,.04)}
.wp-bot-radio{width:14px;height:14px;border-radius:50%;border:2px solid #3c4e6a;margin-top:2px;flex-shrink:0;transition:.15s}
.wp-bot-opt.sel .wp-bot-radio{border-color:#00c8ff;background:#00c8ff;box-shadow:0 0 6px #00c8ff}
.wp-bot-opt.sel{border-color:#00c8ff;background:rgba(0,200,255,.06)}
.wp-bot-opt-name{font-size:13px;font-weight:600;color:#cdd6f4}
.wp-bot-opt-desc{font-size:11px;color:#aee5ff;margin-top:3px}
.wp-spin{display:inline-block;width:12px;height:12px;border:2px solid #00c8ff;border-top-color:transparent;border-radius:50%;animation:spin .7s linear infinite;vertical-align:middle}
.wp-modal-overlay {  position:fixed;inset:0;background: rgba(0,0,0,.6);display: none;align-items: center;justify-content: center;z-index: 999; opacity: 0;transition: opacity 0.2s ease;}
.wp-modal-overlay.active {display: flex;opacity: 1;}
.wp-modal {transform: scale(0.95);opacity: 0;transition: all 0.2s ease;}
.wp-modal-overlay.active .wp-modal {transform: scale(1);opacity: 1;}
@keyframes spin{to{transform:rotate(360deg)}}
@media (max-width: 768px) {
  .wp-table thead { display: none; }
  .wp-table tbody { display: block; width: 100%; }
  
  /* The Card Wrapper */
  .wp-table tr { 
    display: flex; 
    flex-wrap: wrap; 
    align-items: center;
    justify-content: space-between; /* <-- This forces the items to stretch across the width! */
    gap: 8px 4px; /* Dialed back the gap so space-between does the heavy lifting */
    margin-bottom: 12px; 
    background: rgba(0,0,0,.15); 
    border: 1px solid #1e2a3a; 
    border-radius: 6px; 
    padding: 12px 14px;
  }
  
  /* Row 1: The Data (Inline) */
  .wp-table td { 
    display: inline-block; 
    padding: 0; 
    border: none; 
  }
  /* Hide the text labels to eliminate dead space */
  .wp-table td::before { display: none !important; }
  
  /* Row 2: Force ONLY the Actions column to drop to the bottom */
  .wp-table td[data-label="Actions"] { 
    width: 100%; 
    margin-top: 6px; 
    padding-top: 12px; 
    border-top: 1px dashed rgba(30,42,58,.5); 
  }
  
  /* Action Button Layout */
  .wp-table td .wp-btn-row { width: 100%; display: flex; flex-wrap: wrap; gap: 8px; }
  
  /* Makes Vault Dropdown full width, and stretches buttons evenly below it */
  .wp-table td .wp-btn-row .wp-sel-wrap { flex: 1 1 100%; }
  .wp-table td .wp-btn-row .wp-btn { flex: 1; justify-content: center; }
}
</style>
</head>
<body>

<div class="wp-hdr">
  <div class="wp-logo">
    <div class="wp-logo-icon">WP</div>
    <div class="wp-logo-text">WhiteoutProject<span>OS</span></div>
  </div>
  <div class="wp-hdr-right">
    <div class="wp-dot"></div>
    <span>Running</span>
  </div>
</div>

<nav class="wp-nav">
  <button class="active" onclick="showTab('bots',this)">⚡ Bots</button>
  <button onclick="showTab('tokens',this)">🔑 Tokens</button>
  <button onclick="showTab('system',this)">🖥 System</button>
</nav>

<div class="wp-main">

<!-- BOTS -->
<div id="bots" class="wp-page active">
  <div id="bots-banners"></div>
  <div id="bots-list"></div>
  <div class="wp-card">
    <div class="wp-card-title"><span class="wp-ic">＋</span> Add Bot Slot</div>
    <p style="font-size:12px;color:#aee5ff;margin-bottom:14px">New slots are <strong style="color:#cdd6f4">not installed automatically</strong> — after creating, click <span style="color:#00c8ff">Install</span> on the slot card to download and set up the bot.</p>
    <div id="add-slot-warn"></div>
    <div class="wp-section-lbl">Choose Bot Type</div>
    <div id="bot-type-picker">
      <div class="wp-bot-opt sel" onclick="pickBotType('wos-py',this)">
        <div class="wp-bot-radio"></div>
        <div>
          <div class="wp-bot-opt-name">Whiteout Survival <span class="wp-type-tag wp-tag-py">PYTHON</span></div>
          <div class="wp-bot-opt-desc">Alliance management, gift codes &amp; event notifications — Python edition</div>
        </div>
      </div>
      <div class="wp-bot-opt" onclick="pickBotType('wos-js',this)">
        <div class="wp-bot-radio"></div>
        <div>
          <div class="wp-bot-opt-name">Whiteout Survival <span class="wp-type-tag wp-tag-js">NODE 22</span></div>
          <div class="wp-bot-opt-desc">JavaScript/TypeScript edition</div>
        </div>
      </div>
      <div class="wp-bot-opt" onclick="pickBotType('kingshot',this)">
        <div class="wp-bot-radio"></div>
        <div>
          <div class="wp-bot-opt-name">Kingshot <span class="wp-type-tag wp-tag-ks">PYTHON</span></div>
          <div class="wp-bot-opt-desc">Alliance management, gift codes &amp; events for Kingshot</div>
        </div>
      </div>
      <div class="wp-bot-opt" onclick="pickBotType('voicechat',this)">
        <div class="wp-bot-radio"></div>
        <div>
          <div class="wp-bot-opt-name">VoiceChat Counter <span class="wp-type-tag wp-tag-vc">NODE 22</span></div>
          <div class="wp-bot-opt-desc">Live voice channel member counter display</div>
        </div>
      </div>
    </div>
    <div class="wp-form-row" style="margin-top:14px">
      <div class="wp-form-group" style="flex:1;min-width:150px">
        <span class="wp-form-label">Slot ID</span>
        <input class="wp-inp" id="new-sid" placeholder="wos-2, kingshot-1…">
      </div>
      <div class="wp-form-group" style="flex:1;min-width:150px">
        <span class="wp-form-label">Display Name</span>
        <input class="wp-inp" id="new-label" placeholder="My Bot">
      </div>
      <button class="wp-btn wp-btn-primary" onclick="createSlot()" style="align-self:flex-end">Create Slot</button>
    </div>
    <input type="hidden" id="new-type" value="wos-py">
  </div>
</div>

<!-- TOKENS -->
<div id="tokens" class="wp-page">
  <div id="tokens-msg"></div>
  <div class="wp-card">
    <div class="wp-card-title"><span class="wp-ic">🔑</span> Active Tokens</div>
    <table class="wp-table">
      <thead><tr><th>Slot</th><th>Type</th><th>Label</th><th>Token</th><th>Actions</th></tr></thead>
      <tbody id="active-tokens-body"></tbody>
    </table>
  </div>
  <div class="wp-card">
    <div class="wp-card-title"><span class="wp-ic">🗄</span> Token Vault</div>
    <p style="font-size:12px;color:#aee5ff;margin-bottom:14px">Store tokens here to assign them to slots later without re-typing.</p>
    <div class="wp-form-row" style="margin-bottom:14px">
      <div class="wp-form-group" style="flex:1;min-width:220px">
        <span class="wp-form-label">Token</span>
        <input class="wp-inp" id="vault-token" type="password" placeholder="Discord bot token">
      </div>
      <div class="wp-form-group" style="flex:1;min-width:160px">
        <span class="wp-form-label">Note (optional)</span>
        <input class="wp-inp" id="vault-comment" placeholder="e.g. main alliance bot">
      </div>
      <button class="wp-btn wp-btn-success" onclick="vaultAdd()" style="align-self:flex-end">Add to Vault</button>
    </div>
    <table class="wp-table">
      <thead><tr><th>Token</th><th>Note</th><th>Added</th><th>Actions</th></tr></thead>
      <tbody id="vault-body"></tbody>
    </table>
  </div>
</div>

<!-- SYSTEM -->
<div id="system" class="wp-page">
  <div class="wp-sys-grid" id="sys-info"></div>
  <div class="wp-card">
    <div class="wp-card-title" style="justify-content:space-between">
      <span><span class="wp-ic">📡</span> Service Status</span>
      <button class="wp-btn wp-btn-warn" style="font-size:10px;padding:5px 12px" onclick="restartAll()">↺ Restart All</button>
    </div>
    <table class="wp-table">
      <thead><tr><th>Slot</th><th>Status</th></tr></thead>
      <tbody id="sys-services"></tbody>
    </table>
  </div>
  <div class="wp-card">
    <div class="wp-card-title"><span class="wp-ic">📋</span> Setup Log</div>
    <div class="wp-log-box" id="sys-log" style="height:200px"></div>
  </div>
  <div class="wp-card">
    <div class="wp-card-title" style="justify-content:space-between">
      <span><span class="wp-ic">⬆</span> OS Update</span>
      <button class="wp-btn wp-btn-primary" id="update-btn" onclick="runUpdate()" style="font-size:10px;padding:5px 12px">Check &amp; Apply Updates</button>
    </div>
    <div id="update-msg"></div>
    <div class="wp-log-box" id="update-log" style="height:200px;display:none;margin-top:10px"></div>
  </div>
</div>

</div><!-- /wp-main -->

<script>
let _slots=[], _allSlots=[], _selBotType='wos-py';

// --- CUSTOM PORTAL DROPDOWN ENGINE ---

// Close menus on click-outside
document.addEventListener('click', (e) => {
  if(!e.target.closest('.wp-sel-wrap') && !e.target.closest('.wp-sel-menu')) {
    closeAllMenus();
  }
});

// Close menus instantly on any scrolling or resizing
window.addEventListener('resize', closeAllMenus);
document.addEventListener('scroll', (e) => {
  if (!e.target.closest('.wp-sel-menu')) closeAllMenus();
}, true);

function closeAllMenus() {
  // Find menus trapped in the body and send them back to their wrappers
  document.querySelectorAll('body > .wp-sel-menu').forEach(m => {
    m.classList.remove('open');
    if (m.originalParent) m.originalParent.appendChild(m);
  });
  document.querySelectorAll('.wp-sel-menu').forEach(m => m.classList.remove('open'));
}

function toggleCustomSel(menuId, boxId) {
  const menu = document.getElementById(menuId);
  const box = document.getElementById(boxId);
  
  if (menu.classList.contains('open')) {
    closeAllMenus();
    return;
  }

  closeAllMenus();

  // Remember its original home before we portal it
  if (!menu.originalParent) {
    menu.originalParent = menu.parentElement;
  }

  // Portal to body
  document.body.appendChild(menu);
  
  // Calculate exact coordinates
  const rect = box.getBoundingClientRect();
  menu.style.position = 'absolute';
  menu.style.top = (rect.bottom + window.scrollY + 4) + 'px';
  menu.style.left = (rect.left + window.scrollX) + 'px';
  menu.style.width = rect.width + 'px';
  menu.style.margin = '0'; 
  menu.style.zIndex = '99999'; // Forces it above the modal!
  
  menu.classList.add('open');
}

function pickCustomSel(menuId, inputId, val, text) {
  document.getElementById('box-' + menuId).textContent = text;
  document.getElementById(inputId).value = val;
  closeAllMenus(); 
}

// --- MODAL CONTROLLERS ---
function customPrompt(title, message, inputType = 'text') {
  return new Promise(resolve => {
    const modal = document.getElementById('custom-prompt-modal');
    document.getElementById('c-prompt-title').textContent = title;
    document.getElementById('c-prompt-msg').innerHTML = message;
    
    const input = document.getElementById('c-prompt-input');
    input.type = inputType;
    input.value = '';
    
    modal.classList.add('active');
    setTimeout(() => input.focus(), 100);

    const cleanup = () => { modal.classList.remove('active'); };

    document.getElementById('c-prompt-ok').onclick = () => { cleanup(); resolve(input.value); };
    document.getElementById('c-prompt-cancel').onclick = () => { cleanup(); resolve(null); };
  });
}

function customConfirm(title, message, isAlert = false, isDanger = false) {
  return new Promise(resolve => {
    const modal = document.getElementById('custom-confirm-modal');
    document.getElementById('c-confirm-title').textContent = title;
    document.getElementById('c-confirm-msg').innerHTML = message;
    document.getElementById('c-confirm-ic').textContent = isAlert ? 'ℹ' : '⚠';
    
    modal.classList.add('active');

    const btnOk = document.getElementById('c-confirm-ok');
    const btnCancel = document.getElementById('c-confirm-cancel');

    btnOk.className = 'wp-btn ' + (isDanger ? 'wp-btn-danger' : 'wp-btn-primary');
    btnOk.textContent = isAlert ? 'Dismiss' : 'Confirm';
    btnCancel.style.display = isAlert ? 'none' : 'inline-flex';

    const cleanup = () => { modal.classList.remove('active'); };

    btnOk.onclick = () => { cleanup(); resolve(true); };
    btnCancel.onclick = () => { cleanup(); resolve(false); };
  });
}

function showTab(id,btn){
  document.querySelectorAll('.wp-page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.wp-nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
  if(id==='bots') loadBots();
  if(id==='tokens') loadTokens();
  if(id==='system') loadSystem();
}

function esc(s){const d=document.createElement('span');d.textContent=s;return d.innerHTML}

function pillClass(s){
  if(s==='active') return 'wp-pill-active';
  if(s==='failed') return 'wp-pill-failed';
  if(s==='activating') return 'wp-pill-activating';
  return 'wp-pill-inactive';
}

function typeTag(t){
  const map={
    'wos-py':'<span class="wp-type-tag wp-tag-py">PYTHON</span>',
    'wos-js':'<span class="wp-type-tag wp-tag-js">NODE 22</span>',
    'kingshot':'<span class="wp-type-tag wp-tag-ks">KINGSHOT</span>',
    'voicechat':'<span class="wp-type-tag wp-tag-vc">VOICECHAT</span>',
  };
  return map[t]||`<span class="wp-type-tag">${esc(t)}</span>`;
}

async function api(method,path,body){
  const opts={method,headers:{'Content-Type':'application/json'}};
  if(body) opts.body=JSON.stringify(body);
  const r=await fetch('/api'+path,opts);
  return r.json();
}

// ---- BOTS ----
async function loadBots(){
  _slots=await api('GET','/slots');
  _allSlots=[..._slots];
  const el=document.getElementById('bots-list');
  if(!_slots.length){
    el.innerHTML='<div class="wp-card" style="color:#6c7a96;text-align:center;padding:32px">No bot slots found.</div>';
    return;
  }
  el.innerHTML=_slots.map(slotCard).join('');
  _slots.filter(s=>s.type==='voicechat').forEach(s=>loadVcConfig(s.slot_id));
  suggestSlotId();
}

function slotCard(s){
  const notInstalled=!s.installed;
  return `<div class="wp-card" id="slot-${s.slot_id}">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px">
    <span style="font-family:'Share Tech Mono',monospace;font-size:15px;color:#00c8ff">${esc(s.slot_id)}</span>
    ${typeTag(s.type)}
    <span class="wp-pill ${pillClass(s.service_status)}">${esc(s.service_status)}</span>
    <span style="color:#aee5ff;font-size:12px">${esc(s.label)}</span>
    <span class="wp-token-mask${s.has_token?' has-token':''}" style="margin-left:auto">${esc(s.token_mask)}</span>
  </div>
  ${notInstalled?`<div class="wp-not-installed">
    <span>&#9888; Not installed — click <strong>Install</strong> to download and set up this bot.</span>
    <button class="wp-btn wp-btn-primary" onclick="installSlot('${s.slot_id}','${s.type}')">&#8681; Install</button>
  </div>`:''}
  <div class="wp-btn-row">
    <button class="wp-btn wp-btn-success" onclick="slotAct('${s.slot_id}','start')">&#9654; Start</button>
    <button class="wp-btn wp-btn-danger" onclick="slotAct('${s.slot_id}','stop')">&#9632; Stop</button>
    <button class="wp-btn wp-btn-warn" onclick="slotAct('${s.slot_id}','restart')">&#8635; Restart</button>
    <button class="wp-btn wp-btn-ghost" onclick="toggleLog('${s.slot_id}',this)">&#128203; Logs</button>
    <button class="wp-btn wp-btn-ghost" style="color:#ff5a7a;border-color:#ff1744" onclick="removeSlot('${s.slot_id}')">&#10005; Remove</button>
  </div>
  ${s.type==='voicechat'?`<div class="wp-vc-section">
    <div class="wp-vc-label">VoiceChat Configuration</div>
    <div class="wp-form-row">
      <div class="wp-form-group" style="flex:1;min-width:160px">
        <span class="wp-form-label">Client ID</span>
        <input class="wp-inp" id="vc-cid-${s.slot_id}" placeholder="Discord Application ID">
      </div>
      <div class="wp-form-group" style="flex:1;min-width:160px">
        <span class="wp-form-label">Guild ID</span>
        <input class="wp-inp" id="vc-gid-${s.slot_id}" placeholder="Discord Server ID">
      </div>
      <button class="wp-btn wp-btn-primary" onclick="saveVcConfig('${s.slot_id}')" style="align-self:flex-end">Save Config</button>
    </div>
    <div id="vc-msg-${s.slot_id}" style="font-size:11px;margin-top:8px"></div>
  </div>`:''}
  <div id="install-log-${s.slot_id}" class="wp-install-log"></div>
  <div id="bot-log-${s.slot_id}" class="wp-bot-log">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;margin-top:10px">
      <span style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#6c7a96">Journal Log &middot; <span id="bot-log-count-${s.slot_id}">&#8212;</span></span>
      <button class="wp-btn wp-btn-ghost" style="font-size:10px;padding:4px 10px" onclick="refreshLog('${s.slot_id}')">&#8635; Refresh</button>
    </div>
    <div class="wp-log-box" id="bot-log-box-${s.slot_id}" style="height:200px"></div>
  </div>
</div>`;
}

async function loadVcConfig(sid){
  const d=await api('GET',`/slots/${sid}/voicechat-config`);
  const cid=document.getElementById(`vc-cid-${sid}`);
  const gid=document.getElementById(`vc-gid-${sid}`);
  if(cid) cid.value=d.client_id||'';
  if(gid) gid.value=d.guild_id||'';
}

async function saveVcConfig(sid){
  const client_id=(document.getElementById(`vc-cid-${sid}`)?.value||'').trim();
  const guild_id=(document.getElementById(`vc-gid-${sid}`)?.value||'').trim();
  const r=await api('POST',`/slots/${sid}/voicechat-config`,{client_id,guild_id});
  const msg=document.getElementById(`vc-msg-${sid}`);
  if(r.error){msg.innerHTML=`<span style="color:#ff5a7a">${esc(r.error)}</span>`;}
  else{msg.innerHTML='<span style="color:#00e676">&#10003; Saved &#8212; restart bot to apply</span>';setTimeout(()=>{if(msg)msg.innerHTML='';},3000);}
}

async function slotAct(sid,action){
  await api('POST',`/slots/${sid}/${action}`);
  loadBots();
}

async function installSlot(sid,type){
  const logEl=document.getElementById(`install-log-${sid}`);
  logEl.innerHTML=`<div style="color:#aee5ff;font-size:12px;margin-top:10px;margin-bottom:6px"><span class="wp-spin"></span> Installing ${esc(type)} &#8212; this may take a few minutes&hellip;</div><div class="wp-log-box" id="ilog-${sid}" style="height:200px"></div>`;
  await api('POST',`/slots/${sid}/install`);
  pollInstallLog(sid);
}

function pollInstallLog(sid){
  const poll=setInterval(async()=>{
    const d=await api('GET',`/install-log/${sid}`);
    const box=document.getElementById(`ilog-${sid}`);
    if(box){box.textContent=d.lines.join('\n');box.scrollTop=box.scrollHeight;}
    const st=await api('GET',`/slots/${sid}/status`);
    if(!st.installing){clearInterval(poll);loadBots();}
  },2000);
}

async function removeSlot(sid){
  const ok = await customConfirm('Remove Slot', `Are you sure you want to remove <strong style="color:#00c8ff">${esc(sid)}</strong>?<br><br><span style="color:#ff5a7a">This permanently deletes all bot files.</span>`, false, true);
  if(!ok) return;
  const r = await api('DELETE',`/slots/${sid}`);
  if(r.error) await customConfirm('Error', r.error, true); else loadBots();
}

function pickBotType(type,el){
  _selBotType=type;
  document.getElementById('new-type').value=type;
  document.querySelectorAll('#bot-type-picker .wp-bot-opt').forEach(o=>o.classList.remove('sel'));
  el.classList.add('sel');
  suggestSlotId();
}

function suggestSlotId(){
  const type=_selBotType;
  const prefix=type==='voicechat'?'vc':type.replace('-py','').replace('-js','');
  const existing=_allSlots.filter(s=>s.slot_id.startsWith(prefix+'-')).length;
  document.getElementById('new-sid').value=`${prefix}-${existing+1}`;
}

async function createSlot(){
  const sid=(document.getElementById('new-sid').value||'').trim();
  const type=document.getElementById('new-type').value;
  const label=(document.getElementById('new-label').value||'').trim();
  const warn=document.getElementById('add-slot-warn');
  if(!sid||!type||!label){warn.innerHTML='<div class="wp-banner-err">Slot ID and Display Name are required.</div>';return;}
  const r=await api('POST','/slots',{slot_id:sid,type,label});
  if(r.error){warn.innerHTML=`<div class="wp-banner-err">${esc(r.error)}</div>`;return;}
  warn.innerHTML='';
  if(r.warnings&&r.warnings.length){
    warn.innerHTML=r.warnings.map(w=>`<div class="wp-banner-warn">&#9888; ${esc(w)}</div>`).join('');
  }
  document.getElementById('new-label').value='';
  loadBots();
}

// ---- TOKENS ----
async function loadTokens(){
  const d=await api('GET','/tokens');
  document.getElementById('active-tokens-body').innerHTML=d.active.map(t=>`<tr>
    <td data-label="Slot" style="font-family:'Share Tech Mono',monospace;color:#00c8ff">${esc(t.slot_id)}</td>
    <td data-label="Type">${typeTag(t.type)}</td>
    <td data-label="Label" style="color:#aee5ff">${esc(t.label)}</td>
    <td data-label="Token" style="font-family:'Share Tech Mono',monospace;color:${t.has_token?'#00e676':'#6c7a96'}">${esc(t.token_mask)}</td>
    <td data-label="Actions"><div class="wp-btn-row" style="gap:6px">
      <button class="wp-btn wp-btn-primary" style="font-size:10px;padding:4px 10px" onclick="setTokenPrompt('${t.slot_id}')">Set Token</button>
      ${t.has_token?`
<button class="wp-btn wp-btn-ghost" style="font-size:10px;padding:4px 10px" onclick="openMoveModal('${t.slot_id}')">MOVE TO...</button>
<button class="wp-btn wp-btn-danger" style="font-size:10px;padding:4px 10px" onclick="openDeleteModal('${t.slot_id}')">DELETE</button>
`:''}
    </div></td>
  </tr>`).join('');

  const vbody=document.getElementById('vault-body');
  if(!d.vault.length){
    vbody.innerHTML='<tr><td colspan="4" style="color:#6c7a96;padding:16px 12px">No tokens in vault. Add one above.</td></tr>';
    return `<tr>
    <td data-label="Token" style="font-family:'Share Tech Mono',monospace;color:#cdd6f4">${esc(v.token_mask)}</td>
    <td data-label="Note" style="color:#aee5ff">${v.comment ? esc(v.comment) : '&#8212;'}</td>
    <td data-label="Added" style="color:#6c7a96;font-size:11px">${esc(v.added.slice(0,10))}</td>
    <td data-label="Actions"><div class="wp-btn-row" style="gap:6px">
      
      <!-- NEW CUSTOM DROPDOWN -->
      <div class="wp-sel-wrap">
        <div class="wp-sel-box" id="box-menu-${v.token_hash}" onclick="toggleCustomSel('menu-${v.token_hash}', this.id)">Select slot...</div>
        <div class="wp-sel-menu" id="menu-${v.token_hash}">
          <div class="wp-sel-item" onclick="pickCustomSel('menu-${v.token_hash}', 'asgn-${v.token_hash}', '', 'Select slot...')">Select slot...</div>
          ${slotOpts}
        </div>
        <input type="hidden" id="asgn-${v.token_hash}" value="">
      </div>
      <!-- END CUSTOM DROPDOWN -->

      <button class="wp-btn wp-btn-primary" style="font-size:10px;padding:4px 10px" onclick="assignVault('${v.token_hash}')">Assign</button>
      <button class="wp-btn wp-btn-danger" style="font-size:10px;padding:4px 10px" onclick="removeVault('${v.token_hash}')">Remove</button>
    </div></td>
  </tr>`;
  }

  vbody.innerHTML=d.vault.map(v=>{
    
    // Generating options INSIDE the loop so it knows the correct token_hash!
    const slotOpts = d.active.map(s => 
      `<div class="wp-sel-item" onclick="pickCustomSel('menu-${v.token_hash}', 'asgn-${v.token_hash}', '${esc(s.slot_id)}', '${esc(s.slot_id)} (${esc(s.type)})')">${esc(s.slot_id)} (${esc(s.type)})</div>`
    ).join('');

    return `<tr>
    <td style="font-family:'Share Tech Mono',monospace;color:#cdd6f4">${esc(v.token_mask)}</td>
    <td style="color:#aee5ff">${v.comment ? esc(v.comment) : '&#8212;'}</td>
    <td style="color:#6c7a96;font-size:11px">${esc(v.added.slice(0,10))}</td>
    <td><div class="wp-btn-row" style="gap:6px">
      
      <!-- NEW CUSTOM DROPDOWN -->
      <div class="wp-sel-wrap">
        <div class="wp-sel-box" id="box-menu-${v.token_hash}" onclick="toggleCustomSel('menu-${v.token_hash}', this.id)">Select slot...</div>
        <div class="wp-sel-menu" id="menu-${v.token_hash}">
          <div class="wp-sel-item" onclick="pickCustomSel('menu-${v.token_hash}', 'asgn-${v.token_hash}', '', 'Select slot...')">Select slot...</div>
          ${slotOpts}
        </div>
        <input type="hidden" id="asgn-${v.token_hash}" value="">
      </div>
      <!-- END CUSTOM DROPDOWN -->

      <button class="wp-btn wp-btn-primary" style="font-size:10px;padding:4px 10px" onclick="assignVault('${v.token_hash}')">Assign</button>
      <button class="wp-btn wp-btn-danger" style="font-size:10px;padding:4px 10px" onclick="removeVault('${v.token_hash}')">Remove</button>
    </div></td>
  </tr>`;
  }).join('');
}

async function setTokenPrompt(sid){
  const tok = await customPrompt('Set Token', `Enter new Discord bot token for slot <strong style="color:#00c8ff">${esc(sid)}</strong>:`, 'password');
  if(!tok) return;
  const r = await api('POST','/tokens/set',{slot_id:sid, token:tok.trim()});
  showMsg(r); loadTokens();
}

let _activeSlotId = null;

// --- MOVE / RETURN MODAL ---
function openMoveModal(slot_id) {
  _activeSlotId = slot_id;
  const slots = _allSlots.filter(s => s.slot_id !== slot_id);
  
  const selHTML = slots.length 
    ? slots.map(s => `<div class="wp-sel-item" onclick="pickCustomSel('menu-move', 'move-dest-slot', '${esc(s.slot_id)}', '${esc(s.slot_id)} (${esc(s.type)})')">${esc(s.slot_id)} (${esc(s.type)})</div>`).join('')
    : `<div class="wp-sel-item" onclick="pickCustomSel('menu-move', 'move-dest-slot', '', '-- No other slots available --')">-- No other slots available --</div>`;
    
  document.getElementById('move-custom-inject').innerHTML = `
    <div class="wp-sel-wrap">
      <div class="wp-sel-box" id="box-menu-move" onclick="toggleCustomSel('menu-move', this.id)">Select destination...</div>
      <div class="wp-sel-menu" id="menu-move">
        ${selHTML}
      </div>
      <input type="hidden" id="move-dest-slot" value="">
    </div>
  `;
    
  document.getElementById('move-modal').classList.add('active');
}

function closeMoveModal() {
  document.getElementById('move-modal').classList.remove('active');
  _activeSlotId = null;
}

async function confirmMove() {
  if (!_activeSlotId) return;
  const dst = document.getElementById('move-dest-slot').value;
  if (!dst) { await customConfirm('Notice', 'No destination slot selected.', true); return; }
  
  const r = await api('POST', '/tokens/migrate', {from_slot: _activeSlotId, to_slot: dst});
  closeMoveModal();
  showMsg(r);
  loadTokens();
}

async function confirmReturn() {
  if (!_activeSlotId) return;
  const r = await api('POST', '/vault/return', {slot_id: _activeSlotId});
  closeMoveModal();
  showMsg(r);
  loadTokens();
}

// --- DELETE MODAL ---
function openDeleteModal(slot_id) {
  _activeSlotId = slot_id;
  document.getElementById('delete-modal').classList.add('active');
}

function closeDeleteModal() {
  document.getElementById('delete-modal').classList.remove('active');
  _activeSlotId = null;
}

async function confirmDelete() {
  if (!_activeSlotId) return;
  const r = await api('POST', '/tokens/clear', { slot_id: _activeSlotId, mode: 'delete' });
  closeDeleteModal();
  showMsg(r);
  loadTokens();
}

// --- GLOBAL MODAL EVENTS ---
window.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.wp-modal-overlay').forEach(modal => {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        closeMoveModal();
        closeDeleteModal();
      }
    });
  });
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeMoveModal();
    closeDeleteModal();
  }
});

async function vaultAdd(){
  const token=(document.getElementById('vault-token').value||'').trim();
  const comment=(document.getElementById('vault-comment').value||'').trim();
  if(!token){showMsg({error:'Token is required'});return;}
  const r=await api('POST','/vault/add',{token,comment});
  showMsg(r);
  document.getElementById('vault-token').value='';
  document.getElementById('vault-comment').value='';
  loadTokens();
}

async function removeVault(h){
  const ok = await customConfirm('Remove Token', 'Are you sure you want to remove this token from the vault?', false, true);
  if(!ok) return;
  const r = await api('DELETE',`/vault/${h}`);
  showMsg(r); loadTokens();
}

async function assignVault(h){
  const sel = document.getElementById(`asgn-${h}`);
  const sid = sel ? sel.value : '';
  if(!sid){ await customConfirm('Notice', 'Please select a destination slot first.', true); return; }
  const r = await api('POST','/vault/assign',{token_hash:h, slot_id:sid});
  showMsg(r); loadTokens();
}

function showMsg(r){
  const el=document.getElementById('tokens-msg');
  if(r.error) el.innerHTML=`<div class="wp-banner-err">&#10005; ${esc(r.error)}</div>`;
  else el.innerHTML=`<div class="wp-banner-ok">&#10003; Done.</div>`;
  setTimeout(()=>el.innerHTML='',3000);
}

// ---- SYSTEM ----
async function loadSystem(){
  const d=await api('GET','/system');
  document.getElementById('sys-info').innerHTML=`
    <div class="wp-sys-tile"><div class="lbl">Hostname</div><div class="val">${esc(d.hostname)}</div></div>
    <div class="wp-sys-tile"><div class="lbl">IP Address</div><div class="val">${esc(d.ip)}</div></div>
    <div class="wp-sys-tile"><div class="lbl">Uptime</div><div class="val">${esc(d.uptime)}</div></div>`;
  document.getElementById('sys-services').innerHTML=d.services.map(s=>
    `<tr>
      <td data-label="Slot" style="font-family:'Share Tech Mono',monospace;color:#00c8ff">${esc(s.slot_id)}</td>
      <td data-label="Status"><span class="wp-pill ${pillClass(s.status)}">${esc(s.status)}</span></td>
    </tr>`
  ).join('')||'<tr><td colspan="2" style="color:#6c7a96;padding:16px 12px">No bot slots found.</td></tr>';
  document.getElementById('sys-log').textContent=d.log_tail.join('\n');
}

async function restartAll(){
  const ok = await customConfirm('Restart All', 'Are you sure you want to restart all running bots?', false, false);
  if(!ok) return;
  const r = await api('POST','/system/restart-all');
  await customConfirm('Success', `Restarted: <br><strong style="color:#00e676">${(r.restarted||[]).join(', ') || 'none'}</strong>`, true);
  loadSystem();
}

let _updatePoll=null;
async function runUpdate(){
  const btn=document.getElementById('update-btn');
  const msg=document.getElementById('update-msg');
  const log=document.getElementById('update-log');
  btn.disabled=true;btn.textContent='Updating\u2026';
  msg.innerHTML='<div class="wp-banner-ok"><span class="wp-spin"></span> Update started &#8212; downloading latest scripts&hellip;</div>';
  log.style.display='block';log.textContent='';
  const r=await api('POST','/system/update');
  if(r.error){
    msg.innerHTML=`<div class="wp-banner-err">&#10005; ${esc(r.error)}</div>`;
    btn.disabled=false;btn.textContent='Check & Apply Updates';return;
  }
  if(_updatePoll) clearInterval(_updatePoll);
  _updatePoll=setInterval(async()=>{
    const d=await api('GET','/system/update-log');
    log.textContent=(d.lines||[]).join('\n');log.scrollTop=log.scrollHeight;
    if(!d.running){
      clearInterval(_updatePoll);_updatePoll=null;
      const ok=(d.lines||[]).some(l=>l.includes('Update complete'));
      const failed=(d.lines||[]).some(l=>l.includes('failed'));
      msg.innerHTML=failed&&!ok
        ?'<div class="wp-banner-err">Update finished with errors &#8212; check the log above.</div>'
        :'<div class="wp-banner-ok">&#10003; Update complete. The web panel will restart shortly &#8212; reload this page in a few seconds.</div>';
      btn.disabled=false;btn.textContent='Check & Apply Updates';
    }
  },2000);
}

// ---- BOT LOGS ----
const _logPolls={};

async function refreshLog(sid){
  const box=document.getElementById(`bot-log-box-${sid}`);
  if(!box) return;
  const d=await api('GET',`/slots/${sid}/logs`);
  const lines=d.lines||[];
  box.textContent=lines.length?lines.join('\n'):'(no log entries yet)';
  box.scrollTop=box.scrollHeight;
  const cnt=document.getElementById(`bot-log-count-${sid}`);
  if(cnt) cnt.textContent=`${lines.length} lines`;
}

function toggleLog(sid,btn){
  const panel=document.getElementById(`bot-log-${sid}`);
  const open=panel.classList.toggle('open');
  btn.textContent=open?'\u{1F4CB} Hide Logs':'\u{1F4CB} Logs';
  if(open){
    refreshLog(sid);
    if(!_logPolls[sid]) _logPolls[sid]=setInterval(()=>refreshLog(sid),4000);
  } else {
    clearInterval(_logPolls[sid]);delete _logPolls[sid];
  }
}

// Init
loadBots();
</script>

<!-- Move / Return Modal -->
<div id="move-modal" class="wp-modal-overlay">
  <div class="wp-modal">
    <div class="wp-card" style="min-width: 300px;">
      <div class="wp-card-title">
        <span class="wp-ic">➡</span> Move Token
      </div>

      <div style="font-size:13px;color:#aee5ff;margin-bottom:16px">
        Where would you like to move this token?
      </div>

      <div class="wp-form-group" style="margin-bottom: 20px;">
        <span class="wp-form-label">Destination Slot</span>
        <div id="move-custom-inject"></div>
      </div>

      <div style="display:flex;flex-direction:column;gap:10px">
        <button class="wp-btn wp-btn-primary" onclick="confirmMove()">
          ➡ Move to Slot
        </button>
        <div style="text-align:center;color:#6c7a96;font-size:11px;margin:2px 0;">OR</div>
        <button class="wp-btn wp-btn-warn" onclick="confirmReturn()">
          ↩ Return to Vault
        </button>
        <button class="wp-btn wp-btn-ghost" onclick="closeMoveModal()" style="margin-top:4px;">
          Cancel
        </button>
      </div>
    </div>
  </div>
</div>

<!-- Delete Modal -->
<div id="delete-modal" class="wp-modal-overlay">
  <div class="wp-modal">
    <div class="wp-card" style="min-width: 300px;">
      <div class="wp-card-title">
        <span class="wp-ic">⚠</span> Delete Token
      </div>

      <div style="font-size:13px;color:#aee5ff;margin-bottom:16px">
        Are you sure you want to permanently delete this token from the slot?<br><br>
        <strong style="color:#ff5a7a">It will NOT be returned to the vault.</strong>
      </div>

      <div style="display:flex;flex-direction:column;gap:10px">
        <button class="wp-btn wp-btn-danger" onclick="confirmDelete()">
          ✖ Delete Anyways
        </button>
        <button class="wp-btn wp-btn-ghost" onclick="closeDeleteModal()">
          Cancel
        </button>
      </div>
    </div>
  </div>
</div>

<!-- Custom Input Modal -->
<div id="custom-prompt-modal" class="wp-modal-overlay">
  <div class="wp-modal">
    <div class="wp-card" style="min-width: 320px;">
      <div class="wp-card-title"><span class="wp-ic">💬</span> <span id="c-prompt-title">Input</span></div>
      <div id="c-prompt-msg" style="font-size:13px;color:#aee5ff;margin-bottom:16px"></div>
      <input class="wp-inp" id="c-prompt-input" style="margin-bottom:16px;">
      <div class="wp-btn-row">
        <button class="wp-btn wp-btn-primary" id="c-prompt-ok">Submit</button>
        <button class="wp-btn wp-btn-ghost" id="c-prompt-cancel">Cancel</button>
      </div>
    </div>
  </div>
</div>

<!-- Custom Confirm/Alert Modal -->
<div id="custom-confirm-modal" class="wp-modal-overlay">
  <div class="wp-modal">
    <div class="wp-card" style="min-width: 320px;">
      <div class="wp-card-title"><span class="wp-ic" id="c-confirm-ic">⚠</span> <span id="c-confirm-title">Confirm</span></div>
      <div id="c-confirm-msg" style="font-size:13px;color:#aee5ff;margin-bottom:20px;line-height:1.5;"></div>
      <div class="wp-btn-row">
        <button class="wp-btn wp-btn-primary" id="c-confirm-ok">Confirm</button>
        <button class="wp-btn wp-btn-ghost" id="c-confirm-cancel">Cancel</button>
      </div>
    </div>
  </div>
</div>

</body>
</html>"""

@app.route("/")
def index():
    return SINGLE_PAGE_HTML, 200, {"Content-Type": "text/html"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
