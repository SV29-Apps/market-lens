# Market Lens — future features (parked)

Things we've deliberately paused for later, so they're not forgotten. Add to this
list whenever we defer something.

---

## Chart

- **"Industry avg (=100)" line** — overlay the stock's industry/sector average on the
  chart (rebased to 100), like Sanat's app, so you can see the stock vs its own group.
  *Effort: moderate.* Needs a new data source — either a per-industry ETF, or a basket
  of the industry's peers averaged together — plus one extra fetch per chart.
  *(Paused 2026-07-01.)*

- **"This stock (=100)" line** — the stock's price rebased to 100, plotted on the RS
  (right) axis so it can be compared apples-to-apples against the industry line above.
  *Effort: trivial.* Mostly useful only once the industry line exists. *(Paused 2026-07-01.)*

- **Zoom / pan on the chart — DONE (2026-07-06).** Added `chartjs-plugin-zoom` (CDN, after
  Chart.js). `buildChart` enables **wheel-zoom + drag-to-zoom (box) + pinch on x**; **double-click
  resets** (`el.ondblclick → chartInst.resetZoom()`); a `.charthint` line under the chart tells the
  user. No hammerjs needed (drag/wheel zoom only, no mouse-pan). Verified live: programmatic
  `zoom()` moved the x-range and `resetZoom()` restored it; plugin registered; 0 console errors.

---

## Investor mode (long-term lens) — or a separate app

Market Lens today is the **trader lens** (entry / stop / "don't chase the jump").
An **"Investor mode"** (a toggle, or a separate app) would reuse the leadership +
theme engine but reframe it for **holding for years**, not trading for weeks:

- **What carries over from JLaw:** relative strength / leadership (judged on the
  6–12 month horizon), "capital flows to the structural winners" (themes), buy
  leaders on pullbacks / don't overpay, risk sizing.
- **What changes:** exit on a **broken thesis**, not a technical dip (hold winners
  through 20–40% drawdowns to compound); **wider / no** stops; add **business
  quality + valuation** depth.

### "How high can it go?" — a long-term upside / fair-value estimate
The one thing JLaw's momentum principles **cannot** give (he refuses price
predictions — *"no crystal ball"*). A long-term "maximum level" comes from
**fundamental valuation**, a different toolkit:
- forward earnings × a fair P/E (or PEG), **DCF** intrinsic value, price-to-sales
  for growth names, sum-of-parts, and/or aggregated **analyst price targets**;
- present it as a **range with confidence**, never a single guaranteed number.

*Effort: significant* — needs fundamentals/estimates data (earnings, growth,
margins) and a valuation model. This is really the core of a separate
"investor" app rather than a small add-on. *(Parked 2026-07-01.)*

### "Probable levels" — a volatility probability cone — DONE (2026-07-06)
Shipped. `app._chart_payload` computes it from the plotted closes: stdev of the last 60
daily **log-returns** → `dvol`; horizon **H=30 trading days (~6 wks)**; for each future day
t the bands are `last·exp(±k·dvol·√t)` for k=1,2 (±1σ/±2σ), **no drift** (centred on today's
price). Returns `chart["cone"]` = 30 future business-day dates + `up1/lo1/up2/lo2` arrays +
`weeks`/`b1_lo`/`b1_hi`/`b2_lo`/`b2_hi`/`pct1` for the caption. Frontend `buildChart` appends
the future dates to the labels and adds 4 shaded band datasets (lo2/up2/lo1/up1, filled
`-1`, `cone:true` → hidden from legend & tooltip); `coneHtml` renders an honest caption
("Probable range over ~6 weeks … the stock's own normal wobble, not a forecast of direction …
typical case ~2 in 3, wider ~19 in 20"). **Rigorously verified:** math unit-tested vs an
independent recompute (rel-err ~1e-5; bands widen √t; ±2σ nests ±1σ nests price; widths rank
KVUE<AAPL<LLY<NVDA<TSLA by vol); an independent quant-review agent rated it **"ship as-is"**
(textbook expected-move cone, correct √t, honest non-directional framing); rendered live (fan
draws forward past "now", legend clean, zoom intact, 0 console errors). See `READ_LOGIC.md`.
- **Backlog (from the review):** flag when an **earnings date falls inside the ~6-week horizon**
  — a single earnings gap can blow through the ±2σ band, the one risk a realized-vol cone
  structurally can't see. Also close-to-close vol slightly *under*-states true vol (conservative).

### Probable trade *period* (how long it might take)
The time dimension of the cone. Same volatility maths run backwards: to travel a
given distance (entry → target) at the stock's typical daily move takes roughly
`(move ÷ daily-move)²` trading days — a **tentative window**, not a schedule.
- Also pairs with JLaw's **time stop** ("give it ~N weeks; if it hasn't worked and
  hasn't broken the stop, the opportunity cost says move on").
- Honest framing: paths are random — show a rough "typically ~X weeks to reach the
  target" with wide uncertainty, never a countdown. *(Parked 2026-07-01.)*

---

## List ↔ read 100% consistency — DONE (2026-07-01)

The list's buy/wait tag now comes from the SAME deep read (`_read_one`, Yahoo data) as the
stock page, so they can never disagree. TradingView is used only to FIND the candidate names
(the market-wide screen) + the header stats. Trade-off accepted: the list is capped at
`_STRONG_MAX` (30) deep-read names and the scan takes ~50s on first load (cached daily),
vs the old fast-but-occasionally-inconsistent 150-name TradingView classify. Verified: 85
list items across US/IN/UK, 0 tag mismatches vs their reads.

---

## Pull-back zone with stacked supports — DONE (2026-07-01)

Shipped. `plain_read._supports` clusters the supports **below** the current price
(10 / 20 / 50 / 200-day lines + the recent low) into a **buy-on-dip zone** (the stacked
levels near the top) and lists every level with its value; shown in the "Where it could go"
box for buy/wait names (skipped for weak/avoid). See `READ_LOGIC.md`. Verified live across
US/IN/UK — every listed level sits below the price, zone spans the clustered supports.

---

## Recent news + catalyst flag — DONE (2026-07-01)

Shipped, key-free. `jlaw_data_core.google_news` pulls 5 stock-specific headlines from
**Google News RSS** (queried by company name); `app._add_news` attaches them on the read
path only (list stays fast) plus a **catalyst flag** when there's a ≥3% recent gap
("usually news-driven — check before assuming a calm pullback"). Deterministic-honest: it
prompts the reader to check, doesn't claim to match a headline to the move. See
`READ_LOGIC.md`. Full LLM-style catalyst *judgment* remains the parked AI-essay read below.

---

## The written "AI" read

- **Full plain-English essay read** (beyond the templated read) — an optional longer,
  free-flowing write-up. On a hosted server this needs either a paid API key or the
  local Max-plan MCP trick; the free templated read is the default. *(Parked.)* This is
  **Tier 2** of the "JLaw snapshot" idea below — the narrative prose (theme-vs-catalyst
  nuance, sizing/psychology, bull/digest/invalidation scenarios) that only an LLM produces.

## JLaw "snapshot card" — a structured verdict summary (Tier 1, deterministic)

*(Raised by user 2026-07-07, after seeing a full 9-section JLaw verdict for ARKG.)* A compact
card on the read page that assembles the momentum verdict into one scannable block:
**Stance · Market gate (Risk-On/Off) · RS leader (+ 1/3/6m excess vs index) · Extension
(% above 20/50-DMA) · Entry band · Stop / Target / R:R · one-line takeaway.**

- **~80% of the data already exists** in the `/api/read` payload (`verdict`, `paragraph`,
  `supports.zone`, `lines`, `action.note` = safety line, `stats` = perf/sector) or elsewhere
  in the engine (the screener's `_bench_perf` true-excess; `price_vs_ma_pct` extension).
  It's mostly **surfacing + assembling**, staying deterministic / instant / free / no API key.
- **Needs adding** (not computed today, all standard TA): **ATR-based stop distance**, a
  **measured-move target**, the **explicit R:R number**, and **wiring the market-gate**
  (broad-market Risk-On/Off) into the read. *Effort: moderate.*
- This is the cheap sibling of the "AI essay" (Tier 2) above — ~80% of the value with none
  of the LLM cost/latency/key. Recommended as the next feature if we resume building.

---

## Deploy / hosting

- **Go live on Render — DONE (2026-07-07).** Live at **https://global-market-lens.onrender.com**
  (repo `SV29-Apps/market-lens`, auto-deploys on push to `main`). Deployed as a plain Web Service
  (NOT blueprint-managed — the `render.yaml`/`Procfile` are still in the repo but the live service
  is configured in the dashboard). Free tier sleeps when idle (~30–60s cold start); `$7/mo` keeps
  it always-on. Note: Render **can't rename an existing service's `onrender.com` subdomain** — a
  specific URL requires creating a fresh service with that name. News (Alpha Vantage) is OFF on the
  host because AV throttles Render's shared datacenter IP, even with a valid key — works locally.

- **Site login (HTTP Basic Auth) — DONE (2026-07-07).** `backend/app.py` `_basic_auth` middleware
  gates the whole site when BOTH `APP_USERNAME` and `APP_PASSWORD` env vars are set (`/api/health`
  exempt so Render monitoring works); fully OPEN when unset (local dev unaffected). Change the
  credentials any time via those two env vars → redeploy. Verified live (no/wrong creds → 401).

---

## Data / coverage

- **"Strong right now" → MOMENTUM SCREENER + 4 tabs. DONE (2026-07-02).** *(Supersedes
  the earlier "middle build".)* The list is now a **fast Sanat-style momentum screener**
  (`market_scan.momentum_list`, ~7–16s, NO per-name deep read) — the JLaw buy/wait judgment
  happens when a stock is OPENED, not on the list. **4 tabs:** Fast movers · Quiet leaders
  (true RS vs S&P 3&6m) · **Early** (JLaw "just turning up", blind-agent-verified, labelled
  "candidates — check the chart") · By sector (**Sector › Industry**). Search box; friendly
  sectors (AMAT→Chips). US≈265 / IN≈142 / UK≈68. Full detail in `SESSION_HANDOVER_2026-07-01.md`.
- **READ: "emerging / early" verdict. DONE (2026-07-02).** Fresh movers (APP/HOOD) now read
  *"Gaining strength — don't chase"* / *"Early — just turning up"* instead of "not a leader".
  See READ_LOGIC.md.

- **JLaw CHART-PATTERN reads — PARTIALLY DONE (2026-07-06).** Shipped the unambiguous subset as a
  non-verdict-changing **"Chart signals"** element (`plain_read._patterns` → `read["signals"]`;
  frontend `signalsHtml`, a "What the chart is showing" box under the chart, ≤2 signals, green/amber
  dots). Detects from the daily snapshot: **buyable-gap-up** (recent up-gap ≥3% holding above the
  50-day), **gap-down**, **relative strength in a soft market** (Neutral/Risk-Off + strong RS + above
  50-day), and the **last bar's shape** — long lower tail (shakeout/reversal), long upper tail
  (rejection), big green body (conviction), big red body (heavy selling). Informational only — it does
  NOT change the buy/wait/weak verdict (verified: 0 tag changes across 16 names). STILL PARKED (need
  more than the snapshot exposes, or an LLM): **engulfing** (needs the prior bar — engine exposes only
  `last_candle`), **first-touch** (needs touch history), **base/flag** structure, **volume-expansion
  signature**, **MACD** crossover, full **M.E.T.A. confluence**. Documented in `READ_LOGIC.md`.
- **PARKED / next depth — the rest of the JLaw CHART-PATTERN reads.** Market Lens's
  read currently uses only JLaw's *measurable* signals (RS, MA structure, ATR-extension,
  direction-aware volume, gaps-flag, swing, reward:risk, emerging). It does NOT read the
  chart *patterns* JLaw uses (his STEP-3 price-action edges): **Reversal (shakeout→180°),
  Engulfing, Long-body candles, gap quality/BGU criteria + follow-through, First-touch of a
  level, higher-lows-vs-a-weak-market divergence, base/flag structure, volume-expansion
  (high→low→high) signature, MACD crossover, multi-edge (M.E.T.A.) confluence.** The corpus
  agent classified these as CHART-JUDGMENT (not numbers) — hard to compute from a daily
  snapshot; today they live in the full JLaw *skill* (LLM), not the app's rules read. The
  engine already exposes `last_candle` (color/body%/wicks) + `recent_gaps`, so a partial,
  honest version is feasible (flag a clean reversal/engulfing/BGU/first-touch when the candle
  math is unambiguous; leave the rest to the chart + a future LLM/Max read). *(Raised by user
  2026-07-03: "have you incorporated chart reads as per JLaw method?" — answer: measurable
  signals yes, chart-pattern reads no. This is the item to build for that.)*

- **Weak / short-watch list** — a separate view of the weakest names (for advanced users).
  Deliberately left out of the beginner app to avoid nudging toward shorting. *(Parked.)*
