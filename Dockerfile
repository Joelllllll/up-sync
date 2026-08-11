# We need gcc to install psycopg2. Instead of keeping gcc in the final image,
# we install it here, do the pip install, then copy the result over.
FROM python:3.11-slim AS build

WORKDIR /code

RUN apt-get update && apt-get install -y gcc libpq-dev build-essential && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /code/requirements.txt
RUN pip install --prefix=/install --no-cache-dir -r /code/requirements.txt

COPY ./app /code/app

# The actual image we run: no gcc, just the installed packages + app code.
FROM python:3.11-slim

WORKDIR /code

COPY --from=build /install /usr/local

COPY --from=build /code/app /code/app

