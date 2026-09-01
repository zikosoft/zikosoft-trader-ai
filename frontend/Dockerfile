# Squelette (B01-B04) : sert le dev server Vite directement en dev. Un build
# de production (multi-stage, nginx) sera ajouté quand le vrai shell (B25)
# sera en place — inutile de l'optimiser avant d'avoir du contenu réel.
FROM node:20-slim AS base

WORKDIR /srv/frontend

COPY frontend/package.json /srv/frontend/package.json
RUN npm install

COPY frontend /srv/frontend

ENV HOST=0.0.0.0
EXPOSE 5173

CMD ["npm", "run", "dev"]
