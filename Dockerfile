# syntax=docker/dockerfile:1

# ── Frontend ────────────────────────────────────────────────────────────────
#
# Stage aparte: node no hace falta en la imagen final, sólo el resultado del
# build. Mismo patrón que los seis productos.
#
# `frontend/package.json` referencia `libra-ui` por `git+https`, que es lo que
# hace que el dev local en WSL funcione sin identidad SSH propia. Este stage
# reescribe esa URL a SSH con su propia deploy key de solo lectura. Un solo
# mount y un solo `SSH_AUTH_SOCK` alcanzan porque acá hay una sola dependencia
# privada — en el stage de Python, con dos, no alcanza (ver el comentario allá).
FROM node:20-slim AS frontend-build
WORKDIR /frontend
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client && rm -rf /var/lib/apt/lists/*
RUN mkdir -p -m 0700 /root/.ssh && ssh-keyscan github.com >> /root/.ssh/known_hosts 2>/dev/null
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=ssh,id=libra-ui,target=/tmp/ssh-libra-ui.sock \
    SSH_AUTH_SOCK=/tmp/ssh-libra-ui.sock \
    sh -c 'git config --global url."ssh://git@github.com/marianocappucci/libra-ui.git".insteadOf "https://github.com/marianocappucci/libra-ui.git" && \
           npm ci'
COPY frontend/ .
RUN npm run build

# ── Backend ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client curl ca-certificates gnupg && rm -rf /var/lib/apt/lists/*

# CLIENTE de Docker + plugin de compose. **No es opcional**: el backoffice
# administra instancias a través de `libracore.provisioning.panel_admin`, que no
# usa una librería sino que ejecuta `docker inspect` y `docker compose` como
# subprocesos. Montar `/var/run/docker.sock` da acceso al daemon del host, pero
# sin el binario el contenedor levanta y recién falla al listar instancias con
# un `FileNotFoundError: 'docker'` (pasó en el piloto de Gestiolibra).
#
# Sólo el cliente, no el daemon: el contenedor le habla al Docker del host.
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# `pip install .` tiene que resolver libracore Y libraauth en un solo comando,
# así que un `SSH_AUTH_SOCK` global no alcanza: esa variable apunta a un solo
# socket a la vez. Cada dependencia usa su propio alias de Host con
# `IdentityAgent` (de qué socket sale la identidad) e `IdentityFile` apuntando
# a la clave PÚBLICA — que no es secreta y se hornea en la imagen — sólo para
# que ssh sepa qué fingerprint pedirle a ese agente.
#
# `IdentitiesOnly yes` por sí solo NO alcanza: sin un `IdentityFile` explícito
# ssh ofrece los paths default (id_rsa/id_ecdsa/…), que no existen en la
# imagen, y nunca llega a preguntarle nada al agente. Así fallaba en los
# productos: "no more authentication methods to try" con el agente cargado.
#
# Las claves privadas viajan por `--mount=type=ssh` y se descartan con la capa:
# ninguna queda en la imagen.
RUN mkdir -p -m 0700 /root/.ssh \
    && ssh-keyscan github.com >> /root/.ssh/known_hosts 2>/dev/null \
    && printf 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG7oB3H2Rd+xsO/qCUk5aCA14/5GaQFMSh1U0ErJjG55 vps-donweb-libracore-deploy-key\n' > /root/.ssh/id_libracore.pub \
    && printf 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAID0FOGgyaywQLO6J583j9+MG71a13oNpXoxOAAcV9Cbp vps-donweb-libraauth-deploy-readonly\n' > /root/.ssh/id_libraauth.pub \
    && printf 'Host github-libracore\n  HostName github.com\n  User git\n  HostKeyAlias github.com\n  IdentityFile /root/.ssh/id_libracore.pub\n  IdentityAgent /tmp/ssh-libracore.sock\n  IdentitiesOnly yes\n\nHost github-libraauth\n  HostName github.com\n  User git\n  HostKeyAlias github.com\n  IdentityFile /root/.ssh/id_libraauth.pub\n  IdentityAgent /tmp/ssh-libraauth.sock\n  IdentitiesOnly yes\n' > /root/.ssh/config \
    && chmod 600 /root/.ssh/config /root/.ssh/id_libracore.pub /root/.ssh/id_libraauth.pub

COPY backend/ .

# Fuera de /app a propósito, igual que en los productos: si algún día el
# compose monta el checkout sobre /app para desarrollo, un dist copiado
# adentro quedaría tapado por el host. `FRONTEND_DIST` (ver `app.py`) apunta
# acá por defecto.
COPY --from=frontend-build /frontend/dist /opt/frontend-dist

RUN --mount=type=ssh,id=libracore,target=/tmp/ssh-libracore.sock \
    --mount=type=ssh,id=libraauth,target=/tmp/ssh-libraauth.sock \
    git config --global url."ssh://git@github-libracore/marianocappucci/libracore.git".insteadOf "https://github.com/marianocappucci/libracore.git" \
    && git config --global url."ssh://git@github-libraauth/marianocappucci/libraauth.git".insteadOf "https://github.com/marianocappucci/libraauth.git" \
    && pip install --no-cache-dir . \
    && git config --global --unset url."ssh://git@github-libracore/marianocappucci/libracore.git".insteadOf \
    && git config --global --unset url."ssh://git@github-libraauth/marianocappucci/libraauth.git".insteadOf

# Los inyecta el build (`--build-arg`) y los muestra la pantalla de salud. Es
# el dato que delata un contenedor que "responde 200" pero está corriendo la
# imagen anterior.
ARG APP_VERSION=desconocida
ARG APP_COMMIT=desconocido
ENV APP_VERSION=$APP_VERSION APP_COMMIT=$APP_COMMIT

EXPOSE 8000

CMD ["uvicorn", "libra_backoffice.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
