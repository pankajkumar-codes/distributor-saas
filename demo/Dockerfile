# Images for the local demo only (docker-compose.demo.yml). Never deployed anywhere.
# One Python image runs the migrations, the API, the seed step and the code watcher;
# nginx serves the built web app and passes /api through to the API.

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

FROM node:22-slim AS webbuild
WORKDIR /srv/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY web ./
# Only this build knows it is the demo: sign-up screens say the code is in the terminal.
ENV VITE_DEMO=1
RUN npx vite build

# The built app behind nginx, which passes /api through to the API (demo/nginx.conf).
FROM nginx:1.27-alpine AS web
COPY demo/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=webbuild /srv/web/dist /usr/share/nginx/html
EXPOSE 5173
