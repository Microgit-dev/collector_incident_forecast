# Сервис ИИ-выделения зданий по спутниковому снимку: Segment Anything (vit_b) на CPU.
# Образ тяжёлый (PyTorch CPU ~ 800 МБ + чекпойнт 375 МБ), поэтому сервис — в профиле compose «ai».
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SEGMENTER_DATA=/data SAM_CHECKPOINT=/opt/sam/sam_vit_b_01ec64.pth

WORKDIR /app
# колёса PyTorch только для CPU: без них pip тянет сборку CUDA на несколько гигабайт
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# чекпойнт Meta SAM ViT-B (Apache 2.0) — в образ, чтобы сервис работал без доступа к dl.fbaipublicfiles.com
ADD --chmod=644 https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth /opt/sam/sam_vit_b_01ec64.pth

COPY app ./app
RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app /data
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
