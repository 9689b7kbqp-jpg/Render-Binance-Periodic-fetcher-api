# Binance Decision API pour Render

API FastAPI pour calculer une décision BTC/USDC selon la stratégie LABR / Delta_LABR / VWAP / ATR.

## Objectif

Éviter que `/decision` prenne trop de temps en recalculant tout à la demande.

Le service lance une boucle background au démarrage, calcule une décision toutes les `REFRESH_SECONDS`, puis expose :

```text
GET /decision-latest
```

Cette route renvoie immédiatement la dernière décision en cache.

## Endpoints

```text
GET /health
GET /help
GET /snapshot?symbol=BTCUSDC&hours=2&kline_limit=100
GET /signal-inputs?symbol=BTCUSDC&signal_hours=2&kline_limit=100
GET /decision?symbol=BTCUSDC&capital=1420&signal_hours=2&kline_limit=100
GET /decision-latest
```

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---:|---|
| `SYMBOL` | `BTCUSDC` | Paire Binance Spot |
| `CAPITAL` | `1420` | Capital de référence USDC |
| `SIGNAL_HOURS` | `2` | Fenêtre minimale pour calculer heure courante + heure précédente |
| `KLINE_LIMIT` | `100` | Nombre de bougies 1h pour ATR |
| `REFRESH_SECONDS` | `15` | Fréquence de recalcul background |
| `STALE_SECONDS` | `30` | Âge maximal accepté du cache |
| `BINANCE_BASE_URL` | `https://api.binance.com` | Base URL Binance publique |

## Lancer localement

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Tester :

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/decision-latest
```

## Déployer sur Render

### Méthode Dashboard

1. Crée un nouveau repo GitHub.
2. Pousse ce dossier dans le repo.
3. Render > New > Web Service.
4. Connecte le repo.
5. Runtime : `Python 3`.
6. Build Command :

```bash
pip install -r requirements.txt
```

7. Start Command :

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

8. Ajoute les variables d'environnement si tu veux modifier les valeurs par défaut.

### Méthode Blueprint

Le fichier `render.yaml` est inclus. Tu peux créer un Blueprint Render depuis ce repo.

## Important trading

`/decision-latest` renvoie :

```json
{
  "decision": "BUY | SELL | NO_TRADE",
  "age_seconds": 6.2,
  "is_stale": false
}
```

Si `is_stale=true`, la décision doit être considérée comme non exploitable.

## Limites

- Le cache mémoire est perdu à chaque redémarrage Render.
- Si le Web Service dort, la boucle background ne tourne plus.
- Pour une disponibilité continue, utiliser une instance Render sans sleep.
- `/snapshot` est volontairement compact : il n'expose pas tous les `aggTrades` pour éviter les réponses massives et les timeouts.
