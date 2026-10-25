# Proxy image = nginx (auth layer) + the built single-page app.
# Build context is the repo root: docker build -f nginx/Dockerfile .

FROM node:22-alpine AS spa
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ARG BUILD_COMMIT=dev
ENV VITE_BUILD_COMMIT=${BUILD_COMMIT}
RUN npm run build

FROM nginx:1.27-alpine
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx/templates/ /etc/nginx/templates/
COPY --from=spa /src/dist /usr/share/nginx/html
EXPOSE 8080
