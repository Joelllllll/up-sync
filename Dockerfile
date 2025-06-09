# Stage 1: Build stage
FROM python:3.11-slim AS build

WORKDIR /code

RUN apt-get update && apt-get install -y gcc libpq-dev build-essential && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /code/requirements.txt
RUN pip install --prefix=/install --no-cache-dir -r /code/requirements.txt

COPY ./app /code/app

# Stage 2: Final runtime stage
FROM python:3.11-slim

WORKDIR /code

COPY --from=build /install /usr/local

COPY --from=build /code/app /code/app

CMD ["python", "-m", "http.server", "8000"]
