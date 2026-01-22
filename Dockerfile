FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY web_server.py .
COPY session_manager.py .
COPY telegram_client.py .
COPY bot_notifier.py .
COPY models.py .
COPY config.py .
COPY static/ ./static/

# Create data and logs directories
RUN mkdir -p /app/data /app/logs

# Default port
ENV PORT=8000

# Expose port for Web server
EXPOSE ${PORT}

# Run Web server with configurable port
CMD uvicorn web_server:app --host 0.0.0.0 --port ${PORT}
