# Branding files

Replace these two files directly, keeping the same paths and file names:

- `frontend/public/branding/logo.png` — header wordmark, rendered inside a
  responsive 190 × 32 px area on desktop.
- `frontend/public/favicon.svg` — browser favicon, square SVG preferred.

Use SVG where possible. If a PNG is required, update both the filename in
`frontend/index.html` and the header source in `frontend/src/AppShell.tsx`.
Do not place secrets or private metadata in either asset.
