# Build redsea from a pinned upstream release. The decoder reads
# the FM multiplex from rtl_fm; no second SDR receiver is required.
FROM debian:bookworm-slim AS redsea-builder
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    git ca-certificates g++ meson ninja-build pkg-config \
    libsndfile1-dev libliquid-dev nlohmann-json3-dev \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch v1.3.1 https://github.com/windytan/redsea.git /src/redsea \
 && meson setup /src/redsea/build /src/redsea -Dbuild_tests=false \
 && meson compile -C /src/redsea/build

FROM debian:bookworm-slim
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 python3-venv rtl-sdr ffmpeg libsndfile1 libliquid1 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/sdr-venv \
 && /opt/sdr-venv/bin/pip install --no-cache-dir "ytmusicapi>=1.10,<2" "paho-mqtt>=2.1,<3"
ENV PATH="/opt/sdr-venv/bin:$PATH"
COPY --from=redsea-builder /src/redsea/build/redsea /usr/local/bin/redsea
WORKDIR /app
COPY main.py radio_metadata.py sdr_scan.py rds_state.py rtr_catalog.py mqtt_bridge.py index.html /app/
COPY run.sh /run.sh
RUN chmod 755 /run.sh
CMD ["/run.sh"]
