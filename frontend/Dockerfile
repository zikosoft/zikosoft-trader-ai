
FROM node:20-slim AS base

WORKDIR /srv/frontend

COPY frontend/package.json /srv/frontend/package.json
RUN npm install

COPY frontend /srv/frontend

ENV HOST=0.0.0.0
EXPOSE 5173

CMD ["npm", "run", "dev"]
