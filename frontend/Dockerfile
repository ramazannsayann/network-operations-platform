# syntax=docker/dockerfile:1

# ---- build: compile the React app to static files ----
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
RUN npm run build

# ---- runtime: nginx serves the app and reverse-proxies /api and /ws to the api service ----
FROM nginx:1.30-alpine
# "nginx-conf" is an additional build context (deploy/nginx) set in deploy/docker-compose.yml.
COPY --from=nginx-conf default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
