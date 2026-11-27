FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-websocket ca-certificates && rm -rf /var/lib/apt/lists/* \
 && npm install -g @openai/codex@0.172.0 \
 && useradd --system --user-group --home-dir /data/codex --shell /usr/sbin/nologin ha_voice
WORKDIR /app
COPY main.py index.html app.js test_main.py test_app.js capture-worklet.js test_capture.js ./
RUN python3 -m unittest -v test_main && python3 -m py_compile main.py && node --check app.js && node --check capture-worklet.js && node --test test_app.js test_capture.js
CMD ["python3","-u","main.py"]
