# Multi-stage not needed for a 2-dependency Flask app; keep it small + non-root.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user (security best practice)
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

EXPOSE 5000

# gunicorn, not the Flask dev server
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "main:app"]
