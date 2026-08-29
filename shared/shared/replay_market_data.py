"""ReplayDataset / ReplayMarketDataProvider — B19 Étape A ("squelette
minimal" du Replay Engine, voir AVANCEMENT.md §"Séquencement révisé").

**Ce module ne contient AUCUNE donnée de marché** — même principe que
`scripts/alpaca_cli_backtest.py` (B12/D021) : cette sandbox n'a ni accès
réseau sortant vers Alpaca ni tes identifiants (voir AVANCEMENT.md §39,
limite réseau récurrente). `scripts/fetch_replay_dataset.py` est le script
que TOI (Zac) exécutes avec tes propres clés/CLI pour produire le fichier
réel (`replay_data/dataset.json`, voir son emplacement dans
`DEFAULT_REPLAY_DATASET_PATH` ci-dessous) — ce module se contente de le lire
et de le rejouer, une fois qu'il existe.

**Axe de temps partagé, pas un index par symbole** : `ReplayDataset.bars`
associe chaque symbole à une liste de `ReplayBar` de MÊME LONGUEUR que
`ReplayDataset.timestamps`, alignée bougie par bougie — `bars[symbol][i]`
correspond toujours à `timestamps[i]`. Ce choix (plutôt qu'un index
indépendant par symbole) modélise un rythme de marché simulé unique et
partagé par TOUS les symboles rejoués en même temps (cohérent avec "Play/
Pause" et "x1/x2/x5/x10" qui contrôlent UNE seule horloge de session, pas
une par symbole) — la construction (`build_dataset`) échoue explicitement
plutôt que d'inventer une bougie manquante si un symbole n'a pas de
donnée à un horodatage où les autres en ont une (voir
`validate_no_blocking_gaps` et son appel dans `build_dataset`).

**Étape A = lecture x1 simple, pas de Play/Pause/x2-x5-x10** : `advance()`
avance TOUJOURS d'exactement une bougie, appelée explicitement par
l'appelant (voir `backend/app/routers/replay.py::POST /api/replay/session/advance`)
— aucune boucle temps-réel/thread ici. L'accélération (x2/x5/x10) et un
autoplay minuté sont explicitement des ajouts d'Étape B (voir
AVANCEMENT.md, séquencement révisé), pas construits ici."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REPLAY_DATASET_PATH = Path(__file__).resolve().parents[2] / "replay_data" / "dataset.json"

# §checklist B19 "Valider absence de trous bloquants" — un trou de plus de
# ce multiple de l'intervalle attendu (ex. 3 x 60s = 180s pour du 1Min) est
# considéré bloquant. Un trou plus petit est toléré (marché parfois inactif
# une minute sur un symbole peu liquide, sans que ce soit une anomalie).
DEFAULT_MAX_GAP_MULTIPLIER = 3.0


class ReplayDatasetError(Exception):
    """Base commune — dataset introuvable, invalide, ou trou bloquant."""


@dataclass(frozen=True)
class ReplayBar:
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> dict:
        return {"open": self.open, "high": self.high, "low": self.low, "close": self.close, "volume": self.volume}

    @staticmethod
    def from_dict(raw: dict) -> ReplayBar:
        return ReplayBar(
            open=float(raw["open"]),
            high=float(raw["high"]),
            low=float(raw["low"]),
            close=float(raw["close"]),
            volume=float(raw["volume"]),
        )


@dataclass(frozen=True)
class ReplayDataset:
    dataset_id: str
    trading_day: str  # "YYYY-MM-DD"
    timezone: str  # fuseau des horodatages bruts à la source (§checklist "Documenter fuseau horaire")
    symbols: tuple[str, ...]
    timestamps: tuple[str, ...]  # ISO8601 UTC, triés, axe de temps partagé
    bars: dict[str, tuple[ReplayBar, ...]]  # bars[symbol][i] <-> timestamps[i], même longueur pour tous
    checksum: str

    def to_dict(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "trading_day": self.trading_day,
            "timezone": self.timezone,
            "symbols": list(self.symbols),
            "timestamps": list(self.timestamps),
            "bars": {symbol: [b.to_dict() for b in bars] for symbol, bars in self.bars.items()},
            "checksum": self.checksum,
        }


def compute_checksum(*, dataset_id: str, trading_day: str, symbols: tuple[str, ...], timestamps: tuple[str, ...], bars: dict[str, tuple[ReplayBar, ...]]) -> str:
    """§checklist "Ajouter fingerprint/checksum" — sha256 sur une
    sérialisation canonique (clés triées, séparateurs compacts) de TOUT le
    contenu qui définit le dataset (pas seulement les métadonnées) : deux
    fichiers avec le même `dataset_id` mais un seul octet de bougie
    différent produisent un checksum différent, détectable par
    `load_dataset` (voir son appel à cette même fonction pour comparaison)."""
    payload = {
        "dataset_id": dataset_id,
        "trading_day": trading_day,
        "symbols": list(symbols),
        "timestamps": list(timestamps),
        "bars": {symbol: [b.to_dict() for b in bars_seq] for symbol, bars_seq in bars.items()},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_no_blocking_gaps(
    *, symbol: str, timestamps: list[str], expected_interval_seconds: int, max_gap_multiplier: float = DEFAULT_MAX_GAP_MULTIPLIER
) -> list[str]:
    """Retourne la liste des trous BLOQUANTS trouvés (chaîne descriptive),
    `[]` si aucun. Compare l'écart réel entre bougies CONSÉCUTIVES DÉJÀ
    PRÉSENTES pour `symbol` à `expected_interval_seconds` — ne sait rien des
    autres symboles (voir `build_dataset` pour la détection des bougies
    manquantes PAR RAPPORT AUX AUTRES symboles, un problème différent)."""
    from datetime import datetime

    issues: list[str] = []
    parsed = [datetime.fromisoformat(ts.replace("Z", "+00:00")) for ts in timestamps]
    for i in range(1, len(parsed)):
        delta = (parsed[i] - parsed[i - 1]).total_seconds()
        if delta > expected_interval_seconds * max_gap_multiplier:
            issues.append(
                f"{symbol} : trou de {delta:.0f}s entre {timestamps[i - 1]} et {timestamps[i]} "
                f"(attendu ~{expected_interval_seconds}s, seuil bloquant {expected_interval_seconds * max_gap_multiplier:.0f}s)"
            )
    return issues


def build_dataset(
    *,
    dataset_id: str,
    trading_day: str,
    timezone: str,
    bars_by_symbol: dict[str, dict[str, dict]],
    expected_interval_seconds: int = 60,
    max_gap_multiplier: float = DEFAULT_MAX_GAP_MULTIPLIER,
) -> ReplayDataset:
    """`bars_by_symbol[symbol][iso_timestamp_utc] = {"open","high","low","close","volume"}`.

    Construit l'axe de temps PARTAGÉ comme l'INTERSECTION des horodatages
    présents pour TOUS les symboles (pas l'union) : un horodatage où un seul
    symbole a une bougie mais pas les autres est EXCLU de l'axe partagé
    plutôt que de fabriquer une bougie manquante pour les autres (§principe
    anti-fabrication du projet). Lève `ReplayDatasetError` si l'intersection
    perd plus de 10 % des horodatages d'un symbole (trou structurel probable
    plutôt qu'une poignée de minutes isolées) ou si un trou bloquant est
    détecté sur l'axe résultant (`validate_no_blocking_gaps`)."""
    if not bars_by_symbol:
        raise ReplayDatasetError("aucun symbole fourni")

    per_symbol_timestamps = {symbol: set(raw.keys()) for symbol, raw in bars_by_symbol.items()}
    shared = set.intersection(*per_symbol_timestamps.values())
    if not shared:
        raise ReplayDatasetError("aucun horodatage commun à tous les symboles — dataset inutilisable")

    for symbol, ts_set in per_symbol_timestamps.items():
        dropped = len(ts_set) - len(shared)
        if len(ts_set) > 0 and dropped / len(ts_set) > 0.10:
            raise ReplayDatasetError(
                f"{symbol} : {dropped}/{len(ts_set)} bougies exclues de l'axe partagé (>10%) — "
                "trou structurel probable, dataset rejeté plutôt que silencieusement dégradé"
            )

    timestamps = tuple(sorted(shared))
    gap_issues = validate_no_blocking_gaps(
        symbol="(axe partagé)",
        timestamps=list(timestamps),
        expected_interval_seconds=expected_interval_seconds,
        max_gap_multiplier=max_gap_multiplier,
    )
    if gap_issues:
        raise ReplayDatasetError("trou(s) bloquant(s) détecté(s) : " + "; ".join(gap_issues))

    symbols = tuple(sorted(bars_by_symbol.keys()))
    bars: dict[str, tuple[ReplayBar, ...]] = {
        symbol: tuple(ReplayBar.from_dict(bars_by_symbol[symbol][ts]) for ts in timestamps) for symbol in symbols
    }

    checksum = compute_checksum(dataset_id=dataset_id, trading_day=trading_day, symbols=symbols, timestamps=timestamps, bars=bars)

    return ReplayDataset(
        dataset_id=dataset_id,
        trading_day=trading_day,
        timezone=timezone,
        symbols=symbols,
        timestamps=timestamps,
        bars=bars,
        checksum=checksum,
    )


def save_dataset(dataset: ReplayDataset, path: Path = DEFAULT_REPLAY_DATASET_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataset.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def load_dataset(path: Path = DEFAULT_REPLAY_DATASET_PATH) -> ReplayDataset:
    """Lève `ReplayDatasetError` si le fichier est absent (cas attendu tant
    que `scripts/fetch_replay_dataset.py` n'a pas été exécuté par Zac, voir
    docstring du module — jamais un `FileNotFoundError` brut qui laisserait
    l'appelant deviner la cause), illisible, ou si le checksum stocké ne
    correspond plus au contenu (fichier corrompu/modifié à la main)."""
    if not path.exists():
        raise ReplayDatasetError(
            f"aucun dataset Replay trouvé à {path} — exécuter scripts/fetch_replay_dataset.py "
            "avec de vraies clés Alpaca pour en produire un (voir sa docstring)"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ReplayDatasetError(f"dataset Replay illisible ({path}) : {exc}") from exc

    try:
        symbols = tuple(raw["symbols"])
        timestamps = tuple(raw["timestamps"])
        bars = {symbol: tuple(ReplayBar.from_dict(b) for b in raw["bars"][symbol]) for symbol in symbols}
        stored_checksum = raw["checksum"]
    except (KeyError, TypeError) as exc:
        raise ReplayDatasetError(f"dataset Replay malformé ({path}) : champ manquant {exc}") from exc

    recomputed = compute_checksum(
        dataset_id=raw["dataset_id"], trading_day=raw["trading_day"], symbols=symbols, timestamps=timestamps, bars=bars
    )
    if recomputed != stored_checksum:
        raise ReplayDatasetError(
            f"checksum du dataset Replay ({path}) ne correspond plus au contenu — fichier corrompu ou modifié à la main"
        )

    return ReplayDataset(
        dataset_id=raw["dataset_id"],
        trading_day=raw["trading_day"],
        timezone=raw["timezone"],
        symbols=symbols,
        timestamps=timestamps,
        bars=bars,
        checksum=stored_checksum,
    )


class ReplayMarketDataProvider:
    """Lecture séquentielle et déterministe d'un `ReplayDataset` — Étape A :
    `advance()` avance TOUJOURS d'exactement une bougie sur l'axe de temps
    partagé (x1), appelé explicitement (aucun thread/minuteur ici, voir
    docstring du module). `reset()` = "Restart déterministe" (§checklist) :
    revient exactement à l'état initial, un `reset()` + N `advance()`
    identiques produit TOUJOURS la même séquence de bougies (§checklist
    "Deux replays identiques reçoivent les mêmes données") — garanti par
    construction puisqu'aucun état aléatoire n'existe nulle part ici."""

    def __init__(self, dataset: ReplayDataset) -> None:
        self._dataset = dataset
        self._index = -1  # avant toute bougie servie

    @property
    def dataset(self) -> ReplayDataset:
        return self._dataset

    @property
    def index(self) -> int:
        return self._index

    @property
    def is_finished(self) -> bool:
        return self._index >= len(self._dataset.timestamps) - 1

    def reset(self) -> None:
        self._index = -1

    def seek(self, index: int) -> None:
        """Restaure une position déjà connue (ex. relue depuis
        `shared.replay_state`, voir `backend/app/routers/replay.py`) sans
        rejouer les `advance()` intermédiaires — un provider est reconstruit
        à chaque requête HTTP (sans état de process, voir ce routeur), donc
        `seek` est la façon normale de reprendre une session déjà en cours,
        pas un détail interne. Lève `ValueError` sur un index hors bornes
        plutôt que de le tolérer silencieusement (un index provenant d'un
        dataset différent, ex. régénéré entre-temps, doit être rejeté par
        l'appelant AVANT d'appeler `seek`, pas ici — cette méthode ne connaît
        que la longueur du dataset courant)."""
        if not (-1 <= index < len(self._dataset.timestamps)):
            raise ValueError(f"index hors bornes : {index} (dataset de {len(self._dataset.timestamps)} bougies)")
        self._index = index

    def advance(self) -> dict[str, ReplayBar] | None:
        """Retourne `None` (jamais une exception) si la session est déjà
        terminée — un appelant qui continue d'appeler `advance()` après la
        fin ne doit pas planter, juste ne plus progresser."""
        if self.is_finished:
            return None
        self._index += 1
        return self.current_bars()

    def current_bars(self) -> dict[str, ReplayBar]:
        if self._index < 0:
            return {}
        return {symbol: bars[self._index] for symbol, bars in self._dataset.bars.items()}

    def current_timestamp(self) -> str | None:
        if self._index < 0:
            return None
        return self._dataset.timestamps[self._index]

    def summary(self) -> dict:
        """§checklist "Résumé final de session" — version Étape A (lecture
        seule, pas de P&L simulé, voir Étape B pour un résumé incluant les
        ordres/portefeuille Replay)."""
        return {
            "dataset_id": self._dataset.dataset_id,
            "trading_day": self._dataset.trading_day,
            "symbols": list(self._dataset.symbols),
            "total_bars": len(self._dataset.timestamps),
            "current_index": self._index,
            "current_timestamp": self.current_timestamp(),
            "is_finished": self.is_finished,
        }
