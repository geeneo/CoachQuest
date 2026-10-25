FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ARG BUILD_COMMIT=dev
ARG BUILD_TIME=
ENV BUILD_COMMIT=${BUILD_COMMIT} BUILD_TIME=${BUILD_TIME}

RUN useradd --uid 10001 --create-home coachquest && mkdir -p /data && chown coachquest /data
USER coachquest

EXPOSE 8000
# One worker: the sync scheduler runs in-process and must not run twice.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
