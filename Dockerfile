# Build from the Ares repository root: docker build -t smk-link-ares .
FROM debian:trixie-slim
ARG JOBS=4
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build pkg-config python3 ca-certificates \
    libgtk-3-dev libxrandr-dev libgl-dev libglx-dev libopengl-dev libxv-dev \
    libao-dev libopenal-dev libsdl3-dev \
    && rm -rf /var/lib/apt/lists/*
COPY . /src/ares
RUN --mount=type=cache,id=smk-link-ares-build,sharing=locked,target=/tmp/ares-build cmake -S /src/ares -B /tmp/ares-build -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DARES_CORES=sfc -DARES_SKIP_DEPS=ON -DARES_ENABLE_LIBRASHADER=OFF \
    -DARES_ENABLE_CHD=OFF -DENABLE_IPO=OFF -DENABLE_CCACHE=OFF \
    -DARES_BUILD_LOCAL=OFF -DARES_BUILD_LINK_LAB=ON \
    && cmake --build /tmp/ares-build -j "$JOBS" \
    && mkdir -p /opt/link/bin \
    && cp /tmp/ares-build/tools/link-lab/ares-link-worker /opt/link/bin/ \
    && cp -r /src/ares/mia/Database /opt/link/bin/ \
    && cp -Lr /tmp/ares-build/rundir /opt/link/desktop \
    && cp /src/ares/tools/link-lab/*.py /opt/link/ \
    && chmod -R a+rX /opt/link \
    && rm -rf /src/ares
ENV XDG_CONFIG_HOME=/tmp/ares-config XDG_DATA_HOME=/tmp/ares-data XDG_CACHE_HOME=/tmp/ares-cache
ENTRYPOINT ["python3", "/opt/link/play.py"]
CMD ["--help"]
