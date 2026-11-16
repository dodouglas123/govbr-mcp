FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv/govbr
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt \
    && groupadd --gid 10101 govbr \
    && useradd --no-create-home --uid 10101 --gid 10101 govbr
COPY alembic.ini ./
COPY migrations/ migrations/
COPY govbr/ govbr/
USER 10101:10101
EXPOSE 8000
CMD ["python", "-m", "govbr", "serve", "--host", "0.0.0.0"]
