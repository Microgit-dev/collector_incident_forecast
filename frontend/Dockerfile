# Сборка SPA на Node, раздача статикой через Caddy (он же TLS и reverse proxy)
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM caddy:2-builder-alpine AS caddy-build

# goproxy.cn - go mirror
ENV GOPROXY=https://goproxy.cn,direct \
    GOSUMDB=off

RUN xcaddy build \
    --with github.com/caddy-dns/duckdns

FROM caddy:2-alpine
COPY --from=caddy-build /usr/bin/caddy /usr/bin/caddy
COPY --from=build /app/dist /srv
EXPOSE 80 443 2019
