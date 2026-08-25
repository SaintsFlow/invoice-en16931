# One image does both jobs: it serves the API and it runs the checks, so the
# machine you work from needs docker and nothing else.
FROM python:3.12-slim

# Tesseract with the English and German language packs, plus poppler: tesseract
# reads images, not PDFs, so pdftoppm renders the pages first.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-deu \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

ARG UV_VERSION=0.12.5
RUN pip install --no-cache-dir "uv==${UV_VERSION}"

# The environment lives outside /app on purpose: compose mounts the project
# over /app, and anything inside would disappear behind the mount.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies get their own layer, so editing code does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY . .

EXPOSE 8080
CMD ["uv", "run", "--frozen", "uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8080"]
