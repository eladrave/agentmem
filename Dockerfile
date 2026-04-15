FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt google-generativeai

COPY src/ ./src/

ENV DATA_DIR=/data
ENV PYTHONPATH=/app
# Cloud Run sets the PORT environment variable, defaulting to 8080
ENV PORT=8080

EXPOSE 8080

CMD sh -c "uvicorn src.main:app --host 0.0.0.0 --port ${PORT}"
