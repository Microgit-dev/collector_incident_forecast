# Сборка SPA на Node, раздача статикой через Caddy (он же TLS и reverse proxy)
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
EXPOSE 80 443 2019
