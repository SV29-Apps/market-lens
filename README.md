# Market Lens

A plain-English stock read for people who aren't traders. Type a stock and it
tells you, in simple words, whether it looks **buy-ready / strong-but-wait /
weak**, why, and **one number** to act on (a buy level, or a sell line).

It runs the tuned "JLaw" momentum logic under the hood, but hides the jargon —
the output is short sentences plus a colour-coded action box.

## What it does

- **Search** any stock (US / India / UK) → a plain read.
- **The read**: a one-line verdict (green / amber / red) → a short why → a
  one-number action box (buy on a dip, or a sell line if it weakens).
- **Strong right now**: a categorised list of leaders (*buyable now* vs
  *strong, but wait*). Starts from a small built-in list; a full market-wide
  scan is the planned next step.

No API key. The read is computed on the server from free public price data
(Yahoo) using deterministic rules — instant and free.

## Run it locally

Needs Python 3.12+.

```bash
pip install -r requirements-prod.txt
uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Then open http://localhost:8000

## Deploy (Render)

This repo is Render-ready (`render.yaml` + `Procfile`):

1. Push to a GitHub repo.
2. Render → **New > Blueprint**, point it at the repo.
3. It builds from `requirements-prod.txt` and starts the app. Done.

Free tier sleeps after ~15 min idle (first visit cold-starts ~30–60s). The
`$7/mo` starter plan keeps it always-on.

## Layout

```
backend/
  app.py            FastAPI — /api/read, /api/strong, serves the UI
  plain_read.py     the rules: engine numbers -> plain words + action box
  jlaw_data_core.py the data engine (Yahoo, relative strength, no API key)
frontend/
  index.html        the 3-screen app (search -> read -> strong list)
```

## Note

Educational only. Not financial advice, and never a buy/sell signal.
