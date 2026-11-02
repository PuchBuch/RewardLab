# Сборка из папки microservices/:  docker build -f games/Dockerfile -t rewardlab-games .
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home app && mkdir /data && chown app /data
COPY common ./common
COPY games ./games
USER app
ENV HOST=0.0.0.0 DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 5003
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5003/health')"
CMD ["python", "-m", "games.app"]
