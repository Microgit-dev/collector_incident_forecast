# Симулятор СМВУ: стандартная библиотека Python + клиент Kafka
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir confluent-kafka==2.15.1
COPY fieldsim ./fieldsim
COPY polygon ./polygon
RUN useradd --create-home --uid 1000 app
USER app
ENV SIM_CATALOG=/app/polygon SIM_SINK=kafka PYTHONUNBUFFERED=1
EXPOSE 8095
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8095/health')"
ENTRYPOINT ["python", "-m", "fieldsim"]
CMD ["serve"]
