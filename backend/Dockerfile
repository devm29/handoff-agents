FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY pyproject.toml ./
COPY src ./src
RUN pip wheel --wheel-dir /wheels .

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    HANDOFF_API_HOST=0.0.0.0 HANDOFF_LOG_JSON=true
RUN useradd --create-home --uid 10001 handoff
COPY --from=build /wheels /wheels
RUN pip install /wheels/*.whl && rm -rf /wheels
USER handoff
WORKDIR /home/handoff
EXPOSE 8104
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8104/api/healthz')" || exit 1
CMD ["handoff", "api"]
