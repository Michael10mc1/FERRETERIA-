FROM node:22-bookworm-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY vite.config.ts tsconfig*.json ./
COPY frontend ./frontend
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY --from=frontend /app/dist ./dist
RUN useradd --create-home horizonte && mkdir -p /app/backend/data && chown -R horizonte:horizonte /app
USER horizonte
EXPOSE 8000
# One worker preserves the background-agent execution contract.
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers"]
