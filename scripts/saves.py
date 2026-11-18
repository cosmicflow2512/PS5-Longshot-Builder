"""Spielstaende der PS5-Titles lesen, vergleichen und per FTP von einem Title in den anderen kopieren.

    saves.py status                      beide Spielstand-Ordner lesen, Stand nach $CONFIG_DIR/saves/status.json
    saves.py copy --from A --to B        Ziel sichern, dann Quelle nach Ziel spiegeln (A, B: longshot, heylisten)
    saves.py restore --backup NAME --to B   Ziel sichern, dann das Backup NAME nach Ziel spiegeln
    saves.py backups                     vorhandene Backups

Umgebung: PS5_HOST, PS5_FTP_PORT (2121), CONFIG_DIR (/config).

Beide Ports legen die Spielstaende gleich ab: <Title-Ordner>/user/save/<Benutzer-ID>/ (host/nn_fs.c), mit derselben festen
Benutzer-ID (user_uid in host/nn_*.c von PS5_Longshot und PS5_HeyListen). Kopiert wird daher der ganze Ordner user/save.
"Spiegeln" heisst: danach liegt im Ziel genau, was in der Quelle liegt; Dateien, die nur im Ziel lagen, werden entfernt. Vorher
wird das Ziel immer nach $CONFIG_DIR/saves/backups/<Zeit>-<title>-<anlass>/ gesichert (die neuesten KEEP_BACKUPS bleiben).

Waehrend des Kopierens darf keines der beiden Spiele auf der PS5 laufen: ein laufendes Spiel schreibt seine Spielstaende beim
naechsten Speichern zurueck.
"""
import argparse
import datetime
import ftplib
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time

TITLES = {"longshot": ("Longshot", "PPSA99025"), "heylisten": ("HeyListen", "PPSA99026"), "fork": ("Longshot-Fork", "PPSA99198")}
CONFIG = os.environ.get("CONFIG_DIR", "/config")
SAVES = os.path.join(CONFIG, "saves")
BACKUPS = os.path.join(SAVES, "backups")
STATUS = os.path.join(SAVES, "status.json")
HISTORY = os.path.join(SAVES, "history.json")
KEEP_BACKUPS = 30
MAX_DOWNLOAD = 256 << 20   # (groessere Ordner werden fuer den Vergleich nicht geladen: nur Groessen und Zeiten)
MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
BACKUP_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z]+-[a-z-]+$")


def say(text):
    print(text, flush=True)


def save_dir(key):
    return "/data/homebrew/%s/user/save" % TITLES[key][1]


def title_dir(key):
    return "/data/homebrew/%s" % TITLES[key][1]


def connect():
    host = os.environ.get("PS5_HOST", "").strip()
    if not host or host == "0.0.0.0":
        sys.exit("FEHLER: PS5_HOST ist nicht gesetzt (IP der PS5)")
    port = int(os.environ.get("PS5_FTP_PORT", "2121"))
    f = ftplib.FTP()
    try:
        f.connect(host, port, timeout=60)
        f.login()
        f.voidcmd("TYPE I")
    except ftplib.all_errors as e:
        sys.exit("FEHLER: keine FTP-Verbindung zu %s:%d (%s). Laeuft der FTP-Server auf der PS5?" % (host, port, e))
    return f


# ---- lesen ----

def parse_list_time(fields):
    """Zeit aus einer LIST-Zeile ("Nov 18 14:38" oder "Nov 18  2025"), als Unix-Zeit in UTC; None wenn unlesbar"""
    try:
        mon, day, third = MONTHS[fields[0].lower()[:3]], int(fields[1]), fields[2]
        if ":" in third:
            hh, mm = (int(x) for x in third.split(":"))
            now = datetime.datetime.now(datetime.timezone.utc)
            t = datetime.datetime(now.year, mon, day, hh, mm, tzinfo=datetime.timezone.utc)
            if t > now + datetime.timedelta(days=2):   # (ohne Jahr: im Vorjahr)
                t = t.replace(year=now.year - 1)
        else:
            t = datetime.datetime(int(third), mon, day, tzinfo=datetime.timezone.utc)
        return t.timestamp()
    except (KeyError, ValueError, IndexError):
        return None


def mdtm(f, path):
    try:
        r = f.sendcmd("MDTM " + path)
        m = re.search(r"(\d{14})", r)
        if m:
            return datetime.datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc).timestamp()
    except ftplib.all_errors:
        pass
    return None


def listdir(f, path):
    """[(name, is_dir, size, mtime)] eines Ordners; None wenn es ihn nicht gibt. Erst MLSD (genaue Zeiten), sonst LIST"""
    try:
        out = []
        for name, facts in f.mlsd(path):
            if name in (".", "..") or facts.get("type") in ("cdir", "pdir"):
                continue
            t = facts.get("modify")
            mt = datetime.datetime.strptime(t[:14], "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc).timestamp() if t else None
            out.append((name, facts.get("type") == "dir", int(facts.get("size", 0) or 0), mt))
        return out
    except ftplib.error_perm as e:
        if not str(e).startswith(("500", "502", "504")):   # (kein MLSD: LIST; sonst gibt es den Ordner nicht)
            return None
    except ftplib.all_errors:
        pass
    lines = []
    try:
        f.retrlines("LIST " + path, lines.append)
    except ftplib.error_perm:
        return None
    out = []
    for line in lines:
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        name = parts[8]
        if name in (".", ".."):
            continue
        try:
            size = int(parts[4])
        except ValueError:
            size = 0
        out.append((name, line.startswith("d"), size, parse_list_time(parts[5:8])))
    return out


def tree(f, root):
    """{relativer Pfad: (Groesse, Zeit)} aller Dateien unter root; None wenn root fehlt"""
    top = listdir(f, root)
    if top is None:
        return None
    files = {}

    def walk(path, rel, entries):
        for name, is_dir, size, mt in entries:
            r = rel + "/" + name if rel else name
            if is_dir:
                sub = listdir(f, path + "/" + name)
                if sub:
                    walk(path + "/" + name, r, sub)
            else:
                files[r] = (size, mt)
    walk(root, "", top)
    for r, (size, mt) in list(files.items()):   # (genauere Zeit, wo der Server MDTM kann)
        exact = mdtm(f, root + "/" + r)
        if exact:
            files[r] = (size, exact)
    return files


def download(f, root, files, to):
    os.makedirs(to, exist_ok=True)
    for r in sorted(files):
        local = os.path.join(to, *r.split("/"))
        os.makedirs(os.path.dirname(local), exist_ok=True)
        with open(local, "wb") as fh:
            f.retrbinary("RETR " + root + "/" + r, fh.write)
        if files[r][1]:
            os.utime(local, (files[r][1], files[r][1]))


def digest_dir(d):
    h = hashlib.sha1()
    for base, _, fs in sorted(os.walk(d)):
        for name in sorted(fs):
            p = os.path.join(base, name)
            h.update(os.path.relpath(p, d).replace(os.sep, "/").encode() + b"\0")
            with open(p, "rb") as fh:
                h.update(hashlib.sha1(fh.read()).digest())
    return h.hexdigest()


def local_files(d):
    out = {}
    for base, _, fs in os.walk(d):
        for name in fs:
            p = os.path.join(base, name)
            out[os.path.relpath(p, d).replace(os.sep, "/")] = (os.path.getsize(p), os.path.getmtime(p))
    return out


def iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


# ---- schreiben ----

def is_dir(f, path):
    try:
        f.cwd(path)
        f.cwd("/")
        return True
    except ftplib.all_errors:
        return False


def mkdirs(f, path):
    """den Ordner path mit allen fehlenden Ebenen; die Antwort des Servers, wenn er danach fehlt (sonst None)"""
    cur, last = "", None
    for part in path.strip("/").split("/"):
        cur += "/" + part
        try:
            f.mkd(cur)
        except ftplib.all_errors as e:
            last = "%s: %s" % (cur, e)
    return None if is_dir(f, path) else (last or "unbekannt")


def store(f, local, remote):
    """local nach remote; bei 550 einmal mit Wechsel in den Ordner und relativem Namen (manche FTP-Server auf der PS5
    lehnen absolute Pfade bei STOR ab). Wirft den Fehler des zweiten Versuchs weiter"""
    with open(local, "rb") as fh:
        try:
            f.storbinary("STOR " + remote, fh)
            return
        except ftplib.error_perm as e:
            first = e
    folder, name = remote.rsplit("/", 1)
    try:
        f.cwd(folder)
        with open(local, "rb") as fh:
            f.storbinary("STOR " + name, fh)
        say("  (%s: absolut abgelehnt [%s], relativ geschrieben)" % (name, str(first).strip()))
    finally:
        try:
            f.cwd("/")
        except ftplib.all_errors:
            pass


def unlock(f, target_key, remote, err):
    """Schreiben in user/ des Ziels abgelehnt, obwohl der Title-Ordner beschreibbar ist: das Spiel hat user/ beim ersten
    Start selbst angelegt, mit Rechten, die der FTP-Server nicht beschreiben darf (vermutet; beobachtet: Title-Ordner
    beschreibbar, user/save/<id> vorhanden und leer, STOR darin 550). Erst SITE CHMOD 777 auf user, user/save und den
    Ordner der Datei; sonst user/ umbenennen (dazu reicht der Title-Ordner) und neu anlegen. True: noch einmal versuchen"""
    say("  Schreiben in %s abgelehnt (%s): Rechte freigeben" % (remote.rsplit("/", 1)[0], str(err).strip()))
    user = title_dir(target_key) + "/user"
    chain, cur = [], user
    for part in remote[len(user) + 1:].split("/")[:-1]:
        chain.append(cur)
        cur += "/" + part
    chain.append(cur)
    ok = True
    for d in chain:
        try:
            f.sendcmd("SITE CHMOD 777 " + d)
        except ftplib.all_errors as e:
            ok = False
            say("    SITE CHMOD 777 %s: %s" % (d, str(e).strip()))
            break
    if ok:
        say("    Rechte von %s freigegeben (SITE CHMOD 777)" % user)
        return True
    if tree(f, user):   # (nur wenn in user/ nichts liegt, was ein Spieler vermissen koennte)
        say("    %s ist nicht leer: wird nicht umbenannt" % user)
        return False
    aside = "%s.vorher-%s" % (user, time.strftime("%Y%m%d-%H%M%S"))
    try:
        f.rename(user, aside)
    except ftplib.all_errors as e:
        say("    %s nicht umbenannt (%s)" % (user, str(e).strip()))
        return False
    say("    %s (leer, nicht beschreibbar) umbenannt nach %s; wird neu angelegt" % (user, aside))
    return True


def diagnose(f, target_key, remote, err):
    """warum STOR abgelehnt wurde: Ordner da? Schreiben im Title-Ordner moeglich?"""
    folder = remote.rsplit("/", 1)[0]
    say("")
    say("FEHLER beim Schreiben von %s" % remote)
    say("  Antwort der PS5: %s" % str(err).strip())
    say("  Zielordner %s: %s" % (folder, "vorhanden" if is_dir(f, folder) else "fehlt"))
    probe = title_dir(target_key) + "/.ps5-builder-schreibtest"
    try:
        f.storbinary("STOR " + probe, io.BytesIO(b"test"))
        f.delete(probe)
        say("  Schreibtest im Title-Ordner %s: geht" % title_dir(target_key))
        say("  -> der Title-Ordner ist beschreibbar, nur der Spielstand-Ordner nicht. Laeuft %s gerade auf der PS5? Dann"
            " das Spiel beenden und noch einmal kopieren." % TITLES[target_key][0])
    except ftplib.all_errors as e:
        say("  Schreibtest im Title-Ordner %s: abgelehnt (%s)" % (title_dir(target_key), str(e).strip()))
        say("  -> der FTP-Server darf dort nicht schreiben. Laeuft %s gerade? Dann beenden. Sonst: ein Deploy schreibt"
            " in denselben Ordner; geht das noch?" % TITLES[target_key][0])


def mirror(f, src_dir, target_key):
    """den lokalen Ordner src_dir nach user/save von target_key: hochladen, ueberzaehlige Dateien entfernen, pruefen"""
    root = save_dir(target_key)
    want = local_files(src_dir)
    for r in sorted(want):
        remote = root + "/" + r
        missing = mkdirs(f, remote.rsplit("/", 1)[0])
        if missing:
            say("  Hinweis: Ordner %s nicht angelegt (%s)" % (remote.rsplit("/", 1)[0], missing))
        local = os.path.join(src_dir, *r.split("/"))
        try:
            store(f, local, remote)
        except ftplib.error_perm as e:
            if not unlock(f, target_key, remote, e):
                diagnose(f, target_key, remote, e)
                sys.exit("FEHLER: Kopieren abgebrochen bei %s. Was schon im Ziel lag, ist im Backup unter %s." % (r, BACKUPS))
            mkdirs(f, remote.rsplit("/", 1)[0])
            try:
                store(f, local, remote)
            except ftplib.all_errors as e2:
                diagnose(f, target_key, remote, e2)
                sys.exit("FEHLER: Kopieren abgebrochen bei %s. Was schon im Ziel lag, ist im Backup unter %s." % (r, BACKUPS))
        mt = want[r][1]
        try:   # (die Zeit der Quelle mitnehmen, wo der Server MFMT kann: sonst gilt die Zeit des Hochladens)
            f.sendcmd("MFMT %s %s" % (time.strftime("%Y%m%d%H%M%S", time.gmtime(mt)), remote))
        except ftplib.all_errors:
            pass
        say("  hochgeladen: %s (%d Bytes)" % (r, want[r][0]))
    now = tree(f, root) or {}
    for r in sorted(set(now) - set(want)):
        try:
            f.delete(root + "/" + r)
            say("  entfernt (lag nur im Ziel, ist im Backup): %s" % r)
        except ftplib.all_errors as e:
            say("  Hinweis: %s nicht entfernt (%s)" % (r, e))
    now = tree(f, root) or {}
    bad = [r for r in want if r not in now or now[r][0] != want[r][0]]
    if bad:
        sys.exit("FEHLER: nach dem Kopieren stimmen %d Dateien nicht (Groesse): %s" % (len(bad), ", ".join(bad[:5])))
    say("  geprueft: %d Dateien im Ziel, Groessen stimmen" % len(want))


def backup(f, key, reason):
    """user/save von key nach backups/<zeit>-<key>-<reason>; None wenn dort nichts liegt"""
    files = tree(f, save_dir(key))
    if not files:
        say("  %s: keine Spielstaende auf der PS5, nichts zu sichern" % TITLES[key][0])
        return None
    name = "%s-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), key, reason)
    to = os.path.join(BACKUPS, name)
    download(f, save_dir(key), files, to)
    say("  gesichert: %s (%d Dateien) -> %s" % (TITLES[key][0], len(files), to))
    prune()
    return name


def prune():
    names = sorted(n for n in os.listdir(BACKUPS) if BACKUP_RE.match(n)) if os.path.isdir(BACKUPS) else []
    for n in names[:-KEEP_BACKUPS]:
        shutil.rmtree(os.path.join(BACKUPS, n), ignore_errors=True)


def remember(entry):
    try:
        hist = json.load(open(HISTORY))
    except (OSError, ValueError):
        hist = []
    hist.insert(0, entry)
    os.makedirs(SAVES, exist_ok=True)
    with open(HISTORY, "w") as fh:
        json.dump(hist[:50], fh, indent=1)


# ---- Befehle ----

def cmd_status():
    f = connect()
    os.makedirs(SAVES, exist_ok=True)
    result = {"time": iso(time.time()), "titles": {}}
    for key, (label, tid) in TITLES.items():
        installed = _has_size(f, title_dir(key) + "/eboot.bin")
        files = tree(f, save_dir(key))
        entry = {"label": label, "title_id": tid, "installed": installed, "path": save_dir(key), "present": bool(files)}
        if files:
            newest = max(files.items(), key=lambda kv: kv[1][1] or 0)
            total = sum(s for s, _ in files.values())
            entry.update(files=len(files), bytes=total, newest=iso(newest[1][1]), newest_file=newest[0],
                         list=[{"path": r, "bytes": s, "time": iso(t)} for r, (s, t) in sorted(files.items())])
            if total <= MAX_DOWNLOAD:
                snap = os.path.join(SAVES, "current", key)
                shutil.rmtree(snap, ignore_errors=True)
                download(f, save_dir(key), files, snap)
                entry["digest"] = digest_dir(snap)
        result["titles"][key] = entry
        say("%-10s %s: %s" % (label, tid, "%d Dateien, %d KB, zuletzt geaendert %s (%s)" % (
            entry["files"], entry["bytes"] >> 10, entry["newest"] or "?", entry["newest_file"]) if files else
            ("keine Spielstaende" + ("" if installed else " (Title nicht installiert)"))))
    f.quit()
    t = result["titles"]
    have = [k for k in TITLES if t[k]["present"]]
    for k in have:   # (gleicher Inhalt wie welche anderen)
        t[k]["same_as"] = [o for o in have if o != k and t[k].get("digest") and t[k].get("digest") == t[o].get("digest")]
    if len(have) >= 2:
        result["same"] = all(len(t[k]["same_as"]) == len(have) - 1 for k in have)
        if result["same"]:
            say("-> alle Spielstaende sind gleich")
        else:
            top = max(t[k]["newest"] or "" for k in have)
            newest = [k for k in have if (t[k]["newest"] or "") == top]
            # (der neueste, wenn er es allein ist oder die mit gleicher Zeit gleichen Inhalt haben)
            result["newer"] = newest[0] if len(newest) == 1 or all(o in t[newest[0]]["same_as"] for o in newest[1:]) else None
            for k in have:
                if t[k]["same_as"]:
                    say("-> %s gleich wie %s" % (TITLES[k][0], ", ".join(TITLES[o][0] for o in t[k]["same_as"])))
            say("-> neuester (nach Dateizeit): %s" % (TITLES[result["newer"]][0] if result["newer"] else "unklar, gleiche Zeit"))
    with open(STATUS, "w") as fh:
        json.dump(result, fh, indent=1)


def _has_size(f, path):
    try:
        f.voidcmd("TYPE I")   # (MLSD und LIST lassen die Verbindung im Textmodus, und dort lehnen Server SIZE ab)
        f.size(path)
        return True
    except ftplib.all_errors:
        return False


def cmd_copy(src, dst):
    if src == dst:
        sys.exit("FEHLER: Quelle und Ziel sind gleich")
    f = connect()
    say("Spielstaende %s (%s) -> %s (%s)" % (TITLES[src][0], TITLES[src][1], TITLES[dst][0], TITLES[dst][1]))
    files = tree(f, save_dir(src))
    if not files:
        sys.exit("FEHLER: in %s liegen keine Spielstaende (%s)" % (TITLES[src][0], save_dir(src)))
    if not _has_size(f, title_dir(dst) + "/eboot.bin"):
        say("  Hinweis: %s ist auf der PS5 nicht installiert (%s fehlt); die Spielstaende liegen dann schon bereit"
            % (TITLES[dst][0], title_dir(dst) + "/eboot.bin"))
    saved = backup(f, dst, "vor-kopie")
    tmp = os.path.join(SAVES, "tmp-copy")
    shutil.rmtree(tmp, ignore_errors=True)
    download(f, save_dir(src), files, tmp)
    say("  gelesen: %d Dateien aus %s" % (len(files), TITLES[src][0]))
    mirror(f, tmp, dst)
    digest = digest_dir(tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    f.quit()
    remember({"time": iso(time.time()), "action": "copy", "from": src, "to": dst, "files": len(files), "backup": saved,
              "digest": digest})
    say("fertig: %s hat jetzt die Spielstaende von %s%s" % (TITLES[dst][0], TITLES[src][0],
                                                            " (vorher gesichert: %s)" % saved if saved else ""))


def cmd_restore(name, dst):
    if not BACKUP_RE.match(name) or not os.path.isdir(os.path.join(BACKUPS, name)):
        sys.exit("FEHLER: kein Backup %s" % name)
    src_dir = os.path.join(BACKUPS, name)
    if not local_files(src_dir):
        sys.exit("FEHLER: das Backup %s ist leer" % name)
    f = connect()
    say("Backup %s -> %s (%s)" % (name, TITLES[dst][0], TITLES[dst][1]))
    saved = backup(f, dst, "vor-wiederherstellen")
    mirror(f, src_dir, dst)
    f.quit()
    remember({"time": iso(time.time()), "action": "restore", "backup_used": name, "to": dst, "backup": saved})
    say("fertig: %s hat jetzt den Stand aus %s" % (TITLES[dst][0], name))


def backups():
    out = []
    if os.path.isdir(BACKUPS):
        for n in sorted((n for n in os.listdir(BACKUPS) if BACKUP_RE.match(n)), reverse=True):
            files = local_files(os.path.join(BACKUPS, n))
            key = n.split("-")[2]
            out.append({"name": n, "title": TITLES.get(key, (key, ""))[0], "files": len(files),
                        "bytes": sum(s for s, _ in files.values()),
                        "newest": iso(max((t for _, t in files.values()), default=0)) if files else None})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("status", "copy", "restore", "backups"))
    ap.add_argument("--from", dest="src", choices=sorted(TITLES))
    ap.add_argument("--to", dest="dst", choices=sorted(TITLES))
    ap.add_argument("--backup")
    a = ap.parse_args()
    os.makedirs(BACKUPS, exist_ok=True)
    if a.command == "status":
        cmd_status()
    elif a.command == "copy":
        if not a.src or not a.dst:
            sys.exit("FEHLER: copy braucht --from und --to")
        cmd_copy(a.src, a.dst)
    elif a.command == "restore":
        if not a.backup or not a.dst:
            sys.exit("FEHLER: restore braucht --backup und --to")
        cmd_restore(a.backup, a.dst)
    else:
        print(json.dumps(backups(), indent=1))


if __name__ == "__main__":
    main()
