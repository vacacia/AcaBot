FROM python:3.11-slim

WORKDIR /app

RUN pip install uv --no-cache-dir


COPY pyproject.toml ./
RUN uv pip install --system -e "."


COPY src/ src/
COPY plugins/ plugins/

EXPOSE 8080

ENV PYTHONPATH=/app/src

CMD ["python", "-m", "acabot.main"]
