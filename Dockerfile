FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    KEYFOLIO_HOST=0.0.0.0 \
    KEYFOLIO_PORT=7465 \
    KEYFOLIO_DATA_DIR=/app/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY app/ app/

RUN mkdir -p /app/data
VOLUME /app/data

EXPOSE 7465

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7465/api/health', timeout=3)"

CMD ["python", "main.py"]
