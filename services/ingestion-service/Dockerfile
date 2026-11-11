FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
RUN mkdir -p /var/log/ingestion
EXPOSE 5200
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5200"]
