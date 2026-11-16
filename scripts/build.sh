#!/usr/bin/env bash
# ps5-longshot-builder: baut das PS5-Title von heydemoura/PS5_Longshot (PPSA99025) mit der offiziellen Builder-AppImage
# des gewaehlten Releases, ohne Fenster.
#
#   build.sh check    neuestes Release gegen den geladenen Builder und das gebaute Title
#   build.sh update   AppImage des gewaehlten Releases (Standard: neuestes) laden, gegen ihre .sha256 pruefen, entpacken
#   build.sh build    AppRun --cli (ps5/builder/pipeline.py): .nup lesen, Lift, Kompilieren, Linken, Title nach $OUT_DIR
#   build.sh deploy   Title per FTP nach /data/homebrew/PPSA99025 auf der PS5 (scripts/deploy.py)
#   build.sh all      update + build (+ deploy bei AUTO_DEPLOY=true)
#
# Die AppImage wird entpackt statt gemountet (in Docker gibt es kein FUSE). Ihr AppRun startet mit "--cli" die
# pipeline.py des Releases mit deren Optionen (ps5/builder/package.py), und die bringt Python, clang/ld.lld (mit PS5-Ziel),
# ps5-native-tool und das Kit selbst mit.
set -euo pipefail

CONFIG_DIR=${CONFIG_DIR:-/config}
NUP_DIR=${NUP_DIR:-/nup}
OUT_DIR=${OUT_DIR:-/output}
REPO=${LONGSHOT_REPO:-heydemoura/PS5_Longshot}
GH="https://github.com/$REPO"
API="https://api.github.com/repos/$REPO"
NAME=LongshotPS5Builder
TITLE_ID=${TITLE_ID:-PPSA99025}
# Welches Release und welche Konsole: die Auswahl aus der Web-UI ($CONFIG_DIR/ref, $CONFIG_DIR/model), sonst die Variablen.
REF=${LONGSHOT_REF:-latest}
if [[ -s $CONFIG_DIR/ref ]]; then REF=$(tr -d ' \r\n' < "$CONFIG_DIR/ref"); fi
MODEL=${MODEL:-pro}
if [[ -s $CONFIG_DIR/model ]]; then MODEL=$(tr -d ' \r\n' < "$CONFIG_DIR/model"); fi
BUILDERS="$CONFIG_DIR/builder"
WORK="$CONFIG_DIR/work"
TITLE="$OUT_DIR/$TITLE_ID"
CURL=(curl -fsSL --retry 5 --retry-delay 10 --proto '=https')
CURL_API=("${CURL[@]}" -H 'Accept: application/vnd.github+json')
if [[ -n ${GITHUB_TOKEN:-} ]]; then CURL_API+=(-H "Authorization: Bearer $GITHUB_TOKEN"); fi

# Die Builder-Python und der Lift legen Cache und Einstellungen unter $HOME ab: nach /config, nicht in den Container.
export HOME="$CONFIG_DIR/home" XDG_CACHE_HOME="$CONFIG_DIR/home/.cache" XDG_CONFIG_HOME="$CONFIG_DIR/home/.config" \
       XDG_DATA_HOME="$CONFIG_DIR/home/.local/share"

log() { printf '\n==> [%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
die() { printf '\nFEHLER: %s\n' "$*" >&2; exit 1; }

case $MODEL in
    base|pro) ;;
    *) die "MODEL=$MODEL unbekannt (base = PS5/PS5 Slim, pro = PS5 Pro)" ;;
esac

# Speicherbudget in MB: das kleinere von freiem RAM und Speicherlimit des Containers.
cgroup_limit_mb() {
    local limit
    limit=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo max)
    if [[ $limit =~ ^[0-9]+$ ]]; then echo $(( limit / 1024 / 1024 )); fi
}
budget_mb() {
    local avail limit
    avail=$(awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo 2>/dev/null || echo 0)
    limit=$(cgroup_limit_mb)
    if [[ -n $limit ]] && (( avail == 0 || limit < avail )); then avail=$limit; fi
    echo "$avail"
}
# pipeline.py (default_jobs) nimmt Kerne - 1, hoechstens einen Compiler je 1,6 GB freiem Host-RAM; der Lift (nx2/chunks.py)
# einen Worker je 2 GB freiem Host-RAM. Ein Speicherlimit des Containers sehen beide nicht. Mit Limit bekommen sie
# deshalb feste Werte aus dem Limit: --jobs = Budget / 1,6 GB, --lift-jobs 1 unter 10 GB, darueber je 2 GB nach 4 GB fuer
# den Hauptprozess. Ohne Limit entscheidet Upstream.
LIFT_JOBS=${LONGSHOT_LIFT_JOBS:-}
CC_JOBS=${JOBS:-}
if [[ -n $(cgroup_limit_mb) ]]; then
    b=$(budget_mb)
    if [[ -z $CC_JOBS ]]; then
        n=$(( $(nproc) - 1 )); (( n >= 1 )) || n=1
        m=$(( b * 10 / 16 / 1024 )); (( m >= 1 )) || m=1
        CC_JOBS=$(( n < m ? n : m ))
    fi
    if [[ -z $LIFT_JOBS ]]; then
        if (( b < 10240 )); then LIFT_JOBS=1; else LIFT_JOBS=$(( (b - 4096) / 2048 )); fi
    fi
fi

valid_tag() { [[ $1 =~ ^[A-Za-z0-9._+-]{1,80}$ ]]; }

# Neuestes Release: GitHubs /releases/latest (nur veroeffentlichte, keine Vorabversionen). Ohne API (Abfragegrenze: 60
# je Stunde ohne GITHUB_TOKEN) die hoechste v-Version aus den Git-Tags.
latest_tag() {
    local tag
    if ! tag=$({ "${CURL_API[@]}" "$API/releases/latest" | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])'; } 2>/dev/null); then
        tag=$(git ls-remote --tags --refs "$GH.git" 2>/dev/null | sed -n 's#.*refs/tags/\(v[0-9].*\)$#\1#p' | sort -V | tail -1)
        [[ -n $tag ]] || return 1
        echo "  (GitHub-API nicht erreichbar: hoechstes v-Tag $tag aus den Git-Tags)" >&2
    fi
    valid_tag "$tag" || return 1
    echo "$tag"
}

want_tag() {
    if [[ $REF == latest ]]; then
        latest_tag || die "neuestes Release von $REPO nicht ermittelbar (Netz? LONGSHOT_REF auf ein Tag setzen)"
    else
        valid_tag "$REF" || die "LONGSHOT_REF=$REF ist kein gueltiges Tag"
        echo "$REF"
    fi
}

# "<sha256> <name>" der Linux-AppImage eines Releases. Der Name kommt aus den Release-Assets (API), sonst aus dem Schema
# des Release-Workflows (LongshotPS5Builder-<tag>-x86_64.AppImage, .github/workflows/builder-release.yml). Die Pruefsumme
# steht in <name>.sha256, die der Workflow neben die AppImage legt ("<hash>  <name>", ps5/builder/package.py).
release_appimage() {
    local name sums hash
    name=$({ "${CURL_API[@]}" "$API/releases/tags/$1" | NAME=$NAME python3 -c '
import json,os,re,sys
assets=json.load(sys.stdin).get("assets", [])
print(next(a["name"] for a in assets if re.fullmatch(re.escape(os.environ["NAME"]) + r"-.*-x86_64\.AppImage", a["name"])))
'; } 2>/dev/null) || name="$NAME-$1-x86_64.AppImage"
    sums=$("${CURL[@]}" "$GH/releases/download/$1/$name.sha256" 2>/dev/null) || {
        echo "  $name.sha256 von $1 nicht ladbar" >&2; return 1; }
    hash=$(awk -v n="$name" '($2 == n || $2 == "*" n) && $1 ~ /^[0-9a-f]{64}$/ {print $1; exit}' <<<"$sums")
    [[ -n $hash ]] || { echo "  $name.sha256 nennt keine SHA-256 fuer $name" >&2; return 1; }
    echo "$hash $name"
}

appimage_version() { local v=${1#"$NAME"-}; echo "${v%-x86_64.AppImage}"; }

builder_tag() { [[ -f $BUILDERS/current ]] && tr -d ' \r\n' < "$BUILDERS/current" || true; }
apprun() {
    local tag; tag=$(builder_tag)
    [[ -n $tag && -x $BUILDERS/$tag/AppRun ]] && echo "$BUILDERS/$tag/AppRun"
}
built_field() {
    python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' \
        "$CONFIG_DIR/build-info.json" "$1" 2>/dev/null || true
}

stage_update() {
    local tag name tmp want ver line checksum
    tag=$(want_tag)
    log "Builder fuer $tag ($GH/releases/tag/$tag)"
    mkdir -p "$BUILDERS"
    line=$(release_appimage "$tag") ||
        die "Pruefsumme von $tag nicht ladbar oder Release ohne Linux-AppImage: nichts wird ungeprueft entpackt"
    want=${line%% *} name=${line#* }
    ver=$(appimage_version "$name")
    valid_tag "$ver" || die "unerwarteter AppImage-Name: $name"
    if [[ -x $BUILDERS/$ver/AppRun ]]; then
        echo "  schon entpackt: $BUILDERS/$ver"
    else
        tmp="$BUILDERS/.dl"
        rm -rf "$tmp"; mkdir -p "$tmp"
        echo "  lade $name"
        "${CURL[@]}" -o "$tmp/$name" "$GH/releases/download/$tag/$name" || die "Download von $name fehlgeschlagen"
        checksum=$(sha256sum "$tmp/$name" | cut -d' ' -f1)
        [[ $checksum == "$want" ]] || die "Pruefsumme von $name stimmt nicht ($checksum statt $want)"
        echo "  Pruefsumme stimmt ($want)"
        chmod +x "$tmp/$name"
        (cd "$tmp" && "./$name" --appimage-extract >/dev/null) || die "Entpacken der AppImage fehlgeschlagen"
        [[ -x $tmp/squashfs-root/AppRun ]] || die "AppRun fehlt in der AppImage"
        mv "$tmp/squashfs-root" "$BUILDERS/$ver"
        rm -rf "$tmp"
    fi
    echo "$ver" > "$BUILDERS/current"
    local d
    for d in "$BUILDERS"/*/; do   # andere Builder (je einige 100 MB) weg
        d=${d%/}
        if [[ -d $d && $(basename "$d") != "$ver" ]]; then rm -rf "$d"; fi
    done
    echo "  Builder: $ver  ($(du -sh "$BUILDERS/$ver" | cut -f1))"
    log "Teile des Builders pruefen (--cli --check, ohne Spiel)"
    "$BUILDERS/$ver/AppRun" --cli --check --work "$WORK" 2>&1 | readable ||
        die "der Builder laeuft in diesem Container nicht (--check)"
}

find_nup() {
    if [[ -n ${NUP_FILE:-} ]]; then
        [[ -f $NUP_FILE ]] || die "NUP_FILE=$NUP_FILE existiert nicht"
        echo "$NUP_FILE"; return
    fi
    local found
    found=$(find "$NUP_DIR" -maxdepth 2 -type f -iname '*0400486024dec000*.nup' 2>/dev/null | sort | head -1)
    [[ -n $found ]] || found=$(find "$NUP_DIR" -maxdepth 2 -type f -iname '*.nup' 2>/dev/null | sort | head -1)
    echo "$found"
}

# Die @@-Zeilen von pipeline.py (fuer Upstreams Builder-Fenster) lesbar machen: "@@step n of Name" als Ueberschrift,
# "@@progress done total" nur bei jedem vollen Prozent, "@@error" als FEHLER. Exit-Code: der von pipeline.py (PIPESTATUS).
readable() {
    python3 -u -I -c '
import os, re, sys
last = -1
def out(s):
    sys.stdout.write(s + "\n"); sys.stdout.flush()
def line(l):
    global last
    if not l.strip():
        return
    if l.startswith("@@progress "):
        try:
            done, total = (int(x) for x in l.split()[1:3])
            p = done * 100 // total if total else 100
        except ValueError:
            return
        if p != last:
            last = p; out("    %3d %%  (%d von %d)" % (p, done, total))
        return
    if l.startswith("@@step "):
        parts = l.split(" ", 3)
        out("\n--- Schritt %s von %s: %s" % (parts[1], parts[2], parts[3] if len(parts) > 3 else "")); last = -1; return
    if l.startswith("@@error "):
        out("FEHLER: " + l[8:]); return
    if l.startswith("@@done "):
        out("fertig: " + l[7:]); return
    if l.startswith("@@"):
        out(l[2:]); return
    out(l)
buf = b""
while True:
    chunk = os.read(0, 65536)
    if not chunk:
        break
    buf += chunk
    parts = re.split(rb"\r\n|\r|\n", buf)
    buf = parts.pop()
    for part in parts:
        line(part.decode("utf-8", "replace"))
if buf:
    line(buf.decode("utf-8", "replace"))
'
}

# Das Title muss auf einem eingebundenen Pfad liegen, sonst verschwindet es mit dem Container.
out_mounted() {
    mkdir -p "$OUT_DIR" 2>/dev/null || true
    if [[ $(stat -c %d "$OUT_DIR" 2>/dev/null) == "$(stat -c %d / 2>/dev/null)" ]]; then
        die "$OUT_DIR liegt im Container selbst, nicht auf einem eingebundenen Pfad: im Template einen Pfad fuer $OUT_DIR anlegen"
    fi
}

stage_build() {
    local run nup game args
    run=$(apprun) || true
    if [[ -z $run ]]; then stage_update; run=$(apprun); fi
    out_mounted
    mkdir -p "$OUT_DIR" "$WORK"
    nup=$(find_nup)
    if [[ -n $nup ]]; then
        game=$nup
        log "Build $(builder_tag) fuer $MODEL aus $(basename "$nup") nach $TITLE"
    elif [[ -f $WORK/game/exefs/main ]]; then
        # pipeline.py nimmt auch einen Ordner mit dem exefs; den hat ein frueherer Build unter work/game/exefs abgelegt.
        game=$WORK/game/exefs
        log "Build $(builder_tag) fuer $MODEL aus dem exefs eines frueheren Builds (keine .nup unter $NUP_DIR)"
    else
        die "keine .nup unter $NUP_DIR gefunden (NUP_FILE setzen) und kein exefs eines frueheren Builds unter $WORK"
    fi
    args=(--game "$game" --out "$OUT_DIR" --model "$MODEL" --work "$WORK")
    [[ -n $CC_JOBS ]] && args+=(--jobs "$CC_JOBS")
    [[ -n $LIFT_JOBS ]] && args+=(--lift-jobs "$LIFT_JOBS")
    # shellcheck disable=SC2206
    [[ -n ${EXTRA_ARGS:-} ]] && args+=($EXTRA_ARGS)
    if ! "$run" --cli "${args[@]}" 2>&1 | readable; then
        die "der Build ist abgebrochen (Meldung oben). Ein neuer Build setzt fort, wo er war (work bleibt unter $WORK)"
    fi
    [[ -f $TITLE/eboot.bin && -f $TITLE/image.bin ]] || die "eboot.bin oder image.bin fehlt nach dem Build in $TITLE"
    printf '{"tag": "%s", "model": "%s", "time": "%s", "nup": "%s"}\n' "$(builder_tag)" "$MODEL" "$(date '+%d.%m.%Y %H:%M')" \
        "$(basename "${nup:-}")" > "$CONFIG_DIR/build-info.json"
    if [[ -n ${PUID:-} && -n ${PGID:-} ]]; then
        chown -R "$PUID:$PGID" "$TITLE" 2>/dev/null || echo "  Hinweis: Besitzer von $TITLE nicht auf $PUID:$PGID gesetzt"
    fi
    log "Fertig: $TITLE  ($(builder_tag), $MODEL, $(du -sh "$TITLE" | cut -f1)). Auf die PS5 nach /data/homebrew/$TITLE_ID"
}

stage_deploy() {
    [[ -f $TITLE/eboot.bin ]] || die "kein Title unter $TITLE (erst build)"
    local args=(--dist "$TITLE")
    if [[ ${UPLOAD_NUP:-false} == true ]]; then
        local nup; nup=$(find_nup)
        [[ -n $nup ]] || die "UPLOAD_NUP=true, aber keine .nup unter $NUP_DIR"
        args+=(--upload-nup "$nup")
    fi
    log "Deploy nach ${PS5_HOST:-?}:${PS5_FTP_PORT:-2121}/data/homebrew/$TITLE_ID"
    PS5_TITLE_DIR="/data/homebrew/$TITLE_ID" python3 -u /app/scripts/deploy.py "${args[@]}"
    log "Deploy fertig"
}

stage_check() {
    log "Auf Updates pruefen"
    local latest have built built_model tag line want update=false
    latest=$(latest_tag) || die "neuestes Release von $REPO nicht ermittelbar"
    tag=$(want_tag)
    line=$(release_appimage "$tag") || die "Pruefsumme von $tag nicht ladbar oder Release ohne Linux-AppImage"
    want=$(appimage_version "${line#* }")
    have=$(builder_tag); built=$(built_field tag); built_model=$(built_field model)
    [[ -f $TITLE/eboot.bin ]] || built=""
    printf '  %-28s %s\n' "Repository:" "$REPO" "Neuestes Release (latest):" "$latest" "Gewaehlt ($REF):" "$want" \
        "Builder im Container:" "${have:-keiner}" "Gebautes Title:" "${built:-keins}${built:+ ($built_model)}" \
        "Gewaehlte Konsole:" "$MODEL"
    [[ $built == "$want" && $built_model == "$MODEL" ]] || update=true
    if [[ $update == true ]]; then echo "  -> \"Alles bauen\" bringt das Title auf $want ($MODEL)."; else echo "  -> alles aktuell."; fi
    printf '{"time": "%s", "latest": "%s", "want": "%s", "builder": "%s", "built": "%s", "update": %s}\n' \
        "$(date '+%d.%m.%Y %H:%M')" "$latest" "$want" "$have" "$built" "$update" > "$CONFIG_DIR/update-check.json"
}

free_gb() { df -Pk "$1" 2>/dev/null | awk 'NR==2 {print int($4/1024/1024)}'; }

stage=${1:-all}
mkdir -p "$CONFIG_DIR" "$HOME"
IMAGE_REV=${IMAGE_REV:-unbekannt}
echo "Image: ${IMAGE_REV:0:7}  Ref: $REF  Konsole: $MODEL  Compiler: ${CC_JOBS:-auto}  Lift: ${LIFT_JOBS:-auto}  RAM frei: $(awk '/^MemAvailable:/ {print int($2/1024/1024)}' /proc/meminfo) GB  Container-Limit: $(l=$(cgroup_limit_mb); if [[ -n $l ]]; then echo "$l MB"; else echo keins; fi)"
echo "Frei: $(free_gb "$CONFIG_DIR") GB unter $CONFIG_DIR, $(free_gb "$OUT_DIR") GB unter $OUT_DIR (Upstream: rund 6 GB fuer den Build, 1 GB fuer den Builder)"
if [[ $stage == build || $stage == all ]] && (( $(budget_mb) < 8192 )); then
    echo "Hinweis: weniger als 8 GB Speicher frei bzw. erlaubt. Upstream nennt rund 10 GB, der Lift allein haelt etwa 6 GB."
fi
case $stage in
    check) stage_check ;;
    update) stage_update ;;
    build) stage_build ;;
    deploy) stage_deploy ;;
    all)
        stage_update
        stage_build
        if [[ ${AUTO_DEPLOY:-false} == true ]]; then stage_deploy; fi
        ;;
    *) die "unbekannte Stufe: $stage (check|update|build|deploy|all)" ;;
esac
