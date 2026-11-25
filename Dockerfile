
FROM python:3.11-slim

# Install FFmpeg dan kebutuhan Deno
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Deno JavaScript runtime
RUN curl -fsSL https://deno.land/install.sh | sh

# Tambahkan Deno ke PATH
ENV PATH="/root/.deno/bin:${PATH}"

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copy backend
COPY . .

EXPOSE 10000

RUN deno --version && \
    python -m pip show yt-dlp && \
    python -m pip show yt-dlp-ejs

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
