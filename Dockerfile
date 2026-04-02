FROM python:3.11-slim
WORKDIR /app

RUN pip install uv --no-cache-dir

COPY pyproject.toml ./
COPY src/ src/
RUN uv pip install --system .

COPY extensions/ extensions/

EXPOSE 8080 8765
ENV PYTHONPATH=/app/src:/app/extensions
CMD ["python", "-m", "acabot.main"]
