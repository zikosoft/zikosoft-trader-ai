"""Modules de stratégie développeur (B11 — Strategy Registry).

Chaque sous-dossier ici est un module de stratégie candidat, découvert et
validé au démarrage par `shared.strategy_registry.load_definitions_from_directory`
(voir `backend/app/strategy_sync.py`) — jamais importé "en dur" par le reste
de l'application. Un nouveau développeur peut ajouter une stratégie en
créant un nouveau sous-dossier ici avec un `DEFINITION` (voir
`strategies/moving_average_crossover/` comme exemple complet) ; elle sera
prise en compte au prochain redémarrage du backend, sans changement de code
ailleurs (§B11 "de nouveaux modules développeur peuvent être ajoutés").

Interdictions du brief B11 : pas d'éditeur Python utilisateur en V1, pas de
JSON interne éditable, pas d'exécution de code fourni dynamiquement par une
requête API — uniquement des fichiers déjà commit dans ce dossier."""
