FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY app.py ./
COPY static ./static
COPY templates ./templates
RUN useradd -r -m -u 10001 app && chown -R app /app
USER app
CMD ["gunicorn", "--workers", "1", "--threads", "8", "--timeout", "300", "--bind", "0.0.0.0:5001", "app:app"]
