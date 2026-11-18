"""Web-UI fuer ps5-longshot-builder: Stufen starten, Log mitlesen, Release und Konsole waehlen, Stand anzeigen.
Nur Python-Standardbibliothek."""
import glob
import http.server
import json
import os
import re
import signal
import subprocess
import threading
import time
import urllib.parse
import urllib.request

CONFIG = os.environ.get("CONFIG_DIR", "/config")
LOGS = os.path.join(CONFIG, "logs")
PORT = int(os.environ.get("WEBUI_PORT", "8486"))
OUT = os.environ.get("OUT_DIR", "/output")
# Die Projekte, wie scripts/build.sh sie kennt: Repository, Name der Builder-AppImage, Title, eigener Ordner unter /config
PROJECTS = {
    "longshot": {"label": "Longshot (heydemoura/PS5_Longshot)", "repo": os.environ.get("LONGSHOT_REPO", "heydemoura/PS5_Longshot"),
                 "appimage": "LongshotPS5Builder", "title_id": os.environ.get("TITLE_ID", "PPSA99025"), "state": CONFIG,
                 "ref_env": "LONGSHOT_REF"},
    "heylisten": {"label": "HeyListen (cosmicflow2512/PS5_HeyListen, experimentell)",
                  "repo": os.environ.get("HEYLISTEN_REPO", "cosmicflow2512/PS5_HeyListen"), "appimage": "HeyListenPS5Builder",
                  "title_id": "PPSA99026", "state": os.path.join(CONFIG, "heylisten"), "ref_env": "HEYLISTEN_REF"},
}
PROJECT_FILE = os.path.join(CONFIG, "project")
STAGES = ("check", "all", "update", "build", "deploy", "saves-status")
SAVE_TITLES = ("longshot", "heylisten")   # (scripts/saves.py TITLES)
SAVES_DIR = os.path.join(CONFIG, "saves")
BACKUP_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z]+-[a-z-]+$")
MODELS = {"pro": "PS5 Pro", "base": "PS5 / PS5 Slim"}
# Die 16 Sprachen des Spiels (host/nn_applet.c von PS5_Longshot), wie build.sh sie in language.txt schreibt
LANGUAGES = {"de": "Deutsch", "en-US": "English (US)", "en-GB": "English (UK)", "fr": "Français", "fr-CA": "Français (Canada)",
             "it": "Italiano", "es": "Español", "es-419": "Español (Latinoamérica)", "pt-BR": "Português (Brasil)",
             "nl": "Nederlands", "pl": "Polski", "ru": "Русский", "ja": "日本語", "ko": "한국어", "zh-Hans": "简体中文",
             "zh-Hant": "繁體中文"}
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_FILE = os.path.join(CONFIG, "model")
LANGUAGE_FILE = os.path.join(CONFIG, "language")
TAG_RE = re.compile(r"^[A-Za-z0-9._+-]{1,80}$")
RELEASE_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z]+)\.?(\d+)?)?$")
releases_cache = {}

state = {"proc": None, "stage": None, "started": None, "ended": None, "code": None, "log": None}
lock = threading.Lock()


def running():
    return bool(state["proc"] and state["proc"].poll() is None)


def start(stage, env=None):
    with lock:
        if running():
            return False, "es laeuft schon: " + state["stage"]
        os.makedirs(LOGS, exist_ok=True)
        path = os.path.join(LOGS, time.strftime("%Y%m%d-%H%M%S") + "-" + stage + ".log")
        fh = open(path, "wb")
        proc = subprocess.Popen(["bash", "/app/scripts/build.sh", stage], stdout=fh, stderr=subprocess.STDOUT,
                                env=dict(os.environ, **(env or {})),
                                start_new_session=True)
        state.update(proc=proc, stage=stage, started=time.time(), ended=None, code=None, log=path)
        latest = os.path.join(LOGS, "latest.log")
        try:
            if os.path.lexists(latest):
                os.remove(latest)
            os.symlink(os.path.basename(path), latest)
        except OSError:
            pass

        def wait():
            code = proc.wait()
            fh.close()
            with lock:
                state.update(code=code, ended=time.time())
        threading.Thread(target=wait, daemon=True).start()
        return True, path


def stop():
    with lock:
        p = state["proc"]
        if p and p.poll() is None:
            os.killpg(p.pid, signal.SIGTERM)
            return True
    return False


def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def read_line(path):
    try:
        with open(path) as fh:
            return fh.readline().strip()
    except OSError:
        return None


def current_project():
    p = read_line(PROJECT_FILE) or os.environ.get("PROJECT", "longshot")
    return p if p in PROJECTS else "longshot"


def project():
    return PROJECTS[current_project()]


def ref_file():
    return os.path.join(project()["state"], "ref")


def current_ref():
    return read_line(ref_file()) or os.environ.get(project()["ref_env"], "latest")


def current_model():
    m = read_line(MODEL_FILE) or os.environ.get("MODEL", "pro")
    return m if m in MODELS else "pro"


def current_language():
    l = read_line(LANGUAGE_FILE) or os.environ.get("LANGUAGE", "de")
    return l if l in LANGUAGES else ""


def release_order(tag):
    """Neueste zuerst: nach Version, ein fertiges Release vor seinen Vorabversionen"""
    m = RELEASE_RE.match(tag)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if m.group(4) else 1, m.group(4) or "", int(m.group(5) or 0))


def fetch_releases():
    """Releases von GitHub (API: Datum, Vorab-Kennzeichen, ob eine Linux-AppImage dabei ist). Ohne API (ohne Token 60
    Abfragen je Stunde) die v-Tags aus git ls-remote; ob ein Tag eine AppImage hat, zeigt sich dann beim Laden."""
    found, source = {}, None
    repo, appimage = project()["repo"], project()["appimage"]
    try:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ps5-builder"}
        if os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
        req = urllib.request.Request("https://api.github.com/repos/%s/releases?per_page=100" % repo, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            for rel in json.load(r):
                tag = rel.get("tag_name") or ""
                if rel.get("draft") or not TAG_RE.match(tag):
                    continue
                has = any(re.fullmatch(re.escape(appimage) + r"-.*-x86_64\.AppImage", a.get("name", ""))
                          for a in rel.get("assets", []))
                found[tag] = {"tag": tag, "kind": "pre" if rel.get("prerelease") else "stable",
                              "date": (rel.get("published_at") or "")[:10], "appimage": has}
        source = "GitHub-API"
    except Exception as e:
        api_error = str(e)
        try:
            r = subprocess.run(["git", "ls-remote", "--tags", "--refs", "https://github.com/%s.git" % repo],
                               capture_output=True, text=True, timeout=30)
            if r.returncode:
                raise RuntimeError(r.stderr.strip()[:200])
            for l in r.stdout.splitlines():
                t = l.split("refs/tags/", 1)[-1]
                if RELEASE_RE.match(t):
                    found[t] = {"tag": t, "kind": "pre" if RELEASE_RE.match(t).group(4) else "stable", "date": "",
                                "appimage": None}
            source = "Git-Tags (API: %s)" % api_error[:80]
        except Exception as e2:
            raise RuntimeError("Release-Liste nicht abrufbar: %s / %s" % (api_error, e2))
    known = sorted((x for x in found.values() if RELEASE_RE.match(x["tag"])), key=lambda x: release_order(x["tag"]),
                   reverse=True)
    other = sorted((x for x in found.values() if not RELEASE_RE.match(x["tag"])), key=lambda x: x["date"], reverse=True)
    return {"source": source, "releases": known + other}


def releases(force=False):
    key = current_project()
    with lock:
        c = releases_cache.get(key)
        if not force and c and time.time() - c["time"] < 600:
            return c["data"]
    data = fetch_releases()
    with lock:
        releases_cache[key] = {"time": time.time(), "data": data}
    return data


def free_gb(path):
    try:
        st = os.statvfs(path)
        return round(st.f_bavail * st.f_frsize / (1 << 30), 1)
    except OSError:
        return None


def status():
    with lock:
        s = {"running": running(), "stage": state["stage"], "started": state["started"], "ended": state["ended"],
             "code": state["code"], "log": state["log"]}
    nup_dir = os.environ.get("NUP_DIR", "/nup")
    s["nup"] = os.environ.get("NUP_FILE") or next(iter(sorted(glob.glob(os.path.join(nup_dir, "*.nup")) +
                                                             glob.glob(os.path.join(nup_dir, "*", "*.nup")))), None)
    pr = project()
    s["project"] = current_project()
    s["projects"] = {k: v["label"] for k, v in PROJECTS.items()}
    s["repo"] = pr["repo"]
    s["title_id"] = pr["title_id"]
    s["ref"] = current_ref()
    s["model"] = current_model()
    s["models"] = MODELS
    s["language"] = current_language()
    s["languages"] = LANGUAGES
    s["builder"] = read_line(os.path.join(pr["state"], "builder", "current"))
    title = os.path.join(OUT, pr["title_id"])
    s["title"] = title
    s["build"] = read_json(os.path.join(pr["state"], "build-info.json")) if os.path.exists(os.path.join(title, "eboot.bin")) else None
    s["updates"] = read_json(os.path.join(pr["state"], "update-check.json"))
    host = os.environ.get("PS5_HOST", "")
    s["ps5"] = "%s:%s" % (host, os.environ.get("PS5_FTP_PORT", "2121")) if host else ""
    s["upload_nup"] = os.environ.get("UPLOAD_NUP", "false") == "true"
    s["free_config"] = free_gb(CONFIG)
    s["free_out"] = free_gb(OUT)
    return s


def saves_info():
    """Stand der Spielstaende (scripts/saves.py status), die Backups und der Verlauf der Kopien"""
    try:
        r = subprocess.run(["python3", "/app/scripts/saves.py", "backups"], capture_output=True, text=True, timeout=30,
                           env=dict(os.environ, CONFIG_DIR=CONFIG))
        backups = json.loads(r.stdout) if r.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        backups = []
    return {"status": read_json(os.path.join(SAVES_DIR, "status.json")), "backups": backups,
            "history": (read_json(os.path.join(SAVES_DIR, "history.json")) or [])[:10],
            "ps5": bool(os.environ.get("PS5_HOST", "").strip())}


def save_choice(path, value):
    with lock:
        if running():
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(value + "\n")
    return True


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/":
            with open(os.path.join(HERE, "index.html"), "rb") as fh:
                return self.send(200, fh.read(), "text/html; charset=utf-8")
        if u.path == "/api/status":
            return self.send(200, json.dumps(status()))
        if u.path == "/api/releases":
            try:
                force = urllib.parse.parse_qs(u.query).get("refresh", ["0"])[0] == "1"
                return self.send(200, json.dumps(dict(releases(force), ref=current_ref())))
            except Exception as e:
                return self.send(502, json.dumps({"error": str(e), "ref": current_ref(), "releases": []}))
        if u.path == "/api/saves":
            return self.send(200, json.dumps(saves_info()))
        if u.path == "/api/log":
            q = urllib.parse.parse_qs(u.query)
            try:
                off = int(q.get("from", ["0"])[0])
            except ValueError:
                off = 0
            path = state["log"] or os.path.join(LOGS, "latest.log")
            try:
                with open(path, "rb") as fh:
                    size = os.fstat(fh.fileno()).st_size
                    if off > size or off < 0:
                        off = 0
                    if off == 0 and size > 400_000:
                        off = size - 400_000
                    fh.seek(off)
                    chunk = fh.read(2_000_000)
            except OSError:
                return self.send(200, json.dumps({"next": 0, "text": ""}))
            return self.send(200, json.dumps({"next": off + len(chunk), "text": chunk.decode("utf-8", "replace")}))
        self.send(404, '{"error":"not found"}')

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/api/run":
            stage = q.get("stage", [""])[0]
            if stage not in STAGES:
                return self.send(400, json.dumps({"ok": False, "msg": "unbekannte Stufe"}))
            ok, msg = start(stage)
            return self.send(200 if ok else 409, json.dumps({"ok": ok, "msg": msg}))
        if u.path == "/api/ref":
            ref = q.get("ref", [""])[0]
            if not TAG_RE.match(ref):
                return self.send(400, json.dumps({"ok": False, "msg": "kein gueltiges Tag"}))
            if not save_choice(ref_file(), ref):
                return self.send(409, json.dumps({"ok": False, "msg": "waehrend eines Laufs nicht aenderbar"}))
            return self.send(200, json.dumps({"ok": True, "ref": ref}))
        if u.path == "/api/saves/copy":
            src, dst = q.get("from", [""])[0], q.get("to", [""])[0]
            if src not in SAVE_TITLES or dst not in SAVE_TITLES or src == dst:
                return self.send(400, json.dumps({"ok": False, "msg": "Quelle und Ziel: zwei verschiedene Spiele"}))
            ok, msg = start("saves-copy", {"SAVES_FROM": src, "SAVES_TO": dst})
            return self.send(200 if ok else 409, json.dumps({"ok": ok, "msg": msg}))
        if u.path == "/api/saves/restore":
            name, dst = q.get("backup", [""])[0], q.get("to", [""])[0]
            if not BACKUP_RE.match(name) or dst not in SAVE_TITLES or not os.path.isdir(os.path.join(SAVES_DIR, "backups", name)):
                return self.send(400, json.dumps({"ok": False, "msg": "unbekanntes Backup oder Ziel"}))
            ok, msg = start("saves-restore", {"SAVES_BACKUP": name, "SAVES_TO": dst})
            return self.send(200 if ok else 409, json.dumps({"ok": ok, "msg": msg}))
        if u.path == "/api/project":
            p = q.get("project", [""])[0]
            if p not in PROJECTS:
                return self.send(400, json.dumps({"ok": False, "msg": "unbekanntes Projekt"}))
            if not save_choice(PROJECT_FILE, p):
                return self.send(409, json.dumps({"ok": False, "msg": "waehrend eines Laufs nicht aenderbar"}))
            return self.send(200, json.dumps({"ok": True, "project": p}))
        if u.path == "/api/model":
            model = q.get("model", [""])[0]
            if model not in MODELS:
                return self.send(400, json.dumps({"ok": False, "msg": "unbekannte Konsole"}))
            if not save_choice(MODEL_FILE, model):
                return self.send(409, json.dumps({"ok": False, "msg": "waehrend eines Laufs nicht aenderbar"}))
            return self.send(200, json.dumps({"ok": True, "model": model}))
        if u.path == "/api/language":
            lang = q.get("language", [""])[0]
            if lang not in LANGUAGES:
                return self.send(400, json.dumps({"ok": False, "msg": "unbekannte Sprache"}))
            if not save_choice(LANGUAGE_FILE, lang):
                return self.send(409, json.dumps({"ok": False, "msg": "waehrend eines Laufs nicht aenderbar"}))
            return self.send(200, json.dumps({"ok": True, "language": lang}))
        if u.path == "/api/stop":
            return self.send(200, json.dumps({"ok": stop()}))
        self.send(404, '{"error":"not found"}')


if __name__ == "__main__":
    if os.environ.get("RUN_ON_START", "false") == "true":
        start("all")
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print("Web-UI auf Port %d" % PORT, flush=True)
    srv.serve_forever()
