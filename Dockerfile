FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AGENTGATE_DATA_DIR=/data
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home agentgate && mkdir /data && chown agentgate /data
USER agentgate
EXPOSE 8000
CMD ["python", "-m", "agentgate.docker_entry"]

