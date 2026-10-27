# Build the static app, then serve it with nginx. nginx sends /api/* to the FastAPI service.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG VITE_USE_MOCKS=false
ARG VITE_API_BASE=/api
# Admin login (see README): the user name and the SHA-256 hash of the password. Empty: demo default; off: none.
ARG VITE_ADMIN_USERNAME=admin
ARG VITE_ADMIN_PASSWORD_SHA256=
ENV VITE_USE_MOCKS=$VITE_USE_MOCKS VITE_API_BASE=$VITE_API_BASE \
    VITE_ADMIN_USERNAME=$VITE_ADMIN_USERNAME VITE_ADMIN_PASSWORD_SHA256=$VITE_ADMIN_PASSWORD_SHA256
RUN npx vite build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
