FROM python:3.11-slim

# Instal ffmpeg untuk konversi audio
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# Tambahkan --upgrade di sini agar yt-dlp selalu versi terbaru
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY . .

EXPOSE 10000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
