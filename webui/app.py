"""Web-UI fuer ps5-longshot-builder: Stufen starten, Log mitlesen, Release und Konsole waehlen, Stand anzeigen.
Nur Python-Standardbibliothek."""
import glob
import http.server
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.parse
import urllib.request

CONFIG = os.environ.get("CONFIG_DIR", "/config")
LOGS = os.path.join(CONFIG, "logs")
LOG_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9-]{1,40}\.log$")   # (Name eines Laufs: start() schreibt <Zeit>-<Stufe>.log)
PORT = int(os.environ.get("WEBUI_PORT", "8486"))
OUT = os.environ.get("OUT_DIR", "/output")
# Die Projekte, wie scripts/build.sh sie kennt: Repository, Name der Builder-AppImage, Title, eigener Ordner unter /config
PROJECTS = {
    "longshot": {"label": "Longshot (heydemoura/PS5_Longshot)", "repo": os.environ.get("LONGSHOT_REPO", "heydemoura/PS5_Longshot"),
                 "appimage": "LongshotPS5Builder", "title_id": os.environ.get("TITLE_ID", "LGSH00001"), "state": CONFIG,
                 "ref_env": "LONGSHOT_REF"},
    "heylisten": {"label": "HeyListen (cosmicflow2512/PS5_HeyListen, experimentell)",
                  "repo": os.environ.get("HEYLISTEN_REPO", "cosmicflow2512/PS5_HeyListen"), "appimage": "HeyListenPS5Builder",
                  "title_id": "PPSA99026", "state": os.path.join(CONFIG, "heylisten"), "ref_env": "HEYLISTEN_REF"},
}
PROJECTS["fork"] = {"label": "Longshot-Fork (cosmicflow2512/PS5_Longshot_Cosi, mit den offenen PRs)",
                    "repo": os.environ.get("FORK_REPO", "cosmicflow2512/PS5_Longshot_Cosi"), "appimage": "LongshotPS5Builder",
                    "title_id": "LGSF00002", "state": os.path.join(CONFIG, "fork"), "ref_env": "FORK_REF",
                    "id_env": "FORK_TITLE_ID"}
PROJECTS["plus"] = {"label": "Longshot Plus (groovy2312/PS5_Longshot_Plus)",
                    "repo": os.environ.get("PLUS_REPO", "groovy2312/PS5_Longshot_Plus"), "appimage": "PS5LongshotPlusBuilder",
                    "title_id": "LGSP00003", "state": os.path.join(CONFIG, "plus"), "ref_env": "PLUS_REF",
                    "id_env": "PLUS_TITLE_ID"}
PROJECTS["longshot"]["id_env"] = "LONGSHOT_TITLE_ID"
PROJECTS["heylisten"]["id_env"] = "HEYLISTEN_TITLE_ID"
PROJECT_FILE = os.path.join(CONFIG, "project")
STAGES = ("check", "all", "update", "build", "deploy", "saves-status", "titles-list", "settings-backup")
OPTIONS_FILE = {"longshot": "longshot_options.ini", "heylisten": "hookshot_options.ini", "fork": "longshot_options.ini",
                "plus": "longshot_options.ini"}   # (saves.py OPTIONS)
TITLE_ID_RE = re.compile(r"^[A-Z]{4}[0-9]{5}$")
SAVE_TITLES = ("longshot", "heylisten", "fork", "plus")   # (scripts/saves.py TITLES)
SAVES_DIR = os.path.join(CONFIG, "saves")
BACKUP_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9]+-[a-z-]+$")
MODELS = {"pro": "PS5 Pro", "base": "PS5 / PS5 Slim"}
# Die 16 Sprachen des Spiels (host/nn_applet.c von PS5_Longshot), wie build.sh sie in language.txt schreibt. "auto": keine
# language.txt, das Title folgt der Sprache der Konsole (ab v0.1.4) bzw. behaelt, was im Spielmenue gewaehlt ist
LANGUAGES = {"auto": "Sprache der Konsole folgen", "de": "Deutsch", "en-US": "English (US)", "en-GB": "English (UK)", "fr": "Français", "fr-CA": "Français (Canada)",
             "it": "Italiano", "es": "Español", "es-419": "Español (Latinoamérica)", "pt-BR": "Português (Brasil)",
             "nl": "Nederlands", "pl": "Polski", "ru": "Русский", "ja": "日本語", "ko": "한국어", "zh-Hans": "简体中文",
             "zh-Hant": "繁體中文"}
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_FILE = os.path.join(CONFIG, "model")
LANGUAGE_FILE = os.path.join(CONFIG, "language")
TAG_RE = re.compile(r"^[A-Za-z0-9._+-]{1,80}$")
# Archiv- und Builder-Ordner: wie ein Tag, aber nicht mit einem Punkt am Anfang (".", "..", versteckte Temp-Ordner)
NAME_RE = re.compile(r"^[A-Za-z0-9_+-][A-Za-z0-9._+-]{0,79}$")
KEEP_FILE = os.path.join(CONFIG, "keep_builders")
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
    """Das gewaehlte Projekt; title_id: die des letzten Builds ($STATE/title_id, scripts/build.sh), sonst der Standard
    (PS5_Longshot ab v0.1.5 LGSH00001, bis v0.1.4 PPSA99025). TITLE_ID setzt die von longshot fest."""
    pr = dict(PROJECTS[current_project()])
    fixed = os.environ.get(pr["id_env"]) or (os.environ.get("TITLE_ID") if current_project() == "longshot" else None)
    if fixed and TITLE_ID_RE.match(fixed):
        pr["title_id"] = fixed
    else:
        tid = read_line(os.path.join(pr["state"], "title_id"))
        if tid and TITLE_ID_RE.match(tid):
            pr["title_id"] = tid
    return pr


def ref_file():
    return os.path.join(project()["state"], "ref")


def current_ref():
    return read_line(ref_file()) or os.environ.get(project()["ref_env"], "latest")


def current_model():
    m = read_line(MODEL_FILE) or os.environ.get("MODEL", "pro")
    return m if m in MODELS else "pro"


def current_language():
    l = read_line(LANGUAGE_FILE) or os.environ.get("LANGUAGE", "") or "auto"
    return l if l in LANGUAGES else "auto"


def keep_builders():
    return (read_line(KEEP_FILE) or os.environ.get("KEEP_BUILDERS", "true")) == "true"


def archive_dir():
    """Archivierte Builds des gewaehlten Projekts (scripts/build.sh ARCHIVE_DIR)"""
    return os.path.join(OUT, "archive", current_project())


def builders_dir():
    return os.path.join(project()["state"], "builder")


def deploy_file():
    return os.path.join(project()["state"], "deploy_build")


def dir_size(path):
    total = 0
    for base, _, names in os.walk(path):
        for n in names:
            try:
                total += os.lstat(os.path.join(base, n)).st_size
            except OSError:
                pass
    return total


def archive_title(name):
    """Title-ID eines archivierten Builds: aus seiner build-info.json, sonst der Unterordner mit eboot.bin (aeltere Archive)"""
    d = os.path.join(archive_dir(), name)
    tid = (read_json(os.path.join(d, "build-info.json")) or {}).get("title_id")
    if tid and TITLE_ID_RE.match(tid):
        return tid
    for tid in sorted(glob.glob(os.path.join(d, "*", "eboot.bin"))):
        tid = os.path.basename(os.path.dirname(tid))
        if TITLE_ID_RE.match(tid):
            return tid
    return project()["title_id"]


def is_archived(name):
    return bool(NAME_RE.match(name)) and os.path.isfile(os.path.join(archive_dir(), name, archive_title(name), "eboot.bin"))


def archived():
    """Archivierte Builds unter /output/archive/<Projekt>/<Version>-<Konsole>/, neueste zuerst"""
    out, base = [], archive_dir()
    try:
        names = os.listdir(base)
    except OSError:
        return out
    for n in names:
        if not is_archived(n):
            continue
        d = os.path.join(base, n)
        info = read_json(os.path.join(d, "build-info.json")) or {}
        out.append({"name": n, "tag": info.get("tag", ""), "model": info.get("model", ""), "time": info.get("time", ""),
                    "title_id": archive_title(n),
                    "size": dir_size(d), "mtime": os.path.getmtime(d)})
    return sorted(out, key=lambda x: x["mtime"], reverse=True)


def current_deploy():
    """Was "Auf die PS5 kopieren" nimmt: "current" (/output/<Title-ID>) oder ein Archivname, der noch existiert"""
    v = read_line(deploy_file()) or "current"
    return v if v == "current" or is_archived(v) else "current"


def builds():
    pr = project()
    cur = None
    if os.path.isfile(os.path.join(OUT, pr["title_id"], "eboot.bin")):
        info = read_json(os.path.join(pr["state"], "build-info.json")) or {}
        cur = {"tag": info.get("tag", ""), "model": info.get("model", ""), "time": info.get("time", "")}
    active = read_line(os.path.join(builders_dir(), "current"))
    bl = []
    try:
        for n in sorted(os.listdir(builders_dir())):
            if NAME_RE.match(n) and os.path.isdir(os.path.join(builders_dir(), n)):
                bl.append({"name": n, "size": dir_size(os.path.join(builders_dir(), n)), "active": n == active})
    except OSError:
        pass
    return {"project": current_project(), "title_id": pr["title_id"], "archive_dir": archive_dir(), "current": cur,
            "archive": archived(), "deploy": current_deploy(), "keep_builders": keep_builders(), "builders": bl}


def remove_dir(parent, name):
    """Ordner <parent>/<name> loeschen: nicht waehrend eines Laufs, nur direkt unter parent"""
    if not NAME_RE.match(name):
        return False, "kein gueltiger Name"
    path = os.path.join(parent, name)
    if os.path.dirname(os.path.realpath(path)) != os.path.realpath(parent) or not os.path.isdir(path):
        return False, "nicht vorhanden"
    with lock:
        if running():
            return False, "waehrend eines Laufs nicht moeglich"
        try:
            shutil.rmtree(path)
        except OSError as e:
            return False, "Loeschen fehlgeschlagen: %s" % e
    return True, "geloescht: " + path


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
    s["deploy"] = current_deploy()
    s["updates"] = read_json(os.path.join(pr["state"], "update-check.json"))
    host = os.environ.get("PS5_HOST", "")
    s["ps5"] = "%s:%s" % (host, os.environ.get("PS5_FTP_PORT", "2121")) if host else ""
    s["upload_nup"] = os.environ.get("UPLOAD_NUP", "false") == "true"
    s["free_config"] = free_gb(CONFIG)
    s["free_out"] = free_gb(OUT)
    return s


def title_id_of(key):
    """die Title-ID (= Ordner unter /data/homebrew) des Projekts key, wie project() und scripts/saves.py _title_id"""
    pr = PROJECTS[key]
    fixed = os.environ.get(pr["id_env"]) or (os.environ.get("TITLE_ID") if key == "longshot" else None)
    if fixed and TITLE_ID_RE.match(fixed):
        return fixed
    tid = read_line(os.path.join(pr["state"], "title_id"))
    return tid if tid and TITLE_ID_RE.match(tid) else pr["title_id"]


def saves_info():
    """Stand der Spielstaende (scripts/saves.py status), die Backups und der Verlauf der Kopien"""
    try:
        r = subprocess.run(["python3", "/app/scripts/saves.py", "backups"], capture_output=True, text=True, timeout=30,
                           env=dict(os.environ, CONFIG_DIR=CONFIG))
        backups = json.loads(r.stdout) if r.returncode == 0 else []
        r = subprocess.run(["python3", "/app/scripts/saves.py", "settings-backups"], capture_output=True, text=True, timeout=30,
                           env=dict(os.environ, CONFIG_DIR=CONFIG))
        settings = json.loads(r.stdout) if r.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        backups, settings = [], []
    return {"status": read_json(os.path.join(SAVES_DIR, "status.json")), "backups": backups, "settings_backups": settings,
            "options_files": OPTIONS_FILE, "ids": {k: title_id_of(k) for k in SAVE_TITLES},
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
        if u.path == "/api/builds":
            return self.send(200, json.dumps(builds()))
        if u.path == "/api/saves":
            return self.send(200, json.dumps(saves_info()))
        if u.path == "/api/titles":
            return self.send(200, json.dumps({"status": read_json(os.path.join(CONFIG, "titles", "status.json")),
                                              "ps5": bool(os.environ.get("PS5_HOST", "").strip())}))
        if u.path == "/api/logs":
            # die Laeufe unter /config/logs, neueste zuerst (fuer die Auswahl zum Herunterladen)
            out = []
            try:
                for n in os.listdir(LOGS):
                    if LOG_RE.match(n):
                        st = os.stat(os.path.join(LOGS, n))
                        out.append({"name": n, "size": st.st_size, "mtime": st.st_mtime})
            except OSError:
                pass
            out.sort(key=lambda x: x["name"], reverse=True)
            cur = os.path.basename(state["log"]) if state["log"] else None
            return self.send(200, json.dumps({"logs": out[:50], "current": cur}))
        if u.path == "/api/log.txt":
            # ein Lauf ganz, als Textdatei: ?name=<Lauf> (nur Namen aus /config/logs), sonst der aktuelle bzw. letzte
            name = urllib.parse.parse_qs(u.query).get("name", [""])[0]
            if name:
                if not LOG_RE.match(name):
                    return self.send(400, '{"error":"kein gueltiger Name"}')
                path = os.path.join(LOGS, name)
            else:
                path = state["log"] or os.path.realpath(os.path.join(LOGS, "latest.log"))
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
            except OSError:
                return self.send(404, '{"error":"kein Log"}')
            fname = "ps5-builder-" + os.path.basename(path)[:-4] + ".txt"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            if urllib.parse.parse_qs(u.query).get("inline", ["0"])[0] != "1":
                self.send_header("Content-Disposition", 'attachment; filename="%s"' % fname)
            self.end_headers()
            self.wfile.write(data)
            return
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
        if u.path == "/api/settings/copy":
            src, dst = q.get("from", [""])[0], q.get("to", [""])[0]
            if src not in OPTIONS_FILE or dst not in OPTIONS_FILE or src == dst or OPTIONS_FILE[src] != OPTIONS_FILE[dst]:
                return self.send(400, json.dumps({"ok": False, "msg": "nur zwischen Longshot und Longshot-Fork (gleiche Datei)"}))
            ok, msg = start("settings-copy", {"SAVES_FROM": src, "SAVES_TO": dst})
            return self.send(200 if ok else 409, json.dumps({"ok": ok, "msg": msg}))
        if u.path == "/api/settings/restore":
            name, dst = q.get("backup", [""])[0], q.get("to", [""])[0]
            if not BACKUP_RE.match(name) or dst not in OPTIONS_FILE or not os.path.isdir(os.path.join(SAVES_DIR, "settings", name)):
                return self.send(400, json.dumps({"ok": False, "msg": "unbekannte Sicherung oder Ziel"}))
            ok, msg = start("settings-restore", {"SAVES_BACKUP": name, "SAVES_TO": dst})
            return self.send(200 if ok else 409, json.dumps({"ok": ok, "msg": msg}))
        if u.path in ("/api/titles/delete", "/api/titles/rename"):
            tid = q.get("id", [""])[0]
            st = read_json(os.path.join(CONFIG, "titles", "status.json")) or {}
            if not TITLE_ID_RE.match(tid) or tid not in [t.get("id") for t in st.get("titles", [])]:
                return self.send(400, json.dumps({"ok": False, "msg": "unbekannter Title (erst neu lesen)"}))
            if u.path.endswith("delete"):
                ok, msg = start("titles-delete", {"TITLES_ID": tid})
            else:
                name = q.get("name", [""])[0].strip()
                if not name or len(name) > 40 or any(ord(c) < 32 for c in name):
                    return self.send(400, json.dumps({"ok": False, "msg": "Name: 1 bis 40 Zeichen"}))
                ok, msg = start("titles-rename", {"TITLES_ID": tid, "TITLES_NAME": name})
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
        if u.path == "/api/deploy-build":
            name = q.get("name", [""])[0]
            if name != "current" and not is_archived(name):
                return self.send(400, json.dumps({"ok": False, "msg": "kein solcher Build"}))
            if not save_choice(deploy_file(), name):
                return self.send(409, json.dumps({"ok": False, "msg": "waehrend eines Laufs nicht aenderbar"}))
            return self.send(200, json.dumps({"ok": True, "deploy": name}))
        if u.path == "/api/delete-build":
            ok, msg = remove_dir(archive_dir(), q.get("name", [""])[0])
            return self.send(200 if ok else 409, json.dumps({"ok": ok, "msg": msg}))
        if u.path == "/api/delete-builder":
            name = q.get("name", [""])[0]
            if name == read_line(os.path.join(builders_dir(), "current")):
                return self.send(409, json.dumps({"ok": False, "msg": "der aktive Builder bleibt"}))
            ok, msg = remove_dir(builders_dir(), name)
            return self.send(200 if ok else 409, json.dumps({"ok": ok, "msg": msg}))
        if u.path == "/api/keep-builders":
            on = q.get("on", [""])[0]
            if on not in ("true", "false"):
                return self.send(400, json.dumps({"ok": False, "msg": "true oder false"}))
            if not save_choice(KEEP_FILE, on):
                return self.send(409, json.dumps({"ok": False, "msg": "waehrend eines Laufs nicht aenderbar"}))
            return self.send(200, json.dumps({"ok": True, "keep_builders": on == "true"}))
        if u.path == "/api/stop":
            return self.send(200, json.dumps({"ok": stop()}))
        self.send(404, '{"error":"not found"}')


if __name__ == "__main__":
    if os.environ.get("RUN_ON_START", "false") == "true":
        start("all")
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print("Web-UI auf Port %d" % PORT, flush=True)
    srv.serve_forever()
