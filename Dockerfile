# ps5-longshot-builder: baut heydemoura/PS5_Longshot (PS5-Title PPSA99025) oder cosmicflow2512/PS5_HeyListen (PPSA99026)
# aus der eigenen .nup, ohne Fenster.
# Compiler (llvm-mingws LLVM mit PS5-Ziel), Python, Kit und ps5-native-tool bringt die offizielle Builder-AppImage mit
# (zur Laufzeit nach /config geladen, gegen ihre .sha256 geprueft). Das Image braucht nur Download, Web-UI und FTP,
# plus gcc fuer zbic.so, die der AppImage fehlt (scripts/build.sh ensure_zbic).
FROM ubuntu:24.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl git python3 zlib1g libstdc++6 file gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

ENV CONFIG_DIR=/config \
    NUP_DIR=/nup \
    OUT_DIR=/output \
    WEBUI_PORT=8486 \
    PYTHONUNBUFFERED=1

ARG GIT_SHA=unbekannt
ENV IMAGE_REV=${GIT_SHA}
COPY scripts/ /app/scripts/
COPY webui/ /app/webui/
RUN chmod +x /app/scripts/*.sh

EXPOSE 8486
VOLUME ["/config"]
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
