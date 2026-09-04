FROM node:20-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# Unprivileged image so the container runs as a non-root user end-to-end
# (the stock nginx image only drops its worker processes to non-root; the
# master process stays root to bind port 80).
FROM nginxinc/nginx-unprivileged:1.27-alpine AS serve

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080
