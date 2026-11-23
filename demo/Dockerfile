# Images for the local demo only (docker-compose.demo.yml). Never deployed anywhere.
# One Python image runs the migrations, the API, the seed step and the code watcher;
# nginx serves the built web app and passes /api through to the API; the renderer image
# draws PDF previews with the cloud renderer's own code (demo/render_watch.py, #387).

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

# The PDF renderer, built by scripts/build_renderer.py from the same locks as the Lambda zip (same WeasyPrint, pango,
# Noto fonts and templates), for this computer's processor. The build downloads the pinned, hash-checked packages and
# fonts the first time; Docker caches the result.
FROM python:3.12-slim AS rendererbuild
WORKDIR /srv
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends binutils && rm -rf /var/lib/apt/lists/*
RUN pip install zstandard==0.25.0
COPY scripts/build_renderer.py scripts/build_renderer.py
COPY renderer renderer
RUN set -e; arch="$(uname -m)"; python scripts/build_renderer.py --arch "$arch"; \
    case "$arch" in aarch64) zip=build/renderer.zip ;; *) zip="build/renderer-$arch.zip" ;; esac; \
    python -c "import zipfile, sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$zip" /srv/renderer-task

FROM python:3.12-slim AS renderer
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 RENDERER_TASK=/srv/renderer-task
COPY --from=rendererbuild /srv/renderer-task /srv/renderer-task
COPY demo/render_watch.py demo/render_watch.py
CMD ["python", "demo/render_watch.py", "/srv/build/objects"]
