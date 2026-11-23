FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt requirements-cloud.txt ./
RUN pip install --no-cache-dir -r requirements-cloud.txt && useradd --create-home lablink
COPY lablink ./lablink
COPY web ./web
USER lablink
EXPOSE 8080
CMD ["sh","-c","exec uvicorn lablink.main:app --host 0.0.0.0 --port ${PORT:-8080} --no-server-header"]
