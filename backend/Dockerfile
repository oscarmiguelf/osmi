FROM python:3.12-slim

WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

# Run without root; the uploads folder (a volume) belongs to that user
RUN useradd --system --uid 10001 --no-create-home app && mkdir -p /data/uploads && chown app /data/uploads
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
