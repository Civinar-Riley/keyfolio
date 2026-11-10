FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    KEYFOLIO_HOST=0.0.0.0 \
    KEYFOLIO_PORT=3000 \
    KEYFOLIO_DATA_DIR=/app/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY app/ app/

RUN mkdir -p /app/data
VOLUME /app/data

EXPOSE 3000

CMD ["python", "main.py"]
