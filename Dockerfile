FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WHISPER_MODEL=base
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng \
    tesseract-ocr-jpn tesseract-ocr-kor tesseract-ocr-fra tesseract-ocr-spa \
    tesseract-ocr-deu tesseract-ocr-ita tesseract-ocr-por tesseract-ocr-ara tesseract-ocr-rus \
    fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/work
EXPOSE 8000
CMD ["sh","-c","uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
