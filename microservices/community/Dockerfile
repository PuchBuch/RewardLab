# Сборка из папки microservices/:  docker build -f community/Dockerfile -t rewardlab-community .
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home app && mkdir /data && chown app /data
COPY common ./common
COPY community ./community
USER app
ENV HOST=0.0.0.0 DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 5004
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5004/health')"
CMD ["python", "-m", "community.app"]
