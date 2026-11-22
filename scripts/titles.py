"""Die Zelda-Titles auf der PS5 (Longshot, HeyListen, der Fork, auch fremde Builds) per FTP auflisten, loeschen, umbenennen.

    titles.py list                        /data/homebrew lesen, Stand nach $CONFIG_DIR/titles/status.json
    titles.py delete --id PPSA99025       Spielstaende sichern, dann den Title-Ordner auf der PS5 loeschen
    titles.py rename --id PPSA99198 --name "Longshot v3"   den angezeigten Namen (titleName in sce_sys/param.json) aendern

Umgebung: PS5_HOST, PS5_FTP_PORT (2121), CONFIG_DIR (/config).

Erkannt wird ein Title an seinem Ordner unter /data/homebrew: sce_sys/param.json (titleId, titleName, contentVersion), die
Dateien der Ports (image.bin, longshot_env.txt bzw. hookshot_env.txt) und build-info.json, die der Container seit dieser
Version beim Build und Deploy mitschickt (Projekt, Repository, Release, Konsole, Zeit). Fehlt sie (aeltere Deploys, Builds von
woanders), zeigt die Liste das Datum der eboot.bin.

Loeschen nimmt nur Ordner, die beim letzten "list" als Zelda-Title erkannt wurden. Die Spielstaende (user/save) werden vorher
wie beim Kopieren nach $CONFIG_DIR/saves/backups gesichert.

Umbenennen aendert titleName fuer alle Sprachen in param.json auf der PS5. Gehoert die Title-ID zu einem Projekt des
Containers, merkt er sich den Namen dort ($STATE/title_name), damit Build und Deploy ihn behalten.
"""
import argparse
import ftplib
import io
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import saves   # noqa: E402  (FTP-Helfer, Backups)

HOMEBREW = "/data/homebrew"
CONFIG = os.environ.get("CONFIG_DIR", "/config")
STATUS_DIR = os.path.join(CONFIG, "titles")
STATUS = os.path.join(STATUS_DIR, "status.json")
ID_RE = re.compile(r"^[A-Z]{4}[0-9]{5}$")
# Title-ID -> (Projekt, Ordner seines Stands unter /config), wie scripts/build.sh: die aktuellen IDs (saves.TITLES, aus
# $STATE/title_id), dazu die frueheren Standards (Longshot bis v0.1.4: PPSA99025, ab v0.1.5 LGSH00001)
PROJECT_OF = {tid: (key, saves.STATES[key]) for key, (_, tid) in saves.TITLES.items()}
for _tid, _key in (("PPSA99025", "longshot"), ("LGSH00001", "longshot"), ("PPSA99026", "heylisten"), ("PPSA99198", "fork")):
    PROJECT_OF.setdefault(_tid, (_key, saves.STATES[_key]))
ZELDA_WORDS = ("longshot", "heylisten", "hookshot", "zelda", "ocarina")
PORT_FILES = ("image.bin", "longshot_env.txt", "hookshot_env.txt", "longshot_options.ini", "hookshot_options.ini")
say = saves.say


def read_remote(f, path):
    buf = io.BytesIO()
    try:
        f.voidcmd("TYPE I")
        f.retrbinary("RETR " + path, buf.write)
    except ftplib.all_errors:
        return None
    return buf.getvalue()


def read_json(f, path):
    data = read_remote(f, path)
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return None


def title_name(param):
    lp = (param or {}).get("localizedParameters") or {}
    lang = lp.get("defaultLanguage") or "en-US"
    return (lp.get(lang) or {}).get("titleName") or next((v.get("titleName") for v in lp.values()
                                                         if isinstance(v, dict) and v.get("titleName")), None)


def walk_size(f, root):
    """(Dateien, Bytes) unter root, ohne MDTM je Datei"""
    count, total, todo = 0, 0, [root]
    while todo:
        path = todo.pop()
        for name, is_dir, size, _ in saves.listdir(f, path) or []:
            if is_dir:
                todo.append(path + "/" + name)
            else:
                count += 1
                total += size
    return count, total


def cmd_list():
    f = saves.connect()
    entries = saves.listdir(f, HOMEBREW)
    if entries is None:
        sys.exit("FEHLER: %s gibt es auf der PS5 nicht (oder der FTP-Server darf es nicht lesen)" % HOMEBREW)
    found, others = [], []
    for name, is_dir, _, mtime in sorted(entries):
        if not is_dir:
            continue
        base = HOMEBREW + "/" + name
        top = {n: (d, s, t) for n, d, s, t in saves.listdir(f, base) or []}
        param = read_json(f, base + "/sce_sys/param.json")
        label = title_name(param) or ""
        zelda = (name in PROJECT_OF or any(w in label.lower() for w in ZELDA_WORDS)
                 or ("image.bin" in top and any(p in top for p in PORT_FILES[1:])))
        if not zelda:
            others.append(name)
            continue
        info = read_json(f, base + "/build-info.json") or {}
        eboot = top.get("eboot.bin")
        eboot_time = saves.mdtm(f, base + "/eboot.bin") or (eboot[2] if eboot else None)
        files, total = walk_size(f, base)
        save_files, save_bytes = walk_size(f, base + "/user/save")
        proj = PROJECT_OF.get(name, (None, None))[0]
        entry = {"id": name, "title_id": (param or {}).get("titleId"), "name": label,
                 "version": (param or {}).get("contentVersion"), "project": info.get("project") or proj,
                 "project_guess": not info.get("project") and bool(proj), "repo": info.get("repo"), "tag": info.get("tag"),
                 "model": info.get("model"), "built": info.get("time"), "eboot": bool(eboot),
                 "eboot_time": saves.iso(eboot_time) if eboot_time else None, "files": files, "bytes": total,
                 "saves": save_files, "saves_bytes": save_bytes,
                 "env": "longshot_env.txt" if "longshot_env.txt" in top else "hookshot_env.txt" if "hookshot_env.txt" in top else None}
        found.append(entry)
        say("%s  %-22s %s" % (name, '"%s"' % label if label else "(ohne param.json)",
                              ", ".join(x for x in (
                                  "%s %s" % (info.get("repo") or "", info.get("tag") or "") if info.get("tag") else
                                  "Herkunft unbekannt (kein build-info.json)",
                                  info.get("model") and "Konsole " + info["model"],
                                  "gebaut " + info["time"] if info.get("time") else
                                  "eboot.bin vom " + time.strftime("%d.%m.%Y %H:%M", time.localtime(eboot_time)) if eboot_time else "ohne eboot.bin",
                                  "%d MB" % (total >> 20),
                                  "%d Spielstand-Dateien" % save_files if save_files else "keine Spielstaende") if x)))
    f.quit()
    if not found:
        say("keine Zelda-Titles unter %s" % HOMEBREW)
    if others:
        say("andere Titles (nicht angezeigt): %s" % ", ".join(others))
    names = {}
    for e in found:
        names.setdefault((e["name"] or "").strip().lower(), []).append(e["id"])
    for n, ids in names.items():
        if n and len(ids) > 1:
            say("-> gleicher Name \"%s\" bei %s: mit Umbenennen unterscheidbar machen" % (n, ", ".join(ids)))
    os.makedirs(STATUS_DIR, exist_ok=True)
    with open(STATUS, "w") as fh:
        json.dump({"time": saves.iso(time.time()), "titles": found, "others": others}, fh, indent=1)


def known(tid):
    if not ID_RE.match(tid or ""):
        sys.exit("FEHLER: keine gueltige Title-ID: %r" % tid)
    try:
        st = json.load(open(STATUS))
    except (OSError, ValueError):
        sys.exit("FEHLER: erst die Titles lesen")
    hit = [e for e in st.get("titles", []) if e["id"] == tid]
    if not hit:
        sys.exit("FEHLER: %s war beim letzten Lesen kein Zelda-Title auf der PS5; erst neu lesen" % tid)
    return hit[0]


def remove_tree(f, root):
    """root mit allem darin loeschen (Dateien zuerst, dann die Ordner von unten); [(Pfad, Fehler)] was blieb"""
    files, dirs, todo = [], [root], [root]
    while todo:
        path = todo.pop()
        for name, is_dir, _, _ in saves.listdir(f, path) or []:
            (dirs if is_dir else files).append(path + "/" + name)
            if is_dir:
                todo.append(path + "/" + name)
    # (eboot.bin und param.json zuerst: ein halb geloeschter Ordner ist dann kein startbarer Title mehr)
    files.sort(key=lambda p: (not p.endswith(("/eboot.bin", "/sce_sys/param.json")), p))
    failed = []
    for i, p in enumerate(files):
        try:
            f.delete(p)
        except ftplib.all_errors as e:
            failed.append((p, str(e).strip()))
        if (i + 1) % 200 == 0:
            say("  %d von %d Dateien geloescht" % (i + 1, len(files)))
    for d in sorted(dirs, key=lambda p: p.count("/"), reverse=True):
        try:
            f.rmd(d)
        except ftplib.all_errors as e:
            try:   # (gesperrte Ordner wie bei den Spielstaenden: freigeben, nochmal)
                f.sendcmd("SITE CHMOD 777 " + d)
                f.rmd(d)
            except ftplib.all_errors:
                failed.append((d, str(e).strip()))
    return len(files), failed


def cmd_delete(tid):
    entry = known(tid)
    f = saves.connect()
    base = HOMEBREW + "/" + tid
    say("Title %s \"%s\" auf der PS5 loeschen (%s)" % (tid, entry.get("name") or "?", base))
    key = PROJECT_OF.get(tid, (tid.lower(),))[0]
    for ini in ("longshot_options.ini", "hookshot_options.ini"):
        saves.settings_backup(f, key, "vor-loeschen", remote=base + "/" + ini, label=tid)
    sv = saves.tree(f, base + "/user/save")
    if sv:
        name = saves.fresh_name(saves.BACKUPS, key, "vor-loeschen")
        to = os.path.join(saves.BACKUPS, name)
        saves.download(f, base + "/user/save", sv, to)
        say("  Spielstaende gesichert: %d Dateien -> %s" % (len(sv), to))
        saves.prune()
    else:
        say("  keine Spielstaende in diesem Title")
    count, failed = remove_tree(f, base)
    still = saves.listdir(f, base)
    f.quit()
    if still is not None:
        for p, e in failed[:20]:
            say("  nicht geloescht: %s (%s)" % (p, e))
        sys.exit("FEHLER: %s ist nicht ganz geloescht (%d Eintraege blieben). Laeuft das Spiel noch?" % (base, len(failed)))
    say("fertig: %s geloescht (%d Dateien). Steht die Kachel noch auf dem Startbildschirm, dort ebenfalls entfernen." % (base, count))
    try:
        st = json.load(open(STATUS))
        st["titles"] = [e for e in st["titles"] if e["id"] != tid]
        with open(STATUS, "w") as fh:
            json.dump(st, fh, indent=1)
    except (OSError, ValueError):
        pass


def set_name(param, new):
    lp = param.setdefault("localizedParameters", {})
    lp.setdefault("defaultLanguage", "en-US")
    langs = [k for k, v in lp.items() if isinstance(v, dict)] or [lp["defaultLanguage"]]
    for k in langs:
        lp.setdefault(k, {})["titleName"] = new


def cmd_rename(tid, new):
    new = (new or "").strip()
    if not new or len(new) > 40 or any(ord(c) < 32 for c in new):
        sys.exit("FEHLER: Name: 1 bis 40 Zeichen, ohne Steuerzeichen")
    known(tid)
    f = saves.connect()
    path = HOMEBREW + "/" + tid + "/sce_sys/param.json"
    param = read_json(f, path)
    if param is None:
        sys.exit("FEHLER: %s nicht lesbar" % path)
    old = title_name(param)
    set_name(param, new)
    os.makedirs(STATUS_DIR, exist_ok=True)
    tmp = os.path.join(STATUS_DIR, "param.json.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(param, indent=2, ensure_ascii=False) + "\n")
    try:
        saves.store(f, tmp, path)
    except ftplib.all_errors as e:
        sys.exit("FEHLER: %s nicht geschrieben (%s)" % (path, e))
    finally:
        os.remove(tmp)
    check = title_name(read_json(f, path))
    f.quit()
    if check != new:
        sys.exit("FEHLER: nach dem Schreiben steht in %s \"%s\"" % (path, check))
    say("fertig: %s heisst jetzt \"%s\" (vorher \"%s\")" % (tid, new, old or "?"))
    if tid in PROJECT_OF:
        key, state = PROJECT_OF[tid]
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "title_name"), "w") as fh:
            fh.write(new + "\n")
        say("  gemerkt fuer das Projekt %s: Build und Deploy behalten den Namen" % key)
    say("  Ob der Startbildschirm den neuen Namen sofort zeigt, haengt von der Homebrew-Umgebung ab: sonst PS5 neu starten.")
    try:
        st = json.load(open(STATUS))
        for e in st["titles"]:
            if e["id"] == tid:
                e["name"] = new
        with open(STATUS, "w") as fh:
            json.dump(st, fh, indent=1)
    except (OSError, ValueError):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("list", "delete", "rename"))
    ap.add_argument("--id")
    ap.add_argument("--name")
    a = ap.parse_args()
    os.makedirs(saves.BACKUPS, exist_ok=True)
    if a.command == "list":
        cmd_list()
    elif a.command == "delete":
        cmd_delete(a.id)
    else:
        cmd_rename(a.id, a.name)


if __name__ == "__main__":
    main()
