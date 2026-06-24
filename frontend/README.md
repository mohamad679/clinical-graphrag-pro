# Frontend (Static)

This frontend is a static application served by nginx.

## Structure

- `public/index.html`
- `public/css/main.css`
- `public/js/api.js`
- `public/js/router.js`
- `public/js/components/*.js`

## Runtime

The frontend container serves static files from `/usr/share/nginx/html` using `frontend/nginx.conf`.

Container port: `3000`.

## Local Usage

Run via Docker Compose from repository root:

```bash
docker compose up web
```

The reverse-proxied app is typically accessed via root nginx at `http://localhost/`.

## Notes

- This is not a Next.js/TypeScript project in the current repository state.
- If you introduce a build toolchain later, update this file and root docs accordingly.
