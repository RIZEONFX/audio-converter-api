FROM python:3.11-slim

# Instal ffmpeg (wajib untuk konversi audio)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements dan install dependencies (pastikan yt-dlp versi terbaru)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copy sisa kode aplikasi
COPY . .

# Expose port (gunakan 8000 agar sesuai dengan perintah uvicorn di bawah)
EXPOSE 8000

# Jalankan server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
