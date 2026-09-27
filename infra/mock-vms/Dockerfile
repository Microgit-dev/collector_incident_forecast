# Эмулятор системы видеонаблюдения заказчика: только стандартная библиотека Python
FROM python:3.12-slim
WORKDIR /app
COPY app.py .
RUN useradd --create-home --uid 1000 app
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"
CMD ["python", "app.py"]
