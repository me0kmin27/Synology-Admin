FROM python:3.14-slim
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.revision=$SOURCE_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt requirements-container.txt ./
RUN pip install --no-cache-dir -r requirements-container.txt && pip check \
    && groupadd --gid 10001 portal && useradd --uid 10001 --gid 10001 --no-create-home portal
COPY --chown=10001:10001 . .
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "--config", "deploy/gunicorn.conf.py", "config.wsgi:application"]
