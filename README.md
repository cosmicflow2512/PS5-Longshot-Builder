# PS5-Longshot-Builder

Unraid-Container, der [heydemoura/PS5_Longshot](https://github.com/heydemoura/PS5_Longshot) baut: *The Legend of
Zelda: Ocarina of Time* (Switch-2-Version), statisch rekompiliert, als natives PS5-Homebrew-Title **PPSA99025**. Aus der
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
| build | `AppRun --cli` (das ist `ps5/builder/pipeline.py`): `.nup` lesen, Lift, Kompilieren, Linken, Signieren, `PPSA99025` nach `/output` |
| deploy | `/output/PPSA99025` per FTP nach `/data/homebrew/PPSA99025`, nur geänderte Dateien; prüft, ob die `.nup` dort liegt, wo Longshot sie sucht |

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
- Rund 10 GB freier RAM während des Builds (der Lift allein hält etwa 6 GB), rund 6 GB Platz für den Build und 1 GB
  für den Builder.
- Eine PS5 mit Homebrew-Umgebung, die Titles aus `/data/homebrew` startet, und ein FTP-Server darauf (Standardport 2121).
  Wie man das einrichtet, erklärt Upstream nicht; eine Firmware-Version nennt Upstream nicht.

Stand laut Upstream (16.11.2026): experimentell, nur auf einer PS5 Pro gemessen, bis Kokiri-Wald gespielt. Keine
Base-PS5 hat es gestartet. Das Lesen einer `.nup` durch den Builder ist laut `ps5/builder/README.md` noch nicht getestet.

## Installation (Unraid)

```bash
mkdir -p /boot/config/plugins/dockerMan/templates-user
curl -fsSL -o /boot/config/plugins/dockerMan/templates-user/my-ps5-longshot-builder.xml \
  https://raw.githubusercontent.com/cosmicflow2512/PS5-Longshot-Builder/main/unraid/ps5-longshot-builder.xml
```

Danach unter Docker → Add Container das Template `ps5-longshot-builder` wählen, `PS5_HOST` eintragen und die Web-UI
öffnen (Port 8486).

## Projekt: Longshot oder HeyListen

In der Web-UI unter **Projekt** (gespeichert in `/config/project`, geht vor `PROJECT`, Standard `longshot`):

| | `longshot` | `heylisten` | `fork` |
| --- | --- | --- | --- |
| Repository | [heydemoura/PS5_Longshot](https://github.com/heydemoura/PS5_Longshot) | [cosmicflow2512/PS5_HeyListen](https://github.com/cosmicflow2512/PS5_HeyListen) | [cosmicflow2512/PS5_Longshot_Cosi](https://github.com/cosmicflow2512/PS5_Longshot_Cosi) |
| AppImage | `LongshotPS5Builder-<tag>-x86_64.AppImage` | `HeyListenPS5Builder-<tag>-x86_64.AppImage` | `LongshotPS5Builder-<tag>-x86_64.AppImage` |
| Title | `PPSA99025` | `PPSA99026` | `PPSA99198` |
| Release-Vorgabe | `LONGSHOT_REF` | `HEYLISTEN_REF` | `FORK_REF` |
| Builder, Build-Dateien, Stand | direkt unter `/config` (wie bisher) | unter `/config/heylisten` | unter `/config/fork` |

`fork` ist PS5_Longshot v0.1.3 mit den offenen Pull Requests #6, #18–#23, #32, #33 und #35 (darunter der Entwurf #21,
Lossless Scaling). #35 verlegt das Title auf `PPSA99198`, weil das Homebrew reUndr `PPSA99025` nutzt. Mit dem Ordner
„Lossless Scaling“ im Template (nach `/lossless`, `LOSSLESS_DLL`) legen Build und Deploy des Forks die eigene `Lossless.dll`
als `lossless/Lossless.dll` ins Title, wo das Spiel sie sucht (`gpu/vk/vk_framegen.cpp` von PR #21).
Für AMD FSR 4 (PR #41) lädt der Container einmal das Release v0.3.0 von
[beamng-fsr4-linux](https://github.com/Mob1K7105/beamng-fsr4-linux) (Herkunft des PS5-Codes), prüft es gegen eine feste
SHA-256 und die `SHA256SUMS` im Archiv, behält es unter `/config/fsr4` und legt bei Build und Deploy `fsr4/lite/`
(Stufen 1080p und 2160p, mit AMDs Lizenzhinweis) ins Title. `FSR4_ASSETS=all` nimmt zusätzlich `fsr4/int8/` (navi2) mit,
`FSR4_ASSETS=off` lässt FSR 4 weg.

Beide Titles können nebeneinander auf der PS5 liegen. Konsole und Spielsprache gelten für beide Projekte. Die `.nup`
sucht PS5_HeyListen an denselben Orten wie Longshot (`host/ps5/win32_ps5.c` stammt von dort).

PS5_HeyListen ist **experimentell**: HeyListens Engine mit dem PS5-Port von PS5_Longshot, bisher auf keiner Konsole
gestartet. Seine Builder-AppImage baut der Workflow `ps5-builder-release.yml` dort. Solange es kein Release mit
AppImage gibt, meldet „Auf Updates prüfen“ für `heylisten` einen Fehler.

## Spielstände zwischen Longshot und HeyListen

In der Web-UI unter **Spielstände** (Skript `scripts/saves.py`, Stufen `saves-status`, `saves-copy`, `saves-restore`), zwischen
allen drei Titles (`PPSA99025`, `PPSA99026`, `PPSA99198`):

- **Spielstände von der PS5 lesen:** liest per FTP `/data/homebrew/PPSA99025/user/save` und `/data/homebrew/PPSA99026/user/save`,
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

- **Umbenennen** ändert den angezeigten Namen (`titleName` für alle Sprachen in `param.json`) auf der PS5. Bei PPSA99025,
  PPSA99026 und PPSA99198 merkt sich der Container den Namen, und Build und Deploy behalten ihn. Ob der Startbildschirm den
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

## Spielsprache

In der Web-UI unter **Spielsprache** (gespeichert in `/config/language`, geht vor `LANGUAGE`, Standard `de`). `build.sh`
schreibt den Code nach `PPSA99025/language.txt`, im selben Format, das das Spiel beim ersten Start selbst anlegt. Das
Spiel liest die erste Zeile, die kein Kommentar ist und einen seiner 16 Codes nennt; ohne Datei spielt es Englisch (US)
(`host/nn_applet.c`, `desired_language`). Die Datei wird bei jedem Build und jedem Deploy geschrieben, eine andere
Sprache braucht also kein neues Kompilieren: Sprache wählen, „Auf die PS5 kopieren".

Im Spiel gibt es außerdem die Zeile „Game language" im Menü (Touchpad-Klick + Options, Reiter Gameplay), die
`language.txt` neu schreibt. Ob das Title auf der Konsole in seinen Ordner schreiben kann (es liest ihn als `/app0`), ist
ungeprüft. Ein späteres Deploy mit geänderter Sprache überschreibt die Wahl aus dem Spiel.

## Auf der PS5

1. „Auf die PS5 kopieren" (oder `AUTO_DEPLOY=true`) legt `PPSA99025` nach `/data/homebrew/PPSA99025`.
2. Die `.nup` gehört laut Upstream nach `/data/eglantineps5/roms/oot.nup`. Gesucht wird sie laut
   `host/ps5/win32_ps5.c` auch unter `/data/eglantineps5/roms/<Name des Dumps>.nup`, `/data/lichii/roms/oot/oot.nup`
   und `/data/prosperoeden/roms/oot/oot.nup`. Eine `.nup` von PS5_Hookshot oder PS5_Lichii wird also gefunden.
   Mit `UPLOAD_NUP=true` kopiert das Deploy die Datei nach `PS5_NUP_PATH`, fortsetzbar (rund 25 GB).
3. Longshot vom Startbildschirm oder dem Homebrew-Launcher starten. Im Spiel öffnet Touchpad-Klick + Options das Menü.

Spielstände (`user/`), `longshot_options.ini` und die Shader-Caches liegen nur auf der Konsole und bleiben beim Deploy
unberührt. `longshot_env.txt` kommt aus dem Build und wird ersetzt.

## Speicher

Das Template begrenzt den Container mit `--memory=12g --memory-swap=12g`. Das Limit muss unter dem RAM liegen, der auf
dem Host tatsächlich frei ist (`free -m`, Spalte available). `pipeline.py` teilt Compiler und Lift nach dem freien RAM
des Hosts ein und sieht ein Container-Limit nicht. Mit Limit setzt `build.sh` deshalb `--jobs` (Kerne − 1, höchstens
Limit ÷ 1,6 GB) und `--lift-jobs` (1 unter 10 GB, sonst (Limit − 4 GB) ÷ 2 GB) selbst. Ein abgebrochener Build setzt beim
nächsten Lauf fort.

## Variablen

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `NUP_FILE` | leer | Pfad der `.nup` im Container. Leer: erste `.nup` mit `0400486024DEC000` im Namen unter `/nup` |
| `MODEL` | `pro` | `pro` oder `base`, solange in der Web-UI nichts gewählt ist |
| `LANGUAGE` | `de` | Spielsprache (`language.txt`), solange in der Web-UI nichts gewählt ist; leer: keine Datei, das Spiel nimmt Englisch (US) |
| `PROJECT` | `longshot` | `longshot` oder `heylisten`, solange in der Web-UI nichts gewählt ist |
| `LONGSHOT_REF` | `latest` | `latest` = neuestes Release, oder ein Tag (`v0.1.0`) |
| `HEYLISTEN_REF` | `latest` | wie `LONGSHOT_REF`, für `heylisten` |
| `LONGSHOT_REPO` | `heydemoura/PS5_Longshot` | GitHub-Repository der Releases |
| `PS5_HOST` | leer | IP der PS5 |
| `PS5_FTP_PORT` | `2121` | FTP-Port |
| `AUTO_DEPLOY` | `false` | nach „Alles bauen" automatisch deployen |
| `UPLOAD_NUP` | `false` | `.nup` beim Deploy mitkopieren |
| `PS5_NUP_PATH` | `/data/eglantineps5/roms/oot.nup` | Ziel für `UPLOAD_NUP` |
| `FORCE_DEPLOY` | `false` | alle Dateien neu hochladen |
| `PUID` / `PGID` | `99` / `100` | Besitzer des Title-Ordners nach dem Build |
| `RUN_ON_START` | `false` | beim Containerstart sofort bauen |
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
