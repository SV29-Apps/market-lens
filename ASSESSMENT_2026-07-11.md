# Market Lens — Fable 5 Ultracode Assessment (2026-07-11)

**Method:** 57 agents. 7 parallel reviewers (read engine, screener, API server, frontend, deploy/security, docs-vs-code sync, design fidelity), each reading the actual source. Every finding was then handed to an independent adversarial verifier instructed to *refute* it by tracing the code path. **49 findings raised → 37 confirmed, 12 refuted.** Zero high-severity findings; 12 medium, 25 low.

**Overall verdict:** the project is in genuinely good shape. No crashes, no security holes, no wrong-direction verdicts were found. The confirmed issues cluster into five themes, all fixable with small, targeted changes.

---

## The 12 medium findings (fix-worthy)

### Theme 1 — Verdict/action inconsistency (the class the app most wants to avoid)

1. **Risk-Off override changes the verdict to "wait" but leaves the buy action intact** — `backend/plain_read.py:179`. In a Risk-Off market, an established leader's card header says *"Strong, but the market is weak… Go slow"* while the action box still says *"Good spot to buy around $X"* and the chart still draws a buy level. Reachable in every bear market. Fix: the override should also swap paragraph/action/buy_level to the wait variants.

2. **Two conflicting "extended" definitions** — `backend/plain_read.py:106`. The verdict uses a flat `>12% above 50-day`; the setup-check dot uses the ATR rule that READ_LOGIC.md declares canonical ("JLaw measures extended in ATR terms, not a flat %"). A low-volatility leader 13% above its 50-day shows a green "Not over-extended" dot directly under a "don't chase — it has run up" verdict. Fix: use the 7×ATR rule for both.

### Theme 2 — Failure results cached for a whole day

3. **A transient TradingView failure is cached as the day's screener result** — `backend/app.py:310`. `momentum_list` returns `[]` on failure (and silently drops any single lane that errors); `_put` caches it unconditionally; `_cached` treats `[]` as a valid hit. One hiccup at the day's first `/api/strong` → empty (or Early-tab-less) screener until midnight, while the UI says "try again shortly". Fix: skip `_put` when the list is empty; log per-lane failures (currently bare `except: continue` — zero observability).

4. **`/api/read` daily-caches `ok:False` payloads** (low but same family) — `backend/app.py:290`. A throttled Yahoo search returning 200-with-empty-quotes makes a valid ticker "unreadable" for the day. Fix: skip `_put` when `out.ok` is falsy.

### Theme 3 — The intraday-cumulative bug class survives in one more place

5. **Every lane's liquidity floor gates on `Value.Traded`** — `backend/market_scan.py:222`. Same field class as the fixed Early-tab bug: it's session-cumulative, so a morning scan (10:00 ET ≈ your evening IST browsing window) excludes mid-caps that haven't yet crossed the full-day floor — and the calendar-day cache then freezes that thinned list. Fix: gate on `average_volume_10d_calc × close` instead. Also (low): `snapshot()`'s "Wk turnover" chip actually shows today's session-to-date value (~5× understated, swings with time of day) — relabel or ×5 a trailing average.

### Theme 4 — UK market: pence vs pounds

6. **UK screener prices are 100× wrong** — `backend/market_scan.py:26`. TradingView quotes LSE in pence; the screener renders `£4,520` for a £45.20 stock (the deep read divides by 100, so opening the same stock shows the right price — a visible self-contradiction). The `dollar_vol=2_000_000` floor in pence ≈ £20k/day — far too low to kill micro-pumps. Fix: divide LSE closes by 100 for display; restate UK floors explicitly in pence.

### Theme 5 — Server robustness & frontend races

7. **`_CACHE` grows without bound on user-controlled keys** — `backend/app.py:82`. No eviction ever; the read key embeds the *raw* `?market=` string before validation, so junk market values mint duplicate entries. Memory-exhaustion vector on the 512MB instance (mitigated by Basic-auth + free-tier restarts). Fix: evict stale-day keys in `_put`; build the key from the validated market.

8. **No per-request deadline** — `backend/app.py:273`. One read = up to ~10 sequential upstream calls, each retried 3× at 25s timeout → minutes per request during a Yahoo brownout. ~40 stuck reads exhaust the threadpool, which also blocks `/api/health` (sync def) → Render restarts the service. Fix: `tries=1` for interactive reads, and/or make health `async def`.

9. **No lock on the daily caches** — `backend/app.py:302`. Cold-cache visitors each independently run the full ~15s 5-lane scan in parallel; the burst from one IP is exactly what invites throttling (which then feeds finding #3). Fix: per-key `threading.Lock` / single-flight.

10. **`openRead` has no stale-response guard** — `frontend/index.html:254`. Tap stock A (cold start, 30–60s), tap back, open B — A's late response silently replaces B's read. Page stays self-consistently labelled A, but it's still a swap under the user. Fix: one-line request-sequence counter. Same pattern (low): `loadTeaser` market-pill race (`:467`).

11. **Strong screen renders the previous market's cached list mid-scan** — `frontend/index.html:572`. Clicking a tab or typing in the filter while India is scanning re-renders the cached US list under the "India" title. Fix: clear `lastStrong` on market switch; guard `renderStrongView` while a scan is in flight.

12. **`fmtMoney` rounds to whole units, collapsing low-priced stocks** — `frontend/index.html:227`. A $3.47 fast-mover: axis $3/$3/$4, "stop $3" for an actual 3.47 stop (~15% off on a trading level), cone caption "$3–$3". UK sub-£10 names all affected. Fix: 2 decimals under 10 units.

Plus one deploy medium: **all deps in `requirements-prod.txt` are unpinned `>=`** — a future redeploy can silently pull pandas 3.x / numpy 2.x / a breaking tradingview-screener major, and the health check (static `{"ok": true}`) stays green while scans break. Fix: pin `==` or add upper bounds.

---

## Low findings worth a batch pass (25 total; highlights)

- **Engine:** `just_popped` is checked before the settle branch, so one +4% bounce day flips a still-sliding leader from "wait to steady" to "buy the dip" (`plain_read.py:147` — the design reviewer independently found the same ordering issue via `near_high`); Risk-Off gate skips the riskier *emerging* starter-buy (`:179`); "up about **-12%** in six months" garbled phrasing for bear-market leaders (`:493`).
- **Design/copy:** "Good spot to buy around $X" / "Ends a day below X → **sell it**" are literal imperatives on a site whose footer says "never a buy or sell signal" — the emerging action's "one way to play it" phrasing shows the house style already knows the fix (`plain_read.py:552,601`).
- **Frontend:** no cold-start feedback on the read path (bare spinner up to 60s; `r.ok` never checked, so a Render 502 wake-up page shows a generic error); dead news-list CSS; `.charthint` uses undefined `var(--muted)`.
- **Server/deploy:** `/api/read` returns raw `str(e)` (internal Yahoo URLs) to clients; stale comment block + dead `memo_on`/`_SCAN_LIMIT`/`_DEEP_MAX` in `app.py:65-70`; stale "volume building" comment on the early lane.
- **Docs (7 findings, all low — sync is otherwise unusually good; every numeric threshold traced matched the code):** "Probable trade period" is live in the app but marked *Parked* in FUTURE_FEATURES.md and absent from READ_LOGIC.md entirely; RS-check invariant overstated (a "not a clear leader" name can still get a green "Beating the market" dot — code only guards weak/avoid); RS doc lists 3 dot states, code has 4; stop-line doc mentions an ATR variant the read never uses; README front door is stale ("No API key", port 8000, "market-wide scan is the planned next step", layout omits market_scan.py).

## Refuted (12) — claims that did NOT survive adversarial verification

Notables: the esc()-bypass XSS claim (values provably numeric), the int(NaN) volume crash (FX/index symbols return zeros, not nulls; and `/api/read` catches everything anyway), "unauthenticated /api/read abuse" (verified live: the Render deploy returns 401 — Basic auth is on), the emerging-path "no reclaim check" and "no outperformance" claims (documented intent, and the path is *more* cautious than the alternative), and the cone-caption caveat claim (caption contains every promised element; earnings-gap flag is documented backlog).

## Dimension verdicts (one line each)

- **Engine:** well-organized and defensive; biggest risk is rule-interaction drift — branch *order* now silently decides overlapping verdicts.
- **Screener:** thoughtfully engineered; residual risks are the surviving intraday-cumulative gate and zero logging on failure paths.
- **Server:** defensively written (sync-def handlers, timeouts everywhere, cone math well-guarded); the hand-rolled daily cache is the weak spot.
- **Frontend:** near-perfect `esc()` discipline, cone correctly hidden from legend/tooltip, chart properly destroyed per stock; missing stale-response guards are the gap.
- **Deploy:** no secrets committed, compare_digest auth, live 401 verified; unpinned deps and no rate limiting behind auth are the gaps.
- **Docs:** unusually good sync for a fast-moving solo project; emerging-gate and period-feature entries are the drift points.
- **Design:** no look-ahead, no leakage — the per-article patches show up as magic constants and an elif-pile, not overfit. The cone caption is exemplary honest copy.

## Design reviewer's strategic notes

1. **The refactor worth doing:** deep_fade and settle are the same predicate (below 20-day + falling RS) graded by drawdown depth, and extended/near_high/just_popped is an orthogonal "location" state. The verdict is really a 2-axis matrix — *leadership tier* (established / emerging / mixed / weak) × *pullback health* (resting / stretched / sliding / deep-faded). Refactoring to that matrix removes the branch-ordering bugs (findings 1, and the two ordering lows) structurally, and makes each future article-patch a cell edit instead of a new elif.
2. **Highest-value next features** (vs FUTURE_FEATURES.md): (a) the Tier-1 JLaw snapshot card (~80% assembly of existing payload); (b) earnings-date-inside-cone flag + a working prod news source (Google News RSS, since Alpha Vantage is dead on Render's IP) — both shrink the engine's one designed blind spot; (c) the industry-average RS line — JLaw's system is sector-rotation-driven and the app currently judges leadership only vs the broad index.

---
*Full agent transcripts: session workflow `wf_c3c3fc80-768`. Raw findings JSON: task output `wob2sp0rs.output`.*
