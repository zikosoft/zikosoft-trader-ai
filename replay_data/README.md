# `replay_data/`

Contient le dataset fixe du Replay Engine (B19) : `dataset.json`, produit par
`scripts/fetch_replay_dataset.py` à partir de vraies données Alpaca (une
journée, quelques symboles — voir le docstring du script pour les commandes
exactes `alpaca data bars ...`).

Ce dossier est intentionnellement vide dans le dépôt et dans l'image Docker
tant que ce script n'a pas été exécuté avec de vraies clés Alpaca — cette
sandbox de développement n'a ni accès réseau vers Alpaca ni les identifiants
pour le faire à ta place (même principe que `scripts/alpaca_cli_backtest.py`,
B12/D021).

Tant que `dataset.json` n'existe pas ici, `GET /api/replay/dataset` répond
honnêtement `404 NOT_FOUND` plutôt que de fabriquer des données — voir
`backend/app/routers/replay.py`.

Pour produire le dataset :

```
python scripts/fetch_replay_dataset.py \
    --trading-day 2026-08-31 \
    --bars AAPL=aapl.csv --bars MSFT=msft.csv --bars SPY=spy.csv \
    --output replay_data/dataset.json
```

(voir le docstring de `scripts/fetch_replay_dataset.py` pour comment
produire les CSV d'entrée avec la CLI Alpaca).
