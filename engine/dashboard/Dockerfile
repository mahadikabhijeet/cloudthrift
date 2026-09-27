FROM python:3.12-slim

WORKDIR /app

COPY dashboard/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY shared/          ./shared/
COPY src/engine/ ./src/engine/
COPY dashboard/app/    ./app/

# Data directory for dashboard JSON files (mount a volume here in production)
RUN mkdir -p ./data

ENV PORT=8000
ENV DATA_DIR=/app/data

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
