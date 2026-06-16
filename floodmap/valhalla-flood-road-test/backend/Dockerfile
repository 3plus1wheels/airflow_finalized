FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir boto3

COPY backend ./backend
COPY scripts ./scripts
COPY data ./data

ENV HOST=0.0.0.0
ENV PORT=8010
ENV VALHALLA_URL=http://valhalla:8002

EXPOSE 8010

CMD ["python", "backend/server.py"]
