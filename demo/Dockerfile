# Images for the local demo only (docker-compose.demo.yml). Never deployed anywhere.
# One Python image runs the migrations, the API, the seed step and the code watcher;
# one Node image serves the web app and passes /api through to the API.

FROM python:3.12-slim AS api
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY libs/platform_common libs/platform_common
COPY app app
COPY migrator migrator
COPY refdata refdata
RUN pip install -e libs/platform_common -e "app[dev]" -r migrator/requirements.txt
COPY demo demo
ENV PLATFORM_ENV=local

FROM node:22-slim AS web
WORKDIR /srv/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY web ./
# Only this build knows it is the demo: sign-up screens say the code is in the terminal.
ENV VITE_DEMO=1
RUN npx vite build
EXPOSE 5173
CMD ["npx", "vite", "preview", "--host", "0.0.0.0"]
