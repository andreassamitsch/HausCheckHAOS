FROM python:3.13-alpine
WORKDIR /app
COPY server.py discovery.py /app/
RUN addgroup -S diag && adduser -S -G diag diag
EXPOSE 8099
CMD ["python", "-u", "/app/server.py"]
