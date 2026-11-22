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
`--game --out --model --work --jobs --lift-jobs --check`) und
[`ps5/builder/package.py`](https://github.com/heydemoura/PS5_Longshot/blob/main/ps5/builder/package.py) (das AppRun
startet mit `--cli` die `pipeline.py`). Die AppImage bringt Python, clang/ld.lld mit PS5-Ziel, `ps5-native-tool` und das
Kit mit. Sie wird entpackt statt gemountet, weil es in Docker kein FUSE gibt.

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

## Projekt: Longshot, HeyListen, Fork oder Plus

In der Web-UI unter **Projekt** (gespeichert in `/config/project`, geht vor `PROJECT`, Standard `longshot`):

| | `longshot` | `heylisten` | `fork` | `plus` |
| --- | --- | --- | --- | --- |
| Repository | [heydemoura/PS5_Longshot](https://github.com/heydemoura/PS5_Longshot) | [cosmicflow2512/PS5_HeyListen](https://github.com/cosmicflow2512/PS5_HeyListen) | [cosmicflow2512/PS5_Longshot_Cosi](https://github.com/cosmicflow2512/PS5_Longshot_Cosi) | [groovy2312/PS5_Longshot_Plus](https://github.com/groovy2312/PS5_Longshot_Plus) |
| AppImage | `LongshotPS5Builder-<tag>-x86_64.AppImage` | `HeyListenPS5Builder-<tag>-x86_64.AppImage` | `LongshotPS5Builder-<tag>-x86_64.AppImage` | `PS5LongshotPlusBuilder-<tag>-x86_64.AppImage` |
| Title | `LGSH00001` (bis v0.1.4 `PPSA99025`) | `PPSA99026` | `LGSF00002` (eigene; Kit: `LGSH00001`, bis ps5.6 `PPSA99198`) | `LGSP00003` (eigene; Kit: `PPSA99198`) |
| Release-Vorgabe | `LONGSHOT_REF` | `HEYLISTEN_REF` | `FORK_REF` | `PLUS_REF` |
| Builder, Build-Dateien, Stand | direkt unter `/config` (wie bisher) | unter `/config/heylisten` | unter `/config/fork` | unter `/config/plus` |

`fork` ist PS5_Longshot v0.1.3 mit den offenen Pull Requests #6, #18–#23, #32, #33 und #35 (darunter der Entwurf #21,
Lossless Scaling). #35 verlegt das Title auf `PPSA99198`, weil das Homebrew reUndr `PPSA99025` nutzt. Mit dem Ordner
„Lossless Scaling“ im Template (nach `/lossless`, `LOSSLESS_DLL`) legen Build und Deploy des Forks die eigene `Lossless.dll`
als `lossless/Lossless.dll` ins Title, wo das Spiel sie sucht (`gpu/vk/vk_framegen.cpp` von PR #21).
Für AMD FSR 4 (PR #41) lädt der Container einmal das Release v0.3.0 von
[beamng-fsr4-linux](https://github.com/Mob1K7105/beamng-fsr4-linux) (Herkunft des PS5-Codes), prüft es gegen eine feste
SHA-256 und die `SHA256SUMS` im Archiv, behält es unter `/config/fsr4` und legt bei Build und Deploy `fsr4/lite/`
(Stufen 1080p und 2160p, mit AMDs Lizenzhinweis) ins Title. `FSR4_ASSETS=all` nimmt zusätzlich `fsr4/int8/` (navi2) mit,
`FSR4_ASSETS=off` lässt FSR 4 weg.

`plus` ist [PS5_Longshot_Plus](https://github.com/groovy2312/PS5_Longshot_Plus) von groovy2312, ein Fork von PS5_Longshot
mit eigenem Builder (`PS5LongshotPlusBuilder`, gleiche `pipeline.py` mit `--cli` und `--memory`). Releases mit Linux-AppImage:
`v0.2.0-plus`, `v0.3.0-plus`, `v0.3.2-plus` (`v0.3.1-plus` hat keine). Wie bei Upstream sind die Releases nicht signiert.

Alle Titles können nebeneinander auf der PS5 liegen. Konsole und Spielsprache gelten für alle Projekte.

### Eigene Title-IDs und Name mit Version

Die Kits von `fork` (seit v3.0.0-ps5.7 `LGSH00001`, wie Longshot) und `plus` (`PPSA99198`, wie der Fork bis ps5.6) fielen
mit anderen Titles zusammen: ein Deploy des einen hätte das andere auf der PS5 ersetzt. Beide bekommen deshalb eine eigene
ID, `LGSF00002` und `LGSP00003` (feste: `FORK_TITLE_ID`, `PLUS_TITLE_ID`, `LONGSHOT_TITLE_ID`, `HEYLISTEN_TITLE_ID`).
`pipeline.py` baut in einen Zwischenordner `/output/.build-<Projekt>`, `build.sh` legt das Ergebnis nach
`/output/<Title-ID>` und setzt in `param.json` `titleId`, den ID-Teil von `contentId` (das Etikett `PS5LONGSHOT…` bleibt,
daran erkennt `host/ps5/migrate_id.c` Longshots Ordner) und `conceptId`. Das ist dieselbe Änderung, mit der PS5_Longshot
selbst die ID gewechselt hat ([9bc1211c](https://github.com/heydemoura/PS5_Longshot/commit/9bc1211c): nur `ps5/sce_sys/param.json`); `eboot.bin` wird ohne ID signiert,
und `pipeline.py` schreibt `param.json` selbst erst nach dem Signieren. Dass die PS5 die Präfixe `LGSF`/`LGSP` annimmt, ist
ungeprüft (Upstream hat `LGSH` auf der Konsole geprüft); sonst eine andere ID über die Variable setzen.

Die ID bleibt über Updates gleich: Spielstände, Einstellungen und Shader-Cache bleiben. Ein Fork mit eigener ID übernimmt
beim ersten Start Spielstände aus seinen alten Ordnern, wenn sein `migrate_id.c` sie kennt (der Fork: `PPSA99198`, dann
`PPSA99025`); Plus hat keins, dort die Spielstände im Reiter Spielstände kopieren.

Den Namen auf dem Startbildschirm (`titleName` in `param.json`) setzen Build und Deploy auf Spiel und Version:
`Longshot v0.1.5`, `Longshot ps5.7` (Fork, `v3.0.0-ps5.7`), `Longshot Plus v0.3.2`, `HeyListen <Tag>`. Ein in der Web-UI
vergebener Name geht vor, `AUTO_TITLE_NAME=false` lässt den des Kits. Die `.nup`
sucht PS5_HeyListen an denselben Orten wie Longshot (`host/ps5/win32_ps5.c` stammt von dort).

PS5_HeyListen ist **experimentell**: HeyListens Engine mit dem PS5-Port von PS5_Longshot, bisher auf keiner Konsole
gestartet. Seine Builder-AppImage baut der Workflow `ps5-builder-release.yml` dort. Solange es kein Release mit
AppImage gibt, meldet „Auf Updates prüfen“ für `heylisten` einen Fehler.

## Title-ID

Die Title-ID kommt aus `kit.json` des Builders (`title_id`, aus `ps5/sce_sys/param.json` des Releases). PS5_Longshot
heißt ab v0.1.5 `LGSH00001`, bis v0.1.4 `PPSA99025` ([9bc1211c](https://github.com/heydemoura/PS5_Longshot/commit/9bc1211c)): `PPSA99025` ist auch die ID eines anderen
Homebrews, und zwei Titles mit derselben ID installieren sich übereinander. Ein Build merkt sich die ID in
`<Stand>/title_id` und in `build-info.json`; Deploy, Web-UI, Spielstände und Titles nehmen sie von dort, ein archivierter
Build seine eigene. `TITLE_ID` setzt die von `longshot` fest.

Umstieg von v0.1.4 oder älter: neu bauen und deployen. Beim ersten Start übernimmt `LGSH00001` aus
`/data/homebrew/PPSA99025` (nur wenn dessen `param.json` Longshots ist) `user/` (Spielstände), `longshot_options.ini`
und `language.txt`, wo das neue Title sie nicht hat, und verschiebt `cache/` und `radv-shader-cache/`, damit die
Shader-Vorbereitung nicht noch einmal läuft (`host/ps5/migrate_id.c`). Danach kann der alte Ordner auf der PS5 (Reiter
Titles) und unter `/output` weg; Build und Deploy weisen darauf hin.

## ZBIC

Die `main` einer `.nup` von Firmware 22+ ist ZBIC-komprimiert. Seit PS5_Longshot v0.1.3 bringt die AppImage eine mit dem
LLVM des Kits gebaute `zbic.so` mit, die `--check` mit einem Selbsttest prüft ([46f7bb26](https://github.com/heydemoura/PS5_Longshot/commit/46f7bb26),
[318696dc](https://github.com/heydemoura/PS5_Longshot/commit/318696dc)). Die von v0.1.1 und v0.1.2 entpackt laut Upstream keinen ZBIC-Frame, v0.1.0 hat keine. Für eine
`.nup` also v0.1.3 oder neuer nehmen. Nur wenn ein Builder gar keine `zbic.so` hat, baut `build.sh` sie wie früher mit
gcc, mit Warnung: Upstream hat genau eine GCC-gebaute als defekt gemessen.

## Spielstände zwischen Longshot und HeyListen

In der Web-UI unter **Spielstände** (Skript `scripts/saves.py`, Stufen `saves-status`, `saves-copy`, `saves-restore`), zwischen
allen drei Titles (Longshot `LGSH00001` bzw. bis v0.1.4 `PPSA99025`, `PPSA99026`, `PPSA99198`; jeweils die ID des
letzten Builds):

- **Spielstände von der PS5 lesen:** liest per FTP `/data/homebrew/<Title-ID>/user/save` der drei Titles,
  zeigt je Spiel Dateien, Größe und letzte Änderung und markiert den neueren Stand bzw. „gleich“ (Inhalt verglichen).
- **Kopieren** (z. B. Longshot → HeyListen): sichert zuerst das Ziel nach `/config/saves/backups/<Zeit>-<spiel>-vor-kopie`,
  liest die Quelle und spiegelt sie ins Ziel (Dateien, die nur im Ziel lagen, werden entfernt; sie sind im Backup), prüft
  danach die Größen.
- **Backup zurückspielen:** ein Backup in eines der beiden Spiele, das Ziel wird vorher ebenfalls gesichert. Es bleiben die
  letzten 30 Backups.

Beide Ports speichern unter `<Title>/user/save/<Benutzer-ID>/` mit derselben festen Benutzer-ID (`host/nn_fs.c`,
`user_uid` in `host/nn_*.c` von PS5_Longshot und PS5_HeyListen). Kopiert wird der ganze Ordner, unverändert. Dass das
jeweils andere Spiel die Spielstände lädt, ist auf der Konsole noch ungeprüft: vor dem ersten Kopieren erst lesen, dann
kopieren, im Spiel prüfen; zur Not das Backup zurückspielen.

Während des Kopierens darf keines der beiden Spiele auf der PS5 laufen. „Neuer“ richtet sich nach den Dateizeiten, die der
FTP-Server der PS5 meldet (bei Servern ohne `MLSD`/`MDTM` nur auf die Minute genau).

## Einstellungen des Spiels

Was du im Spiel einstellst (Menü, Grafik, Steuerung, Button prompts), steht in einer Datei im Title-Ordner neben der
`eboot.bin`: `longshot_options.ini` bei Longshot und dem Fork (`host/options_path.c`: ohne `--user` und `HOS_OPTIONS_FILE`
neben dem Spiel), `hookshot_options.ini` bei HeyListen (`host/ps5/hos_sdl_ps5.c`). Deploy und Build lassen sie unverändert.

Im Reiter „Spielstände & Einstellungen“ zeigt „Von der PS5 lesen“ die Datei jedes Titles (Größe, Datum, gewählte Button
prompts, gleich wie welche anderen). „Einstellungen jetzt sichern“ legt sie nach `/config/saves/settings/<Zeit>-<Title>-<Anlass>/`
(die letzten 30). Gesichert wird sie außerdem bei jedem Sichern der Spielstände und vor dem Löschen eines Titles. Zurückspielen
und Kopieren sichern das Ziel vorher; kopiert wird nur zwischen Longshot und Longshot-Fork, die dieselbe Datei haben. Das Spiel
muss dabei beendet sein, sonst schreibt es seine Einstellungen zurück.

## Oberfläche

Oben stehen das Projekt und die Aktionen (Updates prüfen, Alles bauen, Builder aktualisieren, Build, Auf die PS5 kopieren,
Abbrechen). Nach „Auf Updates prüfen“ lädt die Release-Liste neu, und eine Zeile darunter sagt, ob es etwas zu bauen gibt, mit
„Alles bauen“ direkt daneben. Darunter die Reiter Build (Release, Konsole, Sprache, Stand), Spielstände & Einstellungen und
Titles auf der PS5; rechts das Log.

## Titles auf der PS5

„Titles von der PS5 lesen“ zeigt alle Zelda-Titles unter `/data/homebrew` (`scripts/titles.py`). Erkannt werden sie an der
Title-ID eines Projekts, am Namen in `sce_sys/param.json` oder an den Dateien der Ports. Zu jedem Title stehen Name, Title-ID,
Herkunft (Repository, Release, Konsole, Build-Zeit), Größe und die Zahl der Spielstand-Dateien. Die Herkunft kommt aus
`build-info.json`, die Build und Deploy seit dieser Version mit in den Title legen. Bei älteren Deploys steht stattdessen das
Datum der `eboot.bin`.

- **Umbenennen** ändert den angezeigten Namen (`titleName` für alle Sprachen in `param.json`) auf der PS5. Bei den Titles der
  drei Projekte (auch dem alten `PPSA99025`) merkt sich der Container den Namen, und Build und Deploy behalten ihn. Ob der Startbildschirm den
  neuen Namen sofort zeigt, hängt von der Homebrew-Umgebung ab (ungeprüft).
- **Löschen** sichert erst die Spielstände nach `/config/saves/backups` (`<Zeit>-<Projekt oder Title-ID>-vor-loeschen`,
  zurückspielbar wie die anderen Backups), dann wird der ganze Ordner gelöscht. Zur Sicherheit muss die Title-ID eingetippt
  werden.
- Die **Title-ID** selbst lässt sich nicht ändern: Sie steht in `param.json` (`titleId`, `contentId`), im Kit des Builders und
  in Pfaden des Spiels.

## Konsole

In der Web-UI unter **Konsole** (gespeichert in `/config/model`, geht vor `MODEL`). Das Title wird für ein Modell gebaut
(`pipeline.py` `MODELS`):

| | `--model` | `attribute3` in `param.json` | `longshot_env.txt` |
| --- | --- | --- | --- |
| PS5 Pro | `pro` | `0x8540040` (High CPU Frequency, 13.232 MiB) | nichts |
| PS5 / PS5 Slim | `base` | `0x140040` (12.016 MiB) | `RX_VK_TEX_MAX_DIM=512` |

Ein Build für das andere Modell dauert nur Sekunden: die Build-Dateien unter `/config/work` bleiben.

## Mehrere Versionen

Jeder fertige Build wird zusätzlich nach `/output/archive/<Projekt>/<Builder-Version>-<Konsole>/` kopiert (z. B.
`archive/longshot/v0.1.0-pro/PPSA99025`, daneben `build-info.json`). Ein neuer Build derselben Version und Konsole
ersetzt seinen Archiveintrag. `ARCHIVE_BUILDS=false` schaltet das ab.

In der Web-UI im Reiter **Build** unter **Builds** wählst du, was „Auf die PS5 kopieren" nimmt: den aktuellen Build
(`/output/<Title-ID>`) oder einen archivierten (je Projekt gespeichert in `deploy_build`). Ein Wechsel zwischen Versionen
braucht damit kein neues Kompilieren. Sprache, Name, Lossless.dll und FSR 4 kommen beim Deploy wie beim aktuellen Build
in den gewählten Ordner. Archivierte Builds und nicht aktive Builder lassen sich dort auch löschen.

Auf der PS5 liegt je Projekt trotzdem nur eine Version: alle Builds eines Projekts haben dieselbe Title-ID und landen im
selben Ordner unter `/data/homebrew`. Das Deploy löscht auf der Konsole nichts. Eine Datei, die nur die vorher kopierte
Version hat, bleibt also liegen.

Der Schalter **Builder anderer Releases behalten** (gespeichert in `/config/keep_builders`, geht vor `KEEP_BUILDERS`,
Standard an) lässt beim Update die entpackten Builder anderer Releases liegen (je einige 100 MB). Ein Wechsel zurück auf
ein früheres Release lädt dann nichts neu.

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

1. „Auf die PS5 kopieren" (oder `AUTO_DEPLOY=true`) legt das Title nach `/data/homebrew/<Title-ID>` (Longshot ab v0.1.5
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

- **Builder mit `--memory`** (PS5_Longshot ab v0.1.5, [b4e23503](https://github.com/heydemoura/PS5_Longshot/commit/b4e23503)): Übersetzung und Compiles halten sich an
  das Budget, große Funktionen und Chunks werden geteilt, ein Compile startet erst, wenn sein Bedarf passt. `build.sh`
  gibt `--memory` = `MEMORY_GB`, sonst Container-Limit − 3 GB, unter 10 GB Limit höchstens 4 GB (mindestens 2), und
  `--jobs`/`--lift-jobs` nur, wenn `JOBS` bzw. `LONGSHOT_LIFT_JOBS` gesetzt sind. Das Budget zählt nur die Prozesse des
  Builds, das Container-Limit auch Web-UI und Datei-Cache: mit Limit − 1 GB hat der OOM-Killer bei 8 GB Limit einen
  Prozess der Übersetzung beendet (4 Worker). Unter 5 GB übersetzt Upstream in einem Prozess, ohne Worker. Ob der Builder die Option hat, prüft `build.sh` mit `--cli --help`.
  Weniger Speicher ist laut Upstream nur langsamer, das Ergebnis gleich. Linken und Signieren halten kurz rund 3 GB.
- **Ältere Builder**: mit Limit setzt `build.sh` `--jobs` (Kerne − 1, höchstens Limit ÷ 1,6 GB) und `--lift-jobs`
  (1 unter 10 GB, sonst (Limit − 4 GB) ÷ 2 GB) selbst.

Beendet der OOM-Killer einen Prozess des Builds, kann der Rest hängen bleiben (beobachtet: der Haupt-`lift.py` weg, seine
Worker warten ewig, `pipeline.py` wartet auf deren Ausgabe). `build.sh` liest dafür `oom_kill` aus
`/sys/fs/cgroup/memory.events`: steht nach einem OOM-Kill die CPU-Zeit aller Prozesse des Builders 5 Minuten still, beendet
es sie und bricht mit einem Hinweis auf `MEMORY_GB` ab. Rechnet der Build weiter (Upstream ersetzt einen beendeten Worker
selbst), bleibt er unberührt. Nachsehen auf dem Host: `dmesg | grep -i -E 'oom|killed process'`.

Ein abgebrochener Build setzt beim nächsten Lauf fort.

## Variablen

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `NUP_FILE` | leer | Pfad der `.nup` im Container. Leer: erste `.nup` mit `0400486024DEC000` im Namen unter `/nup` |
| `MODEL` | `pro` | `pro` oder `base`, solange in der Web-UI nichts gewählt ist |
| `LANGUAGE` | leer | feste Spielsprache (`language.txt`), solange in der Web-UI nichts gewählt ist; leer oder `auto`: der Konsole folgen |
| `PROJECT` | `longshot` | `longshot` oder `heylisten`, solange in der Web-UI nichts gewählt ist |
| `LONGSHOT_REF` | `latest` | `latest` = neuestes Release, oder ein Tag (`v0.1.0`) |
| `HEYLISTEN_REF` | `latest` | wie `LONGSHOT_REF`, für `heylisten` |
| `LONGSHOT_REPO` | `heydemoura/PS5_Longshot` | GitHub-Repository der Releases |
| `PS5_HOST` | leer | IP der PS5 |
| `PS5_FTP_PORT` | `2121` | FTP-Port |
| `ARCHIVE_BUILDS` | `true` | jeden Build nach `/output/archive/<Projekt>/<Version>-<Konsole>/` kopieren |
| `KEEP_BUILDERS` | `true` | Builder anderer Releases beim Update behalten, solange in der Web-UI nichts gewählt ist |
| `AUTO_DEPLOY` | `false` | nach „Alles bauen" automatisch deployen |
| `UPLOAD_NUP` | `false` | `.nup` beim Deploy mitkopieren |
| `PS5_NUP_PATH` | `/data/eglantineps5/roms/oot.nup` | Ziel für `UPLOAD_NUP` |
| `FORCE_DEPLOY` | `false` | alle Dateien neu hochladen |
| `PUID` / `PGID` | `99` / `100` | Besitzer des Title-Ordners nach dem Build |
| `RUN_ON_START` | `false` | beim Containerstart sofort bauen |
| `MEMORY_GB` | Limit − 3 GB, unter 10 GB Limit höchstens 4 | Speicher für den Build (`--memory`, ab v0.1.5) |
| `TITLE_ID` | aus dem Builder | Title-ID von `longshot` fest setzen |
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
