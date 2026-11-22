"""Das Title (Longshot LGSH00001, bis v0.1.4 PPSA99025; HeyListen PPSA99026; Fork PPSA99198) per FTP auf die PS5 (Standardport 2121) und optional die .nup dazu.

    deploy.py --dist <output/PPSA99025> [--upload-nup <spiel.nup>]

Umgebung: PS5_HOST, PS5_FTP_PORT (2121), PS5_TITLE_DIR (/data/homebrew/<Name von --dist>),
PS5_NUP_PATH (/data/eglantineps5/roms/oot.nup): Ziel fuer UPLOAD_NUP. GAME_NAME (Longshot) fuer die Meldungen,
DEPLOY_MANIFEST ($CONFIG_DIR/deploy-manifest.json) je Projekt (scripts/build.sh).

PS5_HeyListen sucht die .nup an denselben Orten (host/ps5/win32_ps5.c stammt aus PS5_Longshot).

Longshot liest die Spieldaten auf der Konsole direkt aus der .nup und sucht sie an festen Orten (host/ps5/win32_ps5.c von
PS5_Longshot): /data/eglantineps5/roms/<Name des Dumps>.nup, /data/eglantineps5/roms/oot.nup,
/data/lichii/roms/oot/oot.nup, /data/prosperoeden/roms/oot/oot.nup. Das README nennt /data/eglantineps5/roms/oot.nup.

Hochgeladen wird nur, was sich seit dem letzten Deploy auf denselben Host geaendert hat (SHA-1 je Datei in
$CONFIG_DIR/deploy-manifest.json). Geloescht wird auf der Konsole nichts: user/ (Spielstaende), longshot_options.ini,
cache/ und radv-shader-cache/ liegen nicht im gebauten Ordner und bleiben. longshot_env.txt kommt aus dem Build (Profil
der Konsole) und wird ersetzt, wie beim Kopieren laut Upstream-README.
"""
import argparse
import ftplib
import hashlib
import json
import os
import sys
import time

DEFAULT_NUP = "/data/eglantineps5/roms/oot.nup"
KNOWN_NUPS = ("/data/eglantineps5/roms/The Legend of Zelda Ocarina of Time [0400486024dec000][v131072].nup",
              DEFAULT_NUP, "/data/lichii/roms/oot/oot.nup", "/data/prosperoeden/roms/oot/oot.nup")


def connect(host, port):
    f = ftplib.FTP()
    f.connect(host, port, timeout=60)
    f.login()
    f.voidcmd("TYPE I")
    return f


def mkdirs(f, path):
    cur = ""
    for part in path.strip("/").split("/"):
        cur += "/" + part
        try:
            f.mkd(cur)
        except ftplib.all_errors:
            pass


def remote_size(f, path):
    try:
        return f.size(path)
    except ftplib.all_errors:
        return None


def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def progress(done, total, t0, name):
    secs = max(time.time() - t0, 0.001)
    pct = 100.0 * done / total if total else 100.0
    print("  %s: %5.1f%%  %8.1f / %.1f MiB  %.1f MiB/s" % (name, pct, done / (1 << 20), total / (1 << 20),
                                                       done / secs / (1 << 20)), flush=True)


def put_file(f, local, remote, offset=0):
    total = os.path.getsize(local)
    sent = [offset]
    t0 = time.time()
    last = [t0]

    def cb(block):
        sent[0] += len(block)
        if time.time() - last[0] > 10:
            last[0] = time.time()
            progress(sent[0] - offset, total - offset, t0, os.path.basename(local))

    with open(local, "rb") as fh:
        if offset:
            fh.seek(offset)
            f.storbinary("STOR " + remote, fh, blocksize=1 << 20, callback=cb, rest=offset)
        else:
            f.storbinary("STOR " + remote, fh, blocksize=1 << 20, callback=cb)
    if total > (64 << 20):
        progress(sent[0] - offset, total - offset, t0, os.path.basename(local))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", required=True)
    ap.add_argument("--upload-nup")
    a = ap.parse_args()

    host = os.environ.get("PS5_HOST", "").strip()
    if not host or host == "0.0.0.0":
        sys.exit("PS5_HOST ist nicht gesetzt (IP der PS5)")
    port = int(os.environ.get("PS5_FTP_PORT", "2121"))
    title_dir = (os.environ.get("PS5_TITLE_DIR") or
                 "/data/homebrew/" + os.path.basename(os.path.normpath(a.dist))).rstrip("/")
    nup_path = os.environ.get("PS5_NUP_PATH", DEFAULT_NUP).strip() or DEFAULT_NUP
    manifest_path = os.environ.get("DEPLOY_MANIFEST") or os.path.join(os.environ.get("CONFIG_DIR", "/config"), "deploy-manifest.json")
    game = os.environ.get("GAME_NAME", "Longshot")

    try:
        manifest = json.load(open(manifest_path))
    except (OSError, ValueError):
        manifest = {}
    key = "%s:%d%s" % (host, port, title_dir)
    sent_before = {} if os.environ.get("FORCE_DEPLOY", "false") == "true" else manifest.get(key, {})

    try:
        f = connect(host, port)
    except OSError as e:
        sys.exit("keine FTP-Verbindung zu %s:%d (%s). Laeuft der FTP-Server auf der PS5?" % (host, port, e))
    print("  verbunden mit %s:%d" % (host, port), flush=True)

    files = []
    for base, _, names in os.walk(a.dist):
        for n in sorted(names):
            files.append(os.path.join(base, n))
    uploaded = 0
    for local in files:
        rel = os.path.relpath(local, a.dist).replace(os.sep, "/")
        digest = sha1(local)
        remote = title_dir + "/" + rel
        if sent_before.get(rel) == digest and remote_size(f, remote) in (None, os.path.getsize(local)):
            continue
        mkdirs(f, os.path.dirname(remote))
        print("  %s (%.1f MiB)" % (rel, os.path.getsize(local) / (1 << 20)), flush=True)
        put_file(f, local, remote)
        uploaded += 1
        sent_before[rel] = digest
        manifest[key] = sent_before
        with open(manifest_path, "w") as fh:
            json.dump(manifest, fh, indent=1)
    print("  %d von %d Dateien hochgeladen, Rest unveraendert" % (uploaded, len(files)), flush=True)

    if a.upload_nup:
        size = os.path.getsize(a.upload_nup)
        have = remote_size(f, nup_path)
        if have == size:
            print("  .nup liegt schon vollstaendig auf der PS5: %s" % nup_path, flush=True)
        else:
            mkdirs(f, os.path.dirname(nup_path))
            offset = have if have and have < size else 0
            print("  .nup -> %s (%.1f GiB%s)" % (nup_path, size / (1 << 30),
                                                ", fortgesetzt ab %.1f GiB" % (offset / (1 << 30)) if offset else ""),
                  flush=True)
            try:
                put_file(f, a.upload_nup, nup_path, offset)
            except ftplib.error_perm:
                if not offset:
                    raise
                print("  Fortsetzen nicht unterstuetzt, neu ab 0", flush=True)
                f = connect(host, port)
                put_file(f, a.upload_nup, nup_path, 0)
            if remote_size(f, nup_path) not in (None, size):
                sys.exit("  .nup auf der PS5 hat nicht die erwartete Groesse")
    found = [p for p in KNOWN_NUPS if remote_size(f, p)]
    if found:
        print("  .nup fuer %s gefunden: %s" % (game, found[0]), flush=True)
    else:
        print("  ACHTUNG: keine .nup an den Orten, an denen %s sucht:\n    %s\n"
              "  Laut Upstream-README gehoert sie nach %s (UPLOAD_NUP=true kopiert sie dorthin).\n"
              "  Eine vorhandene .nup verschieben:\n"
              "    curl -Q 'MKD /data/eglantineps5' -Q 'MKD /data/eglantineps5/roms' -Q 'RNFR <alter Pfad>' -Q 'RNTO %s' ftp://%s:%d/"
              % (game, "\n    ".join(KNOWN_NUPS), DEFAULT_NUP, DEFAULT_NUP, host, port), flush=True)
    if (title_dir.endswith("/LGSH00001") and game == "Longshot"
            and remote_size(f, "/data/homebrew/PPSA99025/eboot.bin")):
        print("  Hinweis: /data/homebrew/PPSA99025 (Longshot bis v0.1.4) liegt noch auf der PS5. LGSH00001 uebernimmt beim\n"
              "  ersten Start Spielstaende, Einstellungen und Shader-Cache daraus (host/ps5/migrate_id.c von PS5_Longshot)\n"
              "  und legt dort moved_to_LGSH00001.txt ab. Danach kann der alte Ordner weg (Reiter Titles).", flush=True)
    f.quit()
    print("  Deploy fertig: %s. %s vom Startbildschirm oder dem Homebrew-Launcher starten." % (title_dir, game), flush=True)


if __name__ == "__main__":
    main()
