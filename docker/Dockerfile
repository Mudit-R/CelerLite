FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .
RUN useradd -m -u 1000 celerlite && chown -R celerlite:celerlite /app
USER celerlite
EXPOSE 8000
CMD ["python", "run.py"]
