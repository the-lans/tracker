FROM node:20-slim AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html

# TODO: заменить дефолтный nginx.conf на конфигурацию с SPA-фолбэком на index.html
# (все не-файловые пути -> /index.html), когда появится клиентский роутинг.
EXPOSE 80
