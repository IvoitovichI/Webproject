FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    APP_NAME="Docker Fundamentals" \
    APP_MESSAGE="The application is running in a container."

WORKDIR /app

RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup --no-create-home appuser

COPY --chown=appuser:appgroup app.py ./app.py

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8080') + '/health', timeout=2)"

CMD ["python", "app.py"]
