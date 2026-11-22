# PS5-Longshot-Builder

Unraid-Container, der [heydemoura/PS5_Longshot](https://github.com/heydemoura/PS5_Longshot) baut: *The Legend of
Zelda: Ocarina of Time* (Switch-2-Version), statisch rekompiliert, als natives PS5-Homebrew-Title **LGSH00001** (bis v0.1.4 `PPSA99025`). Aus der
eigenen `.nup`, auf dem eigenen Server, ohne Fenster. Anschließend kopiert er das Title per FTP auf die PS5.

Im Image sind weder Spieldateien noch Keys oder Builds, auch nicht der Builder selbst. Der Container lädt zur Laufzeit
die offizielle `LongshotPS5Builder-<tag>-x86_64.AppImage` des gewählten Releases, prüft sie gegen die `.sha256`
daneben und entpackt sie nach `/config`.

Aufbau und Pfade wie bei [hookshot-linux-builder](https://github.com/cosmicflow2512/hookshot-linux-builder), das Deploy
wie bei [hookshot-ps5-builder](https://github.com/cosmicflow2512/hookshot-ps5-builder).

## Was er macht

| Stufe | Inhalt |
| --- | --- |
| check | neuestes Release gegen den geladenen Builder und das gebaute Title (Release und Konsole) |
| update | AppImage des gewählten Releases laden (Standard `latest`), SHA-256 prüfen, entpacken, `--cli --check` |
| build | `AppRun --cli` (das ist `ps5/builder/pipeline.py`): `.nup` lesen, Lift, Kompilieren, Linken, Signieren, Shader-Listen, Title-Ordner nach `/output` |
| deploy | `/output/<Title-ID>` per FTP nach `/data/homebrew/<Title-ID>`, nur geänderte Dateien; prüft, ob die `.nup` dort liegt, wo Longshot sie sucht |

Grundlage sind [`ps5/builder/README.md`](https://github.com/heydemoura/PS5_Longshot/blob/main/ps5/builder/README.md),
[`ps5/builder/pipeline.py`](https://github.com/heydemoura/PS5_Longshot/blob/main/ps5/builder/pipeline.py) (Optionen
`--game --out --model --work --jobs --lift-jobs --memory --check`) und
[`ps5/builder/package.py`](https://github.com/heydemoura/PS5_Longshot/blob/main/ps5/builder/package.py) (das AppRun
startet mit `--cli` die `pipeline.py`). Die AppImage bringt Python, clang/ld.lld mit PS5-Ziel, `ps5-native-tool` und das
Kit mit. Sie wird entpackt statt gemountet, weil es in Docker kein FUSE gibt.

## Title-ID

Ab v0.1.5 heißt das Title `LGSH00001`, bis v0.1.4 `PPSA99025` ([9bc1211c](https://github.com/heydemoura/PS5_Longshot/commit/9bc1211c)): `PPSA99025` ist auch die ID
eines anderen Homebrews, und zwei Titles mit derselben ID installieren sich übereinander. `build.sh` nimmt die ID aus
`kit.json` des geladenen Builders (`title_id`, aus `ps5/sce_sys/param.json`), Build-Ordner und Deploy-Ziel folgen ihr;
`TITLE_ID` setzt sie fest. Das Deploy schickt das Title, das zuletzt gebaut wurde.

Umstieg von v0.1.4 oder älter: neu bauen und deployen. Beim ersten Start übernimmt `LGSH00001` aus
`/data/homebrew/PPSA99025` (nur wenn dessen `param.json` Longshots ist) `user/` (Spielstände), `longshot_options.ini`
und `language.txt`, wo das neue Title sie nicht hat, und verschiebt `cache/` und `radv-shader-cache/`, damit die
Shader-Vorbereitung nicht noch einmal läuft (`host/ps5/migrate_id.c`). Danach kann der alte Ordner auf der PS5 und unter
`/output` weg; das Deploy weist darauf hin, solange er auf der PS5 liegt.

## ZBIC

Die `main` einer `.nup` von Firmware 22+ ist ZBIC-komprimiert. Seit v0.1.3 bringt die AppImage eine mit dem LLVM des
Kits gebaute `zbic.so` mit, die `--check` mit einem Selbsttest prüft ([46f7bb26](https://github.com/heydemoura/PS5_Longshot/commit/46f7bb26),
[318696dc](https://github.com/heydemoura/PS5_Longshot/commit/318696dc)). v0.1.0 hat keine (das Update bricht dann mit Hinweis ab), die von v0.1.1 und v0.1.2 entpackt
laut Upstream keinen ZBIC-Frame. Für eine `.nup` also v0.1.3 oder neuer nehmen. Die früher hier mit gcc gebaute
Ersatz-Bibliothek ist entfernt, weil Upstream genau eine GCC-gebaute `zbic.so` als defekt gemessen hat.

## Prüfung des Downloads

Die `.sha256` liegt im selben Release wie die AppImage (`.github/workflows/builder-release.yml` von Upstream). Sie
schützt gegen kaputte Downloads, nicht gegen ein manipuliertes Release: anders als Longshot von MagicBeanDev signiert
PS5_Longshot seine Releases nicht.

## Voraussetzungen

Laut [Upstream-README](https://github.com/heydemoura/PS5_Longshot/blob/main/README.md#what-you-need):

- Die eigene `.nup` in genau dieser Version: Programm `0400486024DEC000`, Update v131072, Build `e0f3ccfa`.
- Speicher: ab v0.1.5 mindestens 2 GB, gemessen in 3 GB in rund 81 Minuten, mit allem freien Speicher (etwa 19 GB) in rund
  21 Minuten (`ps5/builder/README.md`, Memory). Bis v0.1.4 rund 10 GB. Dazu rund 6 GB Platz für den Build und 1 GB für
  den Builder.
- Eine PS5 mit Homebrew-Umgebung, die Titles aus `/data/homebrew` startet, und ein FTP-Server darauf (Standardport 2121).
  Wie man das einrichtet, erklärt Upstream nicht; eine Firmware-Version nennt Upstream nicht.

Stand laut [Upstream-README](https://github.com/heydemoura/PS5_Longshot/blob/main/README.md) (22.11.2026):
experimentell. Läuft auf der PS5 Pro und der Base-PS5 (PS5 und PS5 Slim, Profil `base`), dort laut Upstream mit
Frame Generation etwa 20 Bilder je Sekunde weniger als auf der Pro.

## Installation (Unraid)

```bash
mkdir -p /boot/config/plugins/dockerMan/templates-user
curl -fsSL -o /boot/config/plugins/dockerMan/templates-user/my-ps5-longshot-builder.xml \
  https://raw.githubusercontent.com/cosmicflow2512/PS5-Longshot-Builder/main/unraid/ps5-longshot-builder.xml
```

Danach unter Docker → Add Container das Template `ps5-longshot-builder` wählen, `PS5_HOST` eintragen und die Web-UI
öffnen (Port 8486).

## Konsole

In der Web-UI unter **Konsole** (gespeichert in `/config/model`, geht vor `MODEL`). Das Title wird für ein Modell gebaut
(`pipeline.py` `MODELS`):

| | `--model` | `attribute3` in `param.json` | `longshot_env.txt` |
| --- | --- | --- | --- |
| PS5 Pro | `pro` | `0x8540040` (High CPU Frequency, 13.232 MiB) | nichts |
| PS5 / PS5 Slim | `base` | `0x140040` (12.016 MiB) | `RX_VK_TEX_MAX_DIM=512` |

Ein Build für das andere Modell dauert nur Sekunden: die Build-Dateien unter `/config/work` bleiben.

## Spielsprache

In der Web-UI unter **Spielsprache** (gespeichert in `/config/language`, geht vor `LANGUAGE`). Standard ist **„Sprache
der Konsole folgen“**: `build.sh` legt keine `language.txt` ins Title (eine früher geschriebene entfernt es aus
`/output`). Ab v0.1.4 nimmt das Spiel dann die Systemsprache der PS5, Englisch (US), wenn es sie nicht hat
([b35353ce](https://github.com/heydemoura/PS5_Longshot/commit/b35353ce)), und hat im Menü (Touchpad-Klick + Options, Reiter Gameplay) die Zeile „Game language“ mit
„Follow the console“ und den 16 Sprachen; sie schreibt `language.txt` im Title-Ordner auf der Konsole
([e85812a8](https://github.com/heydemoura/PS5_Longshot/commit/e85812a8), dort auf der Konsole getestet). Bis v0.1.3 hieß „keine Sprache“ Englisch (US).

Eine feste Sprache schreibt `build.sh` bei Build und Deploy als Code nach `<Title-ID>/language.txt`, im Format, das das
Spiel selbst liest (`host/nn_applet.c`, `desired_language`: die erste Zeile, die kein Kommentar ist und einen der 16
Codes nennt). Das Deploy lädt nur Dateien, die sich seit dem letzten Deploy geändert haben: eine im Spielmenü gewählte
Sprache bleibt, bis hier eine andere feste Sprache gewählt wird (oder `FORCE_DEPLOY=true`). Auf „Konsole folgen“
zurückschalten löscht eine `language.txt` auf der PS5 nicht; dafür im Spielmenü „Follow the console“ wählen.

## Auf der PS5

1. „Auf die PS5 kopieren" (oder `AUTO_DEPLOY=true`) legt das Title nach `/data/homebrew/<Title-ID>` (ab v0.1.5
   `/data/homebrew/LGSH00001`).
2. Die `.nup` gehört laut Upstream nach `/data/eglantineps5/roms/oot.nup`. Gesucht wird sie laut
   `host/ps5/win32_ps5.c` auch unter `/data/eglantineps5/roms/<Name des Dumps>.nup`, `/data/lichii/roms/oot/oot.nup`
   und `/data/prosperoeden/roms/oot/oot.nup`. Eine `.nup` von PS5_Hookshot oder PS5_Lichii wird also gefunden.
   Mit `UPLOAD_NUP=true` kopiert das Deploy die Datei nach `PS5_NUP_PATH`, fortsetzbar (rund 25 GB).
3. Longshot vom Startbildschirm oder dem Homebrew-Launcher starten. Im Spiel öffnet Touchpad-Klick + Options das Menü.

Spielstände (`user/`), `longshot_options.ini` und die Shader-Caches liegen nur auf der Konsole und bleiben beim Deploy
unberührt. `longshot_env.txt` kommt aus dem Build und wird ersetzt.

## Speicher

Das Template begrenzt den Container mit `--memory=12g --memory-swap=12g`. Das Limit muss unter dem RAM liegen, der auf
dem Host tatsächlich frei ist (`free -m`, Spalte available). `pipeline.py` liest den freien Speicher aus `/proc/meminfo`
und sieht ein Container-Limit nicht.

- **Ab v0.1.5** hat `pipeline.py` `--memory GB` ([b4e23503](https://github.com/heydemoura/PS5_Longshot/commit/b4e23503)): Übersetzung und Compiles halten sich an das
  Budget, große Funktionen und Chunks werden geteilt, ein Compile startet erst, wenn sein Bedarf passt. `build.sh` gibt
  `--memory` = `MEMORY_GB`, sonst Container-Limit − 1 GB (mindestens 2), und `--jobs`/`--lift-jobs` nur, wenn `JOBS`
  bzw. `LONGSHOT_LIFT_JOBS` gesetzt sind. Ob der Builder die Option hat, prüft `build.sh` mit `--cli --help`.
  Weniger Speicher ist laut Upstream nur langsamer, das Ergebnis gleich. Linken und Signieren halten kurz rund 3 GB.
- **Bis v0.1.4** setzt `build.sh` mit Limit `--jobs` (Kerne − 1, höchstens Limit ÷ 1,6 GB) und `--lift-jobs` (1 unter
  10 GB, sonst (Limit − 4 GB) ÷ 2 GB) selbst.

Ein abgebrochener Build setzt beim nächsten Lauf fort.

## Variablen

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `NUP_FILE` | leer | Pfad der `.nup` im Container. Leer: erste `.nup` mit `0400486024DEC000` im Namen unter `/nup` |
| `MODEL` | `pro` | `pro` oder `base`, solange in der Web-UI nichts gewählt ist |
| `LANGUAGE` | leer | feste Spielsprache (`language.txt`), solange in der Web-UI nichts gewählt ist; leer oder `auto`: der Konsole folgen |
| `LONGSHOT_REF` | `latest` | `latest` = neuestes Release, oder ein Tag (`v0.1.0`) |
| `LONGSHOT_REPO` | `heydemoura/PS5_Longshot` | GitHub-Repository der Releases |
| `PS5_HOST` | leer | IP der PS5 |
| `PS5_FTP_PORT` | `2121` | FTP-Port |
| `AUTO_DEPLOY` | `false` | nach „Alles bauen" automatisch deployen |
| `UPLOAD_NUP` | `false` | `.nup` beim Deploy mitkopieren |
| `PS5_NUP_PATH` | `/data/eglantineps5/roms/oot.nup` | Ziel für `UPLOAD_NUP` |
| `FORCE_DEPLOY` | `false` | alle Dateien neu hochladen |
| `PUID` / `PGID` | `99` / `100` | Besitzer des Title-Ordners nach dem Build |
| `RUN_ON_START` | `false` | beim Containerstart sofort bauen |
| `MEMORY_GB` | Limit − 1 GB | Speicher für den Build (`--memory`, ab v0.1.5) |
| `TITLE_ID` | aus dem Builder | Title-ID fest setzen |
| `JOBS` | siehe Speicher | Compiler gleichzeitig (`--jobs`) |
| `LONGSHOT_LIFT_JOBS` | siehe Speicher | Prozesse des Lifts (`--lift-jobs`) |
| `GITHUB_TOKEN` | leer | optional, hebt die Grenze der GitHub-API (60 Abfragen je Stunde ohne Token) |
| `EXTRA_ARGS` | leer | weitere Optionen für `pipeline.py` |

Liegt keine `.nup` unter `/nup`, baut der Container aus dem `exefs`, das ein früherer Build unter `/config/work/game`
abgelegt hat (`pipeline.py` nimmt auch einen Ordner mit dem `exefs`).

Kommandozeile ohne Web-UI: `docker exec -it ps5-longshot-builder /app/scripts/build.sh all` (oder `check`, `update`,
`build`, `deploy`).

## Lizenz

GPL-3.0, wie PS5_Longshot. Das Icon stammt aus PS5_Longshot (`assets/longshot.png`).
