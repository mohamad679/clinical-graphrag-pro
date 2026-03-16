FROM nginx:alpine

# Copy the custom Nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy the static frontend files
COPY public /usr/share/nginx/html

EXPOSE 3000

# The healthcheck is already defined in docker-compose.yml using wget
