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
# The Kartaa landing page (landing/, a separate static site), shown at "/" for visitors without a session (demo/nginx.conf).
# Its build takes the two fonts from /srv/web/node_modules, so it sits next to web/ the way it does in the repository.
COPY landing /srv/landing
# Plain build, no --check: the landing's own rules (no absolute http(s) URLs) are enforced in CI, and must not stop the
# demo image when a privacy or terms link becomes a real https address.
RUN node /srv/landing/build.mjs

# The built app behind nginx, which passes /api through to the API (demo/nginx.conf).
FROM nginx:1.27-alpine AS web
COPY demo/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=webbuild /srv/web/dist /usr/share/nginx/html
COPY --from=webbuild /srv/landing/dist /usr/share/nginx/html/_landing
EXPOSE 5173
