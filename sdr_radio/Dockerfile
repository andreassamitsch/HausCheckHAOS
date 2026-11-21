FROM ghcr.io/home-assistant/base:3.24
RUN apk add --no-cache python3 rtl-sdr ffmpeg
WORKDIR /app
COPY main.py /app/main.py
COPY radio_metadata.py /app/radio_metadata.py
COPY sdr_scan.py /app/sdr_scan.py
COPY index.html /app/index.html
COPY run.sh /run.sh
RUN chmod 755 /run.sh
CMD ["/run.sh"]
