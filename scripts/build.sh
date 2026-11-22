#!/usr/bin/env bash
# ps5-longshot-builder: baut das PS5-Title des gewaehlten Projekts mit dessen offizieller Builder-AppImage des gewaehlten
# Releases, ohne Fenster:
#   longshot   heydemoura/PS5_Longshot      LongshotPS5Builder-<tag>-x86_64.AppImage    LGSH00001 (bis v0.1.4 PPSA99025)
#   heylisten  cosmicflow2512/PS5_HeyListen  HeyListenPS5Builder-<tag>-x86_64.AppImage   PPSA99026
#   fork       cosmicflow2512/PS5_Longshot_Cosi  LongshotPS5Builder-<tag>-x86_64.AppImage  LGSF00002 (eigene, siehe OWN_TITLE_ID)
#   plus       groovy2312/PS5_Longshot_Plus  PS5LongshotPlusBuilder-<tag>-x86_64.AppImage LGSP00003 (eigene, siehe OWN_TITLE_ID)
# Das Projekt kommt aus der Web-UI ($CONFIG_DIR/project), sonst aus PROJECT (Standard longshot). Builder, Build-Dateien,
# Die Title-ID kommt aus kit.json des Builders (set_title). Release-Wahl und Stand liegen je Projekt getrennt: longshot wie bisher direkt unter $CONFIG_DIR, heylisten unter
# $CONFIG_DIR/heylisten. Konsole und Sprache gelten fuer beide.
#
#   build.sh check    neuestes Release gegen den geladenen Builder und das gebaute Title
#   build.sh update   AppImage des gewaehlten Releases (Standard: neuestes) laden, gegen ihre .sha256 pruefen, entpacken
#   build.sh build    AppRun --cli (ps5/builder/pipeline.py): .nup lesen, Lift, Kompilieren, Linken, Title nach $OUT_DIR
#   build.sh deploy   Title per FTP nach /data/homebrew/<Title-ID> auf der PS5 (scripts/deploy.py): den aktuellen Build
#                     oder einen archivierten ($STATE/deploy_build, Auswahl in der Web-UI)
#   build.sh all      update + build (+ deploy bei AUTO_DEPLOY=true)
#   build.sh saves-status | saves-copy | saves-restore   Spielstaende auf der PS5 (scripts/saves.py)
#   build.sh titles-list | titles-delete | titles-rename  Zelda-Titles auf der PS5 (scripts/titles.py)
#
# Die AppImage wird entpackt statt gemountet (in Docker gibt es kein FUSE). Ihr AppRun startet mit "--cli" die
# pipeline.py des Releases mit deren Optionen (ps5/builder/package.py), und die bringt Python, clang/ld.lld (mit PS5-Ziel),
# ps5-native-tool und das Kit selbst mit.
set -euo pipefail

CONFIG_DIR=${CONFIG_DIR:-/config}
NUP_DIR=${NUP_DIR:-/nup}
OUT_DIR=${OUT_DIR:-/output}
PROJECT=${PROJECT:-longshot}
if [[ -s $CONFIG_DIR/project ]]; then PROJECT=$(tr -d ' \r\n' < "$CONFIG_DIR/project"); fi
ENV_TITLE_ID=${TITLE_ID:-}   # (vor dem case: dort wird TITLE_ID zum Standard des Projekts)
case $PROJECT in
    longshot)
        REPO=${LONGSHOT_REPO:-heydemoura/PS5_Longshot} NAME=LongshotPS5Builder TITLE_ID=PPSA99025
        FIXED_TITLE_ID=${ENV_TITLE_ID:-${LONGSHOT_TITLE_ID:-}} OWN_TITLE_ID=""
        STATE=$CONFIG_DIR REF=${LONGSHOT_REF:-latest} SRC_PREFIX="" GAME_NAME=Longshot GAME_TITLE=Longshot ;;
    heylisten)
        # (PS5_HeyListen: HeyListens Engine mit dem PS5-Port von PS5_Longshot; die Quellen liegen dort unter engine/)
        REPO=${HEYLISTEN_REPO:-cosmicflow2512/PS5_HeyListen} NAME=HeyListenPS5Builder TITLE_ID=PPSA99026
        FIXED_TITLE_ID=${HEYLISTEN_TITLE_ID:-} OWN_TITLE_ID=""
        STATE=$CONFIG_DIR/heylisten REF=${HEYLISTEN_REF:-latest} SRC_PREFIX="engine/" GAME_NAME=HeyListen GAME_TITLE=HeyListen ;;
    fork)
        # (der eigene Fork von PS5_Longshot mit den offenen Pull Requests. Sein Kit heisst seit v3.0.0-ps5.7 wie Upstream
        # LGSH00001, davor PPSA99198: eigene ID, damit er neben Longshot liegt)
        REPO=${FORK_REPO:-cosmicflow2512/PS5_Longshot_Cosi} NAME=LongshotPS5Builder TITLE_ID=LGSF00002
        FIXED_TITLE_ID=${FORK_TITLE_ID:-} OWN_TITLE_ID=LGSF00002
        STATE=$CONFIG_DIR/fork REF=${FORK_REF:-latest} SRC_PREFIX="" GAME_NAME=Longshot-Fork GAME_TITLE=Longshot ;;
    plus)
        # (groovy2312/PS5_Longshot_Plus: ein Fork von PS5_Longshot. Sein Kit heisst PPSA99198 wie der Fork bis ps5.6: eigene ID)
        REPO=${PLUS_REPO:-groovy2312/PS5_Longshot_Plus} NAME=PS5LongshotPlusBuilder TITLE_ID=LGSP00003
        FIXED_TITLE_ID=${PLUS_TITLE_ID:-} OWN_TITLE_ID=LGSP00003
        STATE=$CONFIG_DIR/plus REF=${PLUS_REF:-latest} SRC_PREFIX="" GAME_NAME=Longshot-Plus GAME_TITLE="Longshot Plus" ;;
    *) printf '\nFEHLER: PROJECT=%s unbekannt (longshot, heylisten, fork oder plus)\n' "$PROJECT" >&2; exit 1 ;;
esac
GH="https://github.com/$REPO"
API="https://api.github.com/repos/$REPO"
# Welches Release und welche Konsole: die Auswahl aus der Web-UI ($STATE/ref, $CONFIG_DIR/model), sonst die Variablen.
if [[ -s $STATE/ref ]]; then REF=$(tr -d ' \r\n' < "$STATE/ref"); fi
MODEL=${MODEL:-pro}
if [[ -s $CONFIG_DIR/model ]]; then MODEL=$(tr -d ' \r\n' < "$CONFIG_DIR/model"); fi
# Spielsprache: language.txt im Title-Ordner (host/nn_applet.c desired_language: die erste Zeile, die keine Leerzeile und
# kein Kommentar ist und einen der 16 Codes nennt). Ab v0.1.4 folgt das Title ohne Code der Sprache der Konsole (Englisch,
# wenn das Spiel sie nicht hat) und laesst sie im Menue (Game language) waehlen; bis v0.1.3 hiess ohne Code Englisch (US).
# LANGUAGE leer oder "auto": keine language.txt, also der Konsole folgen bzw. was auf der PS5 schon gewaehlt ist.
LANGUAGE=${LANGUAGE-}
if [[ -s $CONFIG_DIR/language ]]; then LANGUAGE=$(tr -d ' \r\n' < "$CONFIG_DIR/language"); fi
[[ $LANGUAGE == auto ]] && LANGUAGE=""
# Speicher fuer den Build in GB (pipeline.py --memory, ab v0.1.5). Leer: das Speicherlimit des Containers abzueglich 1 GB.
MEMORY_GB=${MEMORY_GB:-}
LANGUAGES="en-US en-GB fr fr-CA de it es es-419 pt-BR nl pl ru ja ko zh-Hans zh-Hant"
BUILDERS="$STATE/builder"
# Jeder fertige Build wird nach $OUT_DIR/archive/<Projekt>/<Builder-Version>-<Konsole>/ kopiert (ARCHIVE_BUILDS=false:
# nicht). Welcher Build auf die PS5 kommt: $STATE/deploy_build ("current" oder ein Archivname, Auswahl in der Web-UI).
ARCHIVE_DIR="$OUT_DIR/archive/$PROJECT"
ARCHIVE_BUILDS=${ARCHIVE_BUILDS:-true}
DEPLOY_BUILD=current
if [[ -s $STATE/deploy_build ]]; then DEPLOY_BUILD=$(tr -d ' \r\n' < "$STATE/deploy_build"); fi
# Builder anderer Releases beim Update behalten (Standard; je einige 100 MB), damit ein Wechsel zurueck nichts neu laedt.
KEEP_BUILDERS=${KEEP_BUILDERS:-true}
if [[ -s $CONFIG_DIR/keep_builders ]]; then KEEP_BUILDERS=$(tr -d ' \r\n' < "$CONFIG_DIR/keep_builders"); fi
# build-info.json, aus der title_extras die des Titles schreibt: beim Deploy eines archivierten Builds dessen eigene.
BUILD_INFO="$STATE/build-info.json"
WORK="$STATE/work"
# Title-ID des letzten Builds ($STATE/title_id, von stage_build geschrieben), sonst der Standard des Projekts. Ein Build
# nimmt die feste (<PROJEKT>_TITLE_ID, bei longshot auch TITLE_ID), sonst die eigene des Projekts (OWN_TITLE_ID: fork und
# plus, deren Kits sonst mit Longshot bzw. dem alten Fork-Ordner zusammenfielen), sonst die des Kits (set_title_from_kit).
if [[ -n $FIXED_TITLE_ID ]]; then TITLE_ID=$FIXED_TITLE_ID
elif [[ -s $STATE/title_id ]]; then TITLE_ID=$(tr -d ' \r\n' < "$STATE/title_id"); fi
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
if [[ -n $LANGUAGE && " $LANGUAGES " != *" $LANGUAGE "* ]]; then
    die "LANGUAGE=$LANGUAGE unbekannt ($LANGUAGES)"
fi

# Lossless Scaling (Frame Generation des Forks, PR #21): die eigene Lossless.dll in den Title-Ordner, wo das Spiel sie sucht
# (/app0/lossless/Lossless.dll, gpu/vk/vk_framegen.cpp). LOSSLESS_DLL: ihr Pfad im Container (Unraid: eine Datei unter
# einem eingebundenen Pfad). Bei jedem Build und Deploy; ohne Datei nichts.
copy_lossless() {
    [[ $PROJECT == fork && -d $TITLE ]] || return 0   # (nur der Fork hat Lossless Scaling)
    local dll=${LOSSLESS_DLL:-/lossless/Lossless.dll}   # (Standard: der Ordner "Lossless Scaling" des Templates, nach /lossless)
    if [[ ! -f $dll ]]; then
        echo "  Hinweis: keine Lossless.dll unter $dll: ohne Lossless Scaling. Im Container unter Edit einen Pfad anlegen:"
        echo "           Container-Pfad /lossless, Host-Pfad der Ordner mit der Lossless.dll (z. B. /mnt/user/PS5), Read Only"
        return 0
    fi
    LOSSLESS_DLL=$dll
    mkdir -p "$TITLE/lossless"
    cp -f "$LOSSLESS_DLL" "$TITLE/lossless/Lossless.dll"
    echo "  Lossless.dll: $LOSSLESS_DLL -> $TITLE/lossless/Lossless.dll ($(du -h "$LOSSLESS_DLL" | cut -f1))"
}

# AMD FSR 4 des Forks (PR #41, gpu/vk/vk_fsr4.cpp): der PS5-Code sucht fertige Shader und Gewichte unter
# /app0/fsr4/lite/<tier>/ bzw. /app0/fsr4/int8/<tier>/ (docs/PS5_FSR4.md). Sie kommen aus dem Release von
# Mob1K7105/beamng-fsr4-linux, aus dem auch der PS5-Code stammt: einmal laden, gegen die feste SHA-256 und die
# SHA256SUMS im Archiv pruefen, unter $CONFIG_DIR/fsr4 behalten. FSR4_ASSETS: lite (Standard), all (dazu navi2 als int8),
# off. Die 8K-Stufen (t4320) kommen nicht mit.
FSR4_VERSION=0.3.0
FSR4_SHA256=d9cdd75f996b8ac84d3679849d912d68fdd22dd821cead291d6a1be1be2a88c3
fsr4_fetch() {
    local dir=$CONFIG_DIR/fsr4/$FSR4_VERSION
    [[ -f $dir/.ok ]] && { echo "$dir"; return 0; }
    local tmp; tmp=$(mktemp -d)
    local url=https://github.com/Mob1K7105/beamng-fsr4-linux/releases/download/v$FSR4_VERSION/beamng-fsr4-linux.tar.gz
    echo "  FSR 4: lade $url" >&2
    if ! "${CURL[@]}" -o "$tmp/a.tgz" "$url"; then rm -rf "$tmp"; echo "  FSR 4: Download fehlgeschlagen" >&2; return 1; fi
    if [[ $(sha256sum "$tmp/a.tgz" | cut -d' ' -f1) != "$FSR4_SHA256" ]]; then
        rm -rf "$tmp"; echo "  FSR 4: SHA-256 des Archivs passt nicht, nichts uebernommen" >&2; return 1; fi
    tar xzf "$tmp/a.tgz" -C "$tmp"
    local src=$tmp/beamng-fsr4-linux-$FSR4_VERSION
    if ! (cd "$src" && grep -E '  assets/(lite|navi2)/' SHA256SUMS | sha256sum -c --quiet); then
        rm -rf "$tmp"; echo "  FSR 4: SHA256SUMS im Archiv passen nicht, nichts uebernommen" >&2; return 1; fi
    rm -rf "$dir"; mkdir -p "$dir"
    cp -r "$src/assets/lite" "$src/assets/navi2" "$src/assets/NOTICE.md" "$src/notices/AMD-SDK-LICENSE.md" "$dir/"
    touch "$dir/.ok"; rm -rf "$tmp"
    echo "$dir"
}
copy_fsr4() {
    [[ $PROJECT == fork && -d $TITLE ]] || return 0   # (nur der Fork hat FSR 4 fuer die PS5)
    local mode=${FSR4_ASSETS:-lite}
    case $mode in
        off) rm -rf "$TITLE/fsr4"; echo "  FSR 4: aus (FSR4_ASSETS=off)"; return 0 ;;
        lite|all) ;;
        *) echo "  Hinweis: FSR4_ASSETS=$mode unbekannt (lite, all, off): ohne FSR 4"; return 0 ;;
    esac
    local dir; dir=$(fsr4_fetch) || { echo "  Hinweis: ohne FSR 4 weiter"; return 0; }
    rm -rf "$TITLE/fsr4"; mkdir -p "$TITLE/fsr4/lite"
    local t
    for t in t1080_m0 t1080_m1 t2160_m0 t2160_m1; do cp -r "$dir/lite/$t" "$TITLE/fsr4/lite/"; done
    if [[ $mode == all ]]; then
        mkdir -p "$TITLE/fsr4/int8"
        for t in t1080_m0 t1080_m1 t2160_m0 t2160_m1; do cp -r "$dir/navi2/$t" "$TITLE/fsr4/int8/"; done
    fi
    cp -f "$dir/NOTICE.md" "$dir/AMD-SDK-LICENSE.md" "$TITLE/fsr4/"
    echo "  FSR 4: beamng-fsr4-linux v$FSR4_VERSION ($mode) -> $TITLE/fsr4 ($(du -sh "$TITLE/fsr4" | cut -f1))"
}

# Was der Title ueber sich mitbringt, fuer scripts/titles.py auf der PS5: build-info.json (Projekt, Repository, Release,
# Konsole, Zeit) und der angezeigte Name: aus $STATE/title_name (in der Web-UI unter "Titles auf der PS5" umbenannt), sonst
# "<Spiel> <Version>" (AUTO_TITLE_NAME=false: der Name des Kits bleibt).
title_extras() {
    [[ -d $TITLE ]] || return 0
    if [[ -f $BUILD_INFO ]]; then
        PROJECT=$PROJECT REPO=$REPO python3 - "$BUILD_INFO" "$TITLE/build-info.json" <<'PY' || true
import json, os, sys
j = json.load(open(sys.argv[1]))
j.update(project=os.environ["PROJECT"], repo=os.environ["REPO"])
open(sys.argv[2], "w").write(json.dumps(j) + "\n")
PY
    fi
    # (Name: der in der Web-UI gegebene, sonst Projekt und Version des Builds, z. B. "Longshot ps5.7")
    local param=$TITLE/sce_sys/param.json name="" tag
    [[ -s $STATE/title_name ]] && name=$(head -n1 "$STATE/title_name" | tr -d '\r')
    if [[ -z $name && ${AUTO_TITLE_NAME:-true} == true ]]; then
        tag=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("tag", ""))' "$BUILD_INFO" 2>/dev/null || true)
        [[ -n $tag ]] && name="$GAME_TITLE $(short_version "$tag")"
    fi
    [[ -n $name && -f $param ]] || return 0
    TITLE_NAME=$name python3 - "$param" <<'PY' && echo "  angezeigter Name: $name"
import json, os, sys
p = sys.argv[1]
j = json.load(open(p, encoding="utf-8"))
lp = j.setdefault("localizedParameters", {})
lp.setdefault("defaultLanguage", "en-US")
for k in [k for k, v in lp.items() if isinstance(v, dict)] or [lp["defaultLanguage"]]:
    lp.setdefault(k, {})["titleName"] = os.environ["TITLE_NAME"]
open(p, "w", encoding="utf-8", newline="\n").write(json.dumps(j, indent=2, ensure_ascii=False) + "\n")
PY
}

# language.txt in das Title schreiben, im Format, das das Spiel selbst beim ersten Start anlegt (host/nn_applet.c). Ohne
# feste Sprache keine Datei (eine von frueher geschriebene geht weg): dann bleibt auf der PS5, was dort steht, und eine
# neue Installation folgt der Konsole. Das Deploy laedt language.txt nur, wenn sie sich seit dem letzten Deploy geaendert
# hat; eine im Spielmenue gewaehlte Sprache bleibt also, solange hier nichts anderes gewaehlt wird.
write_language() {
    [[ -d $TITLE ]] || return 0
    if [[ -z $LANGUAGE ]]; then
        rm -f "$TITLE/language.txt"
        echo "  Spielsprache: der Konsole folgen (keine language.txt im Title)"
        return 0
    fi
    {
        printf '# The game%ss language. Change the line below to one of the codes listed here, save, and start the game again.\n\n%s\n\n' "'" "$LANGUAGE"
        printf '# %s\n' $LANGUAGES
    } > "$TITLE/language.txt"
    echo "  Spielsprache: $LANGUAGE ($TITLE/language.txt)"
}

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
# pipeline.py liest den freien Speicher aus /proc/meminfo (MemAvailable) und sieht ein Speicherlimit des Containers nicht.
# Ab v0.1.5 hat es --memory GB: die Uebersetzung (--lift-jobs) und die Compiles halten sich daran (ps5/builder/README.md,
# "Memory"; mindestens 2 GB). Mit Limit bekommt es deshalb --memory aus dem Limit, und Upstream verteilt selbst. Das Budget
# zaehlt nur die Prozesse des Builds; das Limit des Containers zaehlt mehr (Web-UI, Datei-Cache der geschriebenen C-Dateien).
# Mit Limit - 1 GB hat der OOM-Killer bei 8 GB Limit einen Prozess der Uebersetzung beendet (4 Worker). Deshalb: Limit - 3 GB,
# unter 10 GB Limit hoechstens 4 GB, denn unter 5 GB uebersetzt Upstream in einem Prozess, ohne Worker.
# Aeltere Builder ohne --memory bekommen feste Werte aus dem Limit: --jobs = Budget / 1,6 GB (default_jobs: ein Compiler
# je 1,6 GB), --lift-jobs 1 unter 10 GB, darueber je 2 GB nach 4 GB fuer den Hauptprozess.
LIFT_JOBS=${LONGSHOT_LIFT_JOBS:-}
CC_JOBS=${JOBS:-}
USER_LIFT_JOBS=$LIFT_JOBS USER_CC_JOBS=$CC_JOBS
if [[ -z $MEMORY_GB && -n $(cgroup_limit_mb) ]]; then
    MEMORY_GB=$(( $(cgroup_limit_mb) / 1024 - 3 ))
    if (( $(cgroup_limit_mb) < 10240 && MEMORY_GB > 4 )); then MEMORY_GB=4; fi
    (( MEMORY_GB >= 2 )) || MEMORY_GB=2
fi
if [[ -n $MEMORY_GB && ! $MEMORY_GB =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "FEHLER: MEMORY_GB=$MEMORY_GB ist keine Zahl" >&2; exit 1
fi
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
        "$STATE/build-info.json" "$1" 2>/dev/null || true
}

# Title-ID des Kits im geladenen Builder (kit.json "title_id", aus ps5/sce_sys/param.json): bei PS5_Longshot bis v0.1.4
# PPSA99025, ab v0.1.5 LGSH00001 (Upstream 9bc1211c: PPSA99025 ist auch ein anderes Homebrew). Fuer den Build.
kit_title_id() {
    local tag kit; tag=$(builder_tag)
    [[ -n $tag ]] || return 0
    kit=$(find "$BUILDERS/$tag" -maxdepth 5 -name kit.json -print -quit 2>/dev/null)
    [[ -n $kit ]] || return 0
    python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("title_id", ""))' "$kit" 2>/dev/null || true
}
set_title_from_kit() {
    local id=$FIXED_TITLE_ID
    [[ -n $id ]] || id=$OWN_TITLE_ID
    [[ -n $id ]] || id=$(kit_title_id)
    [[ -n $id ]] || return 0
    [[ $id =~ ^[A-Z]{4}[0-9]{5}$ ]] || die "unerwartete Title-ID: $id (vier Grossbuchstaben, fuenf Ziffern)"
    TITLE_ID=$id TITLE="$OUT_DIR/$id"
}

# Der Ordner, den pipeline.py macht (<out>/<ID des Kits>), kommt aus einem eigenen Zwischenordner je Projekt nach
# $OUT_DIR/<Title-ID>: so ueberschreibt kein Projekt den Ordner eines anderen, dessen Kit dieselbe ID hat. Weicht die ID
# vom Kit ab, bekommt param.json die neue in titleId, contentId (der ID-Teil, das Etikett behaelt PS5LONGSHOT, daran
# erkennt host/ps5/migrate_id.c Longshots Ordner) und conceptId (ihre Ziffern). Das ist dieselbe Aenderung, mit der
# PS5_Longshot selbst die ID gewechselt hat (9bc1211c, nur ps5/sce_sys/param.json); eboot.bin wird ohne ID signiert
# (pipeline.py title: "self --sign" ohne Content-ID), und pipeline.py schreibt param.json nach dem Signieren selbst.
place_title() {
    local stage=$1 kit_id src
    kit_id=$(kit_title_id)
    src="$stage/${kit_id:-$TITLE_ID}"
    [[ -f $src/eboot.bin ]] || { src=$(dirname "$(find "$stage" -mindepth 2 -maxdepth 2 -name eboot.bin -print -quit)"); }
    [[ -n $src && -f $src/eboot.bin ]] || die "kein Title-Ordner mit eboot.bin unter $stage nach dem Build"
    rm -rf "$TITLE.old"
    [[ -d $TITLE ]] && mv "$TITLE" "$TITLE.old"
    mv "$src" "$TITLE"
    rm -rf "$TITLE.old"
    local param=$TITLE/sce_sys/param.json
    [[ -f $param ]] || return 0
    TID=$TITLE_ID python3 -I - "$param" <<'PY'
import json, os, re, sys
p, tid = sys.argv[1], os.environ["TID"]
j = json.load(open(p, encoding="utf-8"))
old = j.get("titleId")
if old != tid:
    j["titleId"] = tid
    cid = j.get("contentId", "")
    j["contentId"] = re.sub(r"-[A-Z]{4}[0-9]{5}_", "-%s_" % tid, cid) if re.search(r"-[A-Z]{4}[0-9]{5}_", cid) else cid
    if "conceptId" in j:
        j["conceptId"] = tid[4:]
    open(p, "w", encoding="utf-8", newline="\n").write(json.dumps(j, indent=2, ensure_ascii=False) + "\n")
    print("  Title-ID: %s statt %s des Kits (param.json: titleId, contentId %s, conceptId %s)" % (tid, old, j["contentId"], j.get("conceptId")))
PY
}

# Kurzform der Version fuer den angezeigten Namen: v3.0.0-ps5.7 -> ps5.7, v0.3.2-plus -> v0.3.2, sonst das Tag.
short_version() {
    local t=$1
    if [[ $t =~ -(ps5\.[0-9]+)$ ]]; then echo "${BASH_REMATCH[1]}"; return; fi
    echo "${t%-plus}"
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
    for d in "$BUILDERS"/*/; do   # andere Builder (je einige 100 MB) weg, wenn KEEP_BUILDERS=false
        d=${d%/}
        [[ -d $d && $(basename "$d") != "$ver" ]] || continue
        if [[ $KEEP_BUILDERS == true ]]; then echo "  behalten: Builder $(basename "$d")"; else rm -rf "$d"; fi
    done
    check_zbic "$BUILDERS/$ver"
    echo "  Builder: $ver  ($(du -sh "$BUILDERS/$ver" | cut -f1)), Title-ID des Kits: $(kit_title_id)"
    log "Teile des Builders pruefen (--cli --check, ohne Spiel)"
    "$BUILDERS/$ver/AppRun" --cli --check --work "$WORK" 2>&1 | readable ||
        die "der Builder laeuft in diesem Container nicht (--check)"
}

# ZBIC: die main einer .nup von Firmware 22+ ist ZBIC-komprimiert; nx2/zbic.py entpackt sie mit third_party/zbic/zbic.so
# im Kit. Seit v0.1.3 baut PS5_Longshot die Bibliothek mit dem LLVM des Kits in die AppImage, und --check prueft sie mit
# einem Selbsttest (ps5/builder/zbic_check.c, Commits 46f7bb26 und 318696dc); dann ist hier nichts zu tun. Nur wenn ein
# Builder keine zbic.so hat (PS5_Longshot v0.1.0, vielleicht aeltere Releases anderer Projekte), wird sie wie frueher aus
# third_party/zbic desselben Tags mit gcc gebaut. Upstream hat eine mit GCC 11 gebaute als defekt gemessen (sie entpackte
# keinen ZBIC-Frame); bricht der Build in "Reading the game's program" ab, ein neueres Release waehlen.
check_zbic() {
    local dir=$1 tag py zdir tmp f
    tag=$(basename "$dir")
    py=$(find "$dir" -path '*/src/nx2/zbic.py' -print -quit 2>/dev/null)
    [[ -n $py ]] || return 0
    zdir="$(dirname "$(dirname "$py")")/third_party/zbic"
    [[ -f $zdir/zbic.so ]] && return 0
    echo "  WARNUNG: dieser Builder hat keine zbic.so (PS5_Longshot bringt sie ab v0.1.3 mit). Notbau mit gcc; Upstream hat"
    echo "           eine GCC-gebaute als defekt gemessen. Liest der Build die .nup nicht, ein neueres Release waehlen."
    tmp=$(mktemp -d)
    for f in zstd.c zstd.h zstd_errors.h zbic_api.c; do
        "${CURL[@]}" -o "$tmp/$f" "https://raw.githubusercontent.com/$REPO/$tag/${SRC_PREFIX}third_party/zbic/$f" ||
            { rm -rf "$tmp"; die "third_party/zbic/$f von $tag nicht ladbar"; }
    done
    mkdir -p "$zdir"
    gcc -O2 -shared -fPIC -DZSTD_ZBIC_SUPPORT=1 -I "$tmp" -o "$zdir/zbic.so.new" "$tmp/zstd.c" "$tmp/zbic_api.c" ||
        { rm -rf "$tmp"; die "zbic.so nicht gebaut"; }
    mv "$zdir/zbic.so.new" "$zdir/zbic.so"
    rm -rf "$tmp"
    echo "  zbic.so gebaut: $zdir/zbic.so"
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

# OOM-Kills im Container (cgroup v2: memory.events, Zeile oom_kill). Leer, wo es die Datei nicht gibt.
MEMORY_EVENTS=${MEMORY_EVENTS:-/sys/fs/cgroup/memory.events}
oom_kills() { awk '$1 == "oom_kill" {print $2}' "$MEMORY_EVENTS" 2>/dev/null || true; }
# Prozesse des Builders (ihr Programm oder ihre Argumente liegen unter $1): PIDs und ihre CPU-Zeit in Ticks zusammen.
builder_pids() {
    local p cmd
    for p in /proc/[0-9]*; do
        cmd=$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null) || continue
        [[ $cmd == *"$1"* ]] && echo "${p#/proc/}"
    done
}
builder_ticks() {
    local p t=0 v
    for p in $(builder_pids "$1"); do
        # (/proc/<pid>/stat: nach "pid (Name) " sind utime und stime das 12. und 13. Feld)
        v=$(sed 's/^.*) //' "/proc/$p/stat" 2>/dev/null | awk '{print $12 + $13}') || continue
        t=$(( t + ${v:-0} ))
    done
    echo "$t"
}
# Waechter: Beendet der OOM-Killer einen Prozess des Builds, kann der Rest haengen bleiben (beobachtet: der Haupt-lift.py weg,
# seine Worker warten ewig, pipeline.py wartet auf deren Ausgabe). Nach einem OOM-Kill: steht die CPU-Zeit aller
# Builder-Prozesse STALL_SECS lang still, werden sie beendet. Ein Worker, den Upstream selbst ersetzt, rechnet weiter und
# bleibt unberuehrt. Exit 0: nichts zu tun; 99: abgebrochen.
watch_build() {
    local pid=$1 dir=$2 before=$3 stall=${STALL_SECS:-300} poll=${WATCH_POLL_SECS:-20} now last=-1 still=0 p
    while kill -0 "$pid" 2>/dev/null; do
        sleep "$poll"
        now=$(oom_kills)
        [[ -n $before && -n $now ]] && (( now > before )) || continue
        p=$(builder_ticks "$dir")
        if (( p == last )); then still=$(( still + poll )); else still=0; last=$p; fi
        if (( still >= stall )); then
            echo ""
            echo "FEHLER: der OOM-Killer hat einen Prozess des Builds beendet (memory.events oom_kill $before -> $now), und"
            echo "  seit $stall s rechnet keiner mehr: der Rest haengt. Die Prozesse des Builders werden beendet."
            for p in $(builder_pids "$dir"); do kill -TERM "$p" 2>/dev/null || true; done
            sleep 5
            for p in $(builder_pids "$dir"); do kill -KILL "$p" 2>/dev/null || true; done
            return 99
        fi
    done
    return 0
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
    check_zbic "$BUILDERS/$(builder_tag)"
    set_title_from_kit
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
    local stage="$OUT_DIR/.build-$PROJECT"   # (Zwischenordner, place_title)
    mkdir -p "$stage"
    args=(--game "$game" --out "$stage" --model "$MODEL" --work "$WORK")
    if "$run" --cli --help 2>/dev/null | grep -q -- '--memory'; then
        # (v0.1.5+: Upstream verteilt Uebersetzung und Compiles im Budget selbst; JOBS/LONGSHOT_LIFT_JOBS nur, wenn gesetzt)
        [[ -n $MEMORY_GB ]] && args+=(--memory "$MEMORY_GB")
        [[ -n $USER_CC_JOBS ]] && args+=(--jobs "$USER_CC_JOBS")
        [[ -n $USER_LIFT_JOBS ]] && args+=(--lift-jobs "$USER_LIFT_JOBS")
    else
        [[ -n $CC_JOBS ]] && args+=(--jobs "$CC_JOBS")
        [[ -n $LIFT_JOBS ]] && args+=(--lift-jobs "$LIFT_JOBS")
    fi
    # shellcheck disable=SC2206
    [[ -n ${EXTRA_ARGS:-} ]] && args+=($EXTRA_ARGS)
    echo "  pipeline.py ${args[*]}"
    local oom_before code=0 watch=0 wpid
    oom_before=$(oom_kills)
    "$run" --cli "${args[@]}" 2>&1 | readable &
    wpid=$!
    watch_build "$wpid" "$(dirname "$run")/" "$oom_before" || watch=$?
    # (abgebrochen: auch das Lesende der Pipe beenden; haelt noch ein Kindprozess ausserhalb des Builders die Ausgabe offen,
    # kaeme sonst nie ein Ende)
    if (( watch == 99 )); then kill -TERM "$wpid" 2>/dev/null || true; fi
    wait "$wpid" || code=$?
    if (( watch == 99 )); then
        die "Speicher: der Build hat das Limit des Containers ueberschritten (Limit: $(l=$(cgroup_limit_mb); echo "${l:-keins}${l:+ MB}"), --memory ${MEMORY_GB:-auto}). MEMORY_GB kleiner setzen (unter 5: Uebersetzung in einem Prozess) oder das Limit erhoehen. Ein neuer Build setzt fort, wo er war"
    fi
    if (( code != 0 )); then
        if [[ -n $oom_before && $(oom_kills) -gt $oom_before ]]; then
            echo "  (der OOM-Killer hat waehrend des Builds einen Prozess beendet: memory.events oom_kill $oom_before -> $(oom_kills); MEMORY_GB kleiner setzen)"
        fi
        die "der Build ist abgebrochen (Meldung oben). Ein neuer Build setzt fort, wo er war (work bleibt unter $WORK)"
    fi
    place_title "$stage"
    [[ -f $TITLE/eboot.bin && -f $TITLE/image.bin ]] || die "eboot.bin oder image.bin fehlt nach dem Build in $TITLE"
    write_language
    copy_lossless
    copy_fsr4
    printf '{"tag": "%s", "model": "%s", "time": "%s", "nup": "%s", "title_id": "%s"}\n' "$(builder_tag)" "$MODEL" \
        "$(date '+%d.%m.%Y %H:%M')" "$(basename "${nup:-}")" "$TITLE_ID" > "$STATE/build-info.json"
    echo "$TITLE_ID" > "$STATE/title_id"   # (Deploy, Web-UI, saves.py und titles.py nehmen diese ID)
    title_extras
    if [[ -n ${PUID:-} && -n ${PGID:-} ]]; then
        chown -R "$PUID:$PGID" "$TITLE" 2>/dev/null || echo "  Hinweis: Besitzer von $TITLE nicht auf $PUID:$PGID gesetzt"
    fi
    archive_build
    log "Fertig: $TITLE  ($(builder_tag), $MODEL, $(du -sh "$TITLE" | cut -f1)). Auf die PS5 nach /data/homebrew/$TITLE_ID"
    if [[ $PROJECT == longshot && $TITLE_ID != PPSA99025 && -f $OUT_DIR/PPSA99025/eboot.bin ]]; then
        echo "  Hinweis: $OUT_DIR/PPSA99025 ist ein Longshot-Build von v0.1.4 oder aelter. Das neue Title $TITLE_ID uebernimmt"
        echo "  beim ersten Start Spielstaende, Einstellungen und Shader-Cache aus /data/homebrew/PPSA99025 auf der PS5"
        echo "  (host/ps5/migrate_id.c). Den alten Ordner danach auf der PS5 (Reiter Titles) und hier von Hand loeschen."
    fi
}

# Kopie des fertigen Builds nach $ARCHIVE_DIR/<Builder-Version>-<Konsole>/ (ersetzt einen gleichnamigen), daneben seine
# build-info.json. Erst in einen versteckten Ordner, dann umbenennen: ein halb kopiertes Archiv taucht nie in der Liste
# auf. Scheitert die Kopie (Platz), bleibt der Build trotzdem gueltig.
archive_build() {
    [[ $ARCHIVE_BUILDS == true ]] || return 0
    local name dest tmp
    name="$(builder_tag)-$MODEL"
    valid_tag "$name" || { echo "  Hinweis: kein gueltiger Archivname ($name), nicht archiviert"; return 0; }
    dest="$ARCHIVE_DIR/$name"; tmp="$ARCHIVE_DIR/.$name.tmp"
    mkdir -p "$ARCHIVE_DIR"; rm -rf "$tmp"; mkdir -p "$tmp"
    if ! cp -a "$TITLE" "$tmp/$TITLE_ID" || ! cp "$STATE/build-info.json" "$tmp/build-info.json"; then
        rm -rf "$tmp"
        echo "  Hinweis: Archivieren nach $dest fehlgeschlagen (Platz unter $OUT_DIR?). Der Build selbst ist fertig."
        return 0
    fi
    rm -rf "$dest"; mv "$tmp" "$dest"
    if [[ -n ${PUID:-} && -n ${PGID:-} ]]; then chown -R "$PUID:$PGID" "$dest" 2>/dev/null || true; fi
    echo "  archiviert: $dest ($(du -sh "$dest" | cut -f1))"
}

stage_deploy() {
    if [[ -n $DEPLOY_BUILD && $DEPLOY_BUILD != current ]]; then
        valid_tag "$DEPLOY_BUILD" && [[ $DEPLOY_BUILD != .* ]] || die "deploy_build=$DEPLOY_BUILD ist kein gueltiger Archivname"
        # (Sprache, Lossless.dll, FSR 4 und Name kommen wie beim aktuellen Build in den Ordner, den das Deploy kopiert)
        # (die Title-ID des archivierten Builds: aus seiner build-info.json, sonst der Unterordner mit eboot.bin)
        local aid d
        aid=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("title_id", ""))' \
            "$ARCHIVE_DIR/$DEPLOY_BUILD/build-info.json" 2>/dev/null || true)
        if [[ -z $aid ]]; then
            for d in "$ARCHIVE_DIR/$DEPLOY_BUILD"/*/eboot.bin; do [[ -f $d ]] && { aid=$(basename "$(dirname "$d")"); break; }; done
        fi
        [[ $aid =~ ^[A-Z]{4}[0-9]{5}$ ]] && TITLE_ID=$aid
        TITLE="$ARCHIVE_DIR/$DEPLOY_BUILD/$TITLE_ID" BUILD_INFO="$ARCHIVE_DIR/$DEPLOY_BUILD/build-info.json"
        [[ -f $TITLE/eboot.bin ]] || die "archivierter Build $DEPLOY_BUILD fehlt unter $TITLE (in der Web-UI einen anderen waehlen)"
        log "Auf die PS5: archivierter Build $DEPLOY_BUILD ($TITLE)"
    else
        [[ -f $TITLE/eboot.bin ]] || die "kein Title unter $TITLE (erst build)"
        log "Auf die PS5: aktueller Build ($TITLE)"
    fi
    write_language
    copy_lossless
    copy_fsr4
    title_extras
    local args=(--dist "$TITLE")
    if [[ ${UPLOAD_NUP:-false} == true ]]; then
        local nup; nup=$(find_nup)
        [[ -n $nup ]] || die "UPLOAD_NUP=true, aber keine .nup unter $NUP_DIR"
        args+=(--upload-nup "$nup")
    fi
    log "Deploy nach ${PS5_HOST:-?}:${PS5_FTP_PORT:-2121}/data/homebrew/$TITLE_ID"
    PS5_TITLE_DIR="/data/homebrew/$TITLE_ID" GAME_NAME=$GAME_NAME DEPLOY_MANIFEST="$STATE/deploy-manifest.json" python3 -u /app/scripts/deploy.py "${args[@]}"
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
    printf '  %-28s %s\n' "Projekt:" "$PROJECT ($TITLE_ID)" "Repository:" "$REPO" "Neuestes Release (latest):" "$latest" "Gewaehlt ($REF):" "$want" \
        "Builder im Container:" "${have:-keiner}" "Gebautes Title:" "${built:-keins}${built:+ ($built_model)}" \
        "Gewaehlte Konsole:" "$MODEL"
    [[ $built == "$want" && $built_model == "$MODEL" ]] || update=true
    if [[ $update == true ]]; then echo "  -> \"Alles bauen\" bringt das Title auf $want ($MODEL)."; else echo "  -> alles aktuell."; fi
    printf '{"time": "%s", "latest": "%s", "want": "%s", "builder": "%s", "built": "%s", "update": %s}\n' \
        "$(date '+%d.%m.%Y %H:%M')" "$latest" "$want" "$have" "$built" "$update" > "$STATE/update-check.json"
}

free_gb() { df -Pk "$1" 2>/dev/null | awk 'NR==2 {print int($4/1024/1024)}'; }

stage=${1:-all}
mkdir -p "$CONFIG_DIR" "$STATE" "$HOME"
IMAGE_REV=${IMAGE_REV:-unbekannt}
echo "Image: ${IMAGE_REV:0:7}  Projekt: $PROJECT ($REPO, $TITLE_ID)  Ref: $REF  Konsole: $MODEL  Deploy: $DEPLOY_BUILD  Builder behalten: $KEEP_BUILDERS  Sprache: ${LANGUAGE:-Konsole}  Speicher: ${MEMORY_GB:-auto}${MEMORY_GB:+ GB}  RAM frei: $(awk '/^MemAvailable:/ {print int($2/1024/1024)}' /proc/meminfo) GB  Container-Limit: $(l=$(cgroup_limit_mb); if [[ -n $l ]]; then echo "$l MB"; else echo keins; fi)"
echo "Frei: $(free_gb "$CONFIG_DIR") GB unter $CONFIG_DIR, $(free_gb "$OUT_DIR") GB unter $OUT_DIR (Upstream: rund 6 GB fuer den Build, 1 GB fuer den Builder)"
if [[ $stage == build || $stage == all ]] && (( $(budget_mb) < 4096 )); then
    echo "Hinweis: weniger als 4 GB Speicher frei bzw. erlaubt. Ab v0.1.5 baut PS5_Longshot in 2-3 GB (langsamer), Linken"
    echo "  und Signieren halten aber kurz rund 3 GB (ps5/builder/README.md, Memory). Bis v0.1.4 waren es rund 10 GB."
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
    # Spielstaende auf der PS5 (scripts/saves.py): lesen und vergleichen, von einem Title in den anderen kopieren, ein Backup
    # zurueckspielen. SAVES_FROM / SAVES_TO: longshot oder heylisten; SAVES_BACKUP: Name eines Backups unter /config/saves/backups
    saves-status) log "Spielstaende auf der PS5 lesen"; python3 -u /app/scripts/saves.py status ;;
    saves-copy)
        log "Spielstaende kopieren: ${SAVES_FROM:-?} -> ${SAVES_TO:-?}"
        python3 -u /app/scripts/saves.py copy --from "${SAVES_FROM:-}" --to "${SAVES_TO:-}"
        python3 -u /app/scripts/saves.py status ;;
    saves-restore)
        log "Backup zurueckspielen: ${SAVES_BACKUP:-?} -> ${SAVES_TO:-?}"
        python3 -u /app/scripts/saves.py restore --backup "${SAVES_BACKUP:-}" --to "${SAVES_TO:-}"
        python3 -u /app/scripts/saves.py status ;;
    settings-backup) log "Einstellungen sichern"; python3 -u /app/scripts/saves.py settings-backup ;;
    settings-copy)
        log "Einstellungen kopieren: ${SAVES_FROM:-?} -> ${SAVES_TO:-?}"
        python3 -u /app/scripts/saves.py settings-copy --from "${SAVES_FROM:-}" --to "${SAVES_TO:-}"
        python3 -u /app/scripts/saves.py status ;;
    settings-restore)
        log "Einstellungen zurueckspielen: ${SAVES_BACKUP:-?} -> ${SAVES_TO:-?}"
        python3 -u /app/scripts/saves.py settings-restore --backup "${SAVES_BACKUP:-}" --to "${SAVES_TO:-}"
        python3 -u /app/scripts/saves.py status ;;
    titles-list) log "Zelda-Titles auf der PS5 lesen"; python3 -u /app/scripts/titles.py list ;;
    titles-delete) log "Title $TITLES_ID auf der PS5 loeschen"; python3 -u /app/scripts/titles.py delete --id "$TITLES_ID" ;;
    titles-rename) log "Title $TITLES_ID umbenennen"; python3 -u /app/scripts/titles.py rename --id "$TITLES_ID" --name "$TITLES_NAME" ;;
    *) die "unbekannte Stufe: $stage (check|update|build|deploy|all|saves-status|saves-copy|saves-restore|settings-backup|settings-copy|settings-restore|titles-list|titles-delete|titles-rename)" ;;
esac
