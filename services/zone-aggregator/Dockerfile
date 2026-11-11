FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
ARG ZONE=north
ARG PORT=5100
ENV ZONE=${ZONE}
ENV PORT=${PORT}
RUN mkdir -p /var/log/zone-aggregator-${ZONE}
EXPOSE ${PORT}
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
