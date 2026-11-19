# Optional: the API with poppler (pdftotext), for the Congress page's PDF reading (Bloco 10).
# Render's native Python runtime does not list poppler-utils (https://render.com/docs/native-environments);
# the default deploy (render.yaml, runtime: python) keeps working without it and shows the PDF link.
# To use this image instead: in render.yaml set `runtime: docker` and `dockerfilePath: ./Dockerfile`
# (rootDir stays `backend`) and remove buildCommand/startCommand. Not built or tested yet (no Docker on
# the development machine).
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY vendor ./vendor

ENV PORT=10000
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-server-header"]
