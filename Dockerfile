FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DENO_INSTALL=/usr/local \
    PATH="/usr/local/bin:${PATH}"

# FFmpeg performs the MP3 extraction. Deno is yt-dlp's recommended JS runtime.
# unzip is required by Deno's installer. tar is used to unpack the BgUtils provider.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        tar \
        unzip \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://deno.land/install.sh | sh

# Install the current BgUtils PO-token provider server.
# yt-dlp's current YouTube guidance recommends a PO-token provider for mweb GVS requests.
WORKDIR /opt/bgutil-ytdlp-pot-provider
RUN curl -fsSL https://github.com/Brainicism/bgutil-ytdlp-pot-provider/archive/refs/tags/2.0.1.tar.gz \
    | tar -xz --strip-components=1
RUN cd /opt/bgutil-ytdlp-pot-provider/server \
    && deno install --allow-scripts=npm:canvas --frozen

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY start.sh ./
COPY templates ./templates
COPY static ./static

RUN chmod +x /app/start.sh

EXPOSE 8080
CMD ["/app/start.sh"]
