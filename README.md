# ZikosoftTrader AI

> Documentation publique complète prévue en phase finale (B34). Ce README est un
> squelette technique pour la phase de développement (socle B01–B04, B36 partiel,
> B05 auth, B06 contextes — voir `AVANCEMENT.md`) — il ne doit pas être considéré
> comme la doc de soumission.

## Démarrage rapide (socle actuel)

```bash
cp .env.example .env
# éditer .env si besoin (valeurs par défaut utilisables en local)
make up-core        # socle applicatif : postgres, redis, backend-api,
                     # frontend, les 4 agents et les 4 workers (squelettes
                     # tant que leur brique métier n'est pas livrée)
# équivalent : docker compose up -d --build (pas de profil à passer)
```

Tous les services applicatifs sont déclarés dès le jour 1, même quand leur
logique métier est encore un squelette — voir AVANCEMENT.md pour l'état réel
brique par brique. Ils n'ont volontairement **aucun profil** : `docker
compose up -d --build` seul suffit. Seule la stack `observability`
(Prometheus/Loki/Grafana, B24) est derrière un profil, optionnel :

```bash
make up             # socle + observability
# équivalent : docker compose --profile observability up -d --build
```

`docker compose --profile observability config` valide le fichier sans
nécessiter de daemon Docker actif — c'est ce qui a servi à valider
`docker-compose.yml` pendant le développement de cette brique.

Migrations et seed (une fois `postgres` up) :

```bash
make migrate
make seed   # optionnel — backend-api le fait déjà tout seul au démarrage (B05)
make test
```

Une fois les conteneurs démarrés, l'app est sur `http://localhost:5173` —
formulaire de connexion préchargé avec les identifiants démo (voir
`DEMO_USER_EMAIL`/`DEMO_USER_PASSWORD` dans `.env`), puis écran "Choose your
experience" (Historical Replay / Alpaca Paper, B06).

## Structure du monorepo

```text
zikosofttrader-ai/
├── docker-compose.yml    # 15 services, profils core/observability (B02)
├── Makefile              # up / up-core / migrate / seed / test / config
├── frontend/             # React/TypeScript — login (B05), contextes (B06), shell complet en B25
├── backend/              # FastAPI — API, migrations, modèles, auth (B05), contextes (B06)
├── agents/                # Agents IA : market, strategy, risk-critic, execution-explanation
├── workers/               # Composants déterministes : risk-engine, order-worker, alert-worker, watchdog
├── strategies/             # Modules de stratégie développeur (B11-B12)
├── scripts/                # Outillage hors runtime (B12 — artefact backtest CLI Alpaca, §D021)
├── shared/                 # Package Python partagé : contrats d'événement, erreurs, logs, AIProvider
├── infra/                  # Config Prometheus/Loki/Grafana (B24) — squelette fonctionnel dès B02
├── demo/replay/            # Dataset Replay figé (B19)
├── tests/                  # Tests globaux (B33) — 31 tests socle en place (B01-B04, B05, B06, B36)
└── docs/                   # Documentation publique (B34)
```

## Contrats (socle B01–B04, B05, B06)

- Enveloppe d'événement Redis Streams : `shared/shared/events.py`
- Format d'erreur API commun : `shared/shared/errors.py` (appliqué à toute `HTTPException`, pas seulement au 500, voir `backend/app/main.py`)
- Journal d'erreurs applicatif (B36) : `shared/shared/error_log.py`
- Bus d'événements (consumer groups, retry, dead-letter) : `shared/shared/eventbus.py`
- Interface AIProvider (D017/D026) : `shared/shared/ai_provider.py`
- Schéma PostgreSQL : `backend/app/models/`, migrations dans `backend/alembic/versions/`
- Authentification locale (B05) : `backend/app/auth.py` (`get_current_user`, à réutiliser par toute route métier future), `backend/app/security.py` (hachage mot de passe/jeton), `backend/app/rate_limit.py`
- Contextes Replay/Paper (B06) : `backend/app/context.py` (`switch_context`, `ContextConfirmationRequired`), `execution_contexts`/`execution_context_switches` (schéma), événement `context.switched` sur `system.events` (contrat pour B10+)

Voir `AVANCEMENT.md` à la racine du dépôt (fourni séparément, pas encore
committé — document de suivi vivant) pour le détail brique par brique, les
décisions (D001–D029) et les risques.

## Artefact CLI Alpaca (§D021 — troisième technologie nommée par le hackathon)

Le hackathon nomme explicitement trois technologies Alpaca à mettre en
avant : la **Trading API** (déjà exercée par `backend/app/alpaca_client.py`,
B07), le **serveur MCP** (déjà exercé par `agents/market_agent`, B10), et le
**CLI officiel** (`github.com/alpacahq/cli`) — jusqu'ici sous-exploité dans
ce projet. `scripts/alpaca_cli_backtest.py` (B12) comble ce manque : il
rejoue une stratégie déterministe déjà livrée (`moving_average_crossover`
ou `rsi_reversal`) — avec le MÊME code que le Strategy Agent exécute en
production, pas une réimplémentation séparée — sur un historique de
bougies exporté par le CLI Alpaca, et compare son rendement à un benchmark
buy-and-hold. Les hypothèses de simulation (aucun frais, long-only, biais
de look-ahead assumé — l'exécution a lieu au cours de clôture de la bougie
qui a généré le signal) sont formalisées en toutes lettres dans la
docstring du script.

**Important :** ce script ne contient aucune donnée de marché et Claude n'a
jamais eu accès aux identifiants Alpaca de Zac ni à un accès réseau sortant
vers l'API Alpaca depuis son environnement de développement (voir
CONTRIBUTING.md) — produire l'artefact réel ci-dessous est donc une étape
que **Zac exécute lui-même**, avec ses propres clés Paper :

```bash
# 1. Installer le CLI officiel (une fois)
brew install alpacahq/tap/cli
# ou : go install github.com/alpacahq/cli/cmd/alpaca@latest

# 2. S'authentifier avec ses propres clés Alpaca Paper
alpaca profile login

# 3. Exporter un historique de bougies
alpaca data bars --symbol AAPL --start 2025-01-01 --end 2025-12-31 \
    --timeframe 1Day --csv > aapl_2025.csv

# 4. Lancer le backtest (depuis la racine du monorepo, venv backend actif)
python scripts/alpaca_cli_backtest.py --input aapl_2025.csv \
    --strategy moving_average_crossover --symbol AAPL
```

<!--
TODO (Zac) : coller ici la sortie du script (ou une capture d'écran du
terminal) une fois exécutée avec de vraies données Alpaca — c'est le
dernier geste manquant pour clore §D021/B12 "Artefact CLI Alpaca" dans
AVANCEMENT.md. Le script lui-même est livré, testé (voir
`tests/test_alpaca_cli_backtest.py`, données synthétiques) et fonctionnel ;
seule l'exécution contre de vraies données/clés reste hors de portée de
l'environnement de développement de Claude.
-->

Tests unitaires du script (données synthétiques, pas un vrai backtest) :
`tests/test_alpaca_cli_backtest.py`.
