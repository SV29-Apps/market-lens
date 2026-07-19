# Market Lens — future features (parked)

Things we've deliberately paused for later, so they're not forgotten. Add to this
list whenever we defer something.

---

## ✅ LICI PAIR: R:R RISK FLOOR + NO-CACHE-ON-CHARTLESS — 2026-07-18 (user-caught)

User's LICI page had (a) NO chart and (b) "Exit ₹432" ₹1 under the ₹433 price with
"Reward for the risk: 16.7 to 1 — good". Two real defects, both fixed (spec in
READ_LOGIC.md top): the R:R grade now floors risk at ~1×ATR everywhere (the audit-#5
class leaking through the mixed/watch-line path — P8 only covered buy setups; new
**P12** + a mixed-hugging-swing-low scenario, 24 principles scenarios total), and a
read whose best-effort chart fetch failed is no longer cached for the 15-min bucket
(same never-cache-a-failure principle as audit M11/#8). Verified: P12 scenario 33:1→5.0,
principles 24/24, frozen as-of 0 diffs (verdicts untouched — R:R never feeds the tag),
LICI live: 130-point chart + "1.2 to 1 — modest", console clean.

---

## ✅ SUGGESTION-PANEL RACE FIX — 2026-07-18 (user-caught bug; local only)

Coming back from a read could show the type-ahead dropdown covering the market pills:
`hideSugg()` ran on Read-click, but the in-flight `/api/suggest` fetch (250ms debounce)
resolved AFTER it and re-rendered the panel behind the read screen. Fixed both ends:
`show("search")` now hides the panel, and the suggest callback bails when
`current !== "search"`. Verified by scripted reproduction of the exact race (type →
Read at 60ms → wait → back): panel hidden+empty, pills visible, console clean.

---

## ✅ GROUP HEALTH (step 1) + VERIFIED DOTS BUILT — 2026-07-18 ("build both"; local only)

Both fidelity items approved via REAL-DATA SAMPLES first (`dots_sample.py` +
`breadth_sample.py` in the 2026-07-18 session scratchpad). Spec now in READ_LOGIC.md
top section. Key verification:
- **Engine-neutrality PROVEN on frozen data:** as-of-2026-07-16 fidelity set re-run =
  **0 diffs** (the 22 live-regression diffs were Friday-session drift — e.g. CHENNPETRO's
  −4.06% shock day flapping on the −4 gate, and a regress-HARNESS artifact: it calls
  J.screen directly so bare "RELIANCE" resolves nondeterministically; the app's
  suffix-first path is unaffected. ⚠️ Lesson: run regressions AS-OF, or pin suffixed
  symbols in the harness).
- **Dots live:** fresh scan 48s, 213 rows, 51 calm / 162 hot; all 9 sample cases landed
  exactly as predicted (XENE/S/KYMR/PSNL/BILL/CHYM/RH/HRL → green; BAND → amber).
- **Group lines live:** NTAP red 9/11 (+8 hard-week), AMD red 56/62, DDOG healthy,
  UNH mixed 4/8 (the wider breadth universe covers groups the sample missed).
- Principles 23/23 · 56-name sweep 0 · DOM: group line renders last in Checks (worst
  last), tabs Early·5 / Quiet·125 / Fast·45 with verified dots, Quiet legend correctly
  amber-only (no verified green today) · console clean. **No "JLaw" in any new UI text
  (grep'd); also scrubbed a pre-existing "JLaw" from a shipped frontend comment.**
- **STEP 2 (breaking group demotes a fresh green) deliberately NOT built** — grade the
  step-1 line against past articles first.

---

## ✅ "GIVE THE APP MEMORY" BUILT — 2026-07-18 (user's explicit "build"; local only)

The biggest remaining JLaw gap (no time axis) closed with a SMALL memory, not a rewrite:
`jlaw_data_core._trend_memory` adds `days_below_50` + `worst_drop_3d` to
`features.daily.trend_memory` (computed from bars already fetched; light scan path too).
Rules in `plain_read` (full spec now at the top of READ_LOGIC.md):
- **Shock gate:** a would-be green (resting) with a >4% down day in the last 3 sessions →
  sliding wait, subline "A leader, but it just had a sharp drop…". Checked AFTER
  stretched so a pop keeps "don't chase" (first cut overrode CHENNPETRO's +7% pop-day
  chase warning — caught by the regression, reordered).
- **Reclaim window:** 1–3 days below the 50-day → softer "Just slipped below its 50-day —
  give it a few days" (wait); >6 days unreclaimed → firmly weak/avoid (`weak_now`).
- **Principles P10 + P11 added** (`backend/principles_test.py`, now 23 scenarios).

**VERIFIED:** principles 23/23 PASS · 21-name regression: 0 diffs from this feature (the
3 observed = live intraday drift, each verified against real features — NOW's
emerging→avoid is the OLD 15-Jul structural_weak rule firing after it slipped below its
50-day intraday, days_below_50=1, not the new rule) · as-of-2026-07-16 fidelity re-run:
**NTAP green→wait is the ONLY change** — DDOG/XBI stay green, exactly what both judges
prescribed; the 17-Jul article's single MISS is closed (now 15 match / 8 partial / 0 miss)
· 56-name live sweep 0 violations · NTAP DOM-verified (wait card, coherent ladder
exit ≤ zone ≤ price < target) · console clean. LOCAL ONLY — not deployed.

**+ LADDER PRICE-RUNG REWORD (2026-07-18, user-approved option B):** "Current price ·
$X — (see the box above)" → says WHERE the price sits vs the buy zone ("at the top of /
just above / well above the buy zone — a good spot to buy / wait for now"; thresholds
2% / 6% of price). NUMERIC `zone.high` only (parsing the formatted string would re-hit
the GBp 100× trap); no zone or action `none`/`exit` → unchanged behaviour. DOM-verified:
NTAP wait "at the top of the buy zone — wait for now", UNH buy "…a good spot to buy",
MSFT exit mini-ladder untouched, RELIANCE `none` plain price, console clean.
**PARKED (user, 2026-07-18 — "can make peace with this"):** (a) green rung a few %
above support says "good spot to buy" without naming the better price (DDOG $259 vs
$250 — proposed: "okay to buy here; a dip toward $250 is the better price"); (b)
single-level "Buy zone · $250" should read "Buy level". Samples already approved-shaped
in chat if ever wanted.

---

## ✅ 17-JUL ARTICLE FIDELITY TEST + FIXES — 2026-07-18 (local only, not deployed)

Article: "Cracks Are Widening in AI Hardware" (17 Jul, Neutral-to-Risk-Off, AI-hardware
deleveraging). Proven flow: as-of reads at 2026-07-16 (news OFF) over 17 names + 3 indices
→ 2 blind judges grading T/F/D. **Result: STRONG fidelity — 14 MATCH / 8 PARTIAL / 1 MISS
(23 gradeable claims).** Regime Neutral ruled CORRECT by both judges against JLaw's own
label definitions (his label "Neutral to Risk-Off"; S&P above rising 50-day, +7.9% over
200-day — and the engine's ^IXIC + ^KS11 blocks independently caught his two stress tells,
both below their 50-days). Engine independently reproduced his avoid-AI-hardware stance
(NBIS weak · SMCI avoid · SOXX/XLK weak · AEHR weak · DELL/AMD wait), his don't-chase
discipline (DAVE/AAPL/IBB waits), and his two next-leader candidates (DDOG, XBI green) +
META as an unconfirmed early turn ("emerging" ≈ his "research thesis, not a conclusion").

**FIXED (agreed-T only, all verified):**
- **Resolver bug:** exact ticker AEHR resolved to AEHG (2X leveraged lookalike ETF). Root
  causes BOTH fixed in `jlaw_data_core.py`: "NCM" (Nasdaq Capital Market) was missing from
  `COUNTRY_EXCH["US"]` (the hint filter DROPPED the real company), and the exact-typed
  symbol now re-ranks to the top of candidates (the old `exact` flag only suppressed the
  ambiguity prompt — it never re-ranked). Live-verified: AEHR → Aehr Test Systems, weak.
- **Template prose contradicting the engine's own numbers (2 instances):**
  `_para_settle` said "below its short-term line / slipping behind the market" even when
  entered off a single >4% down day with the stock ABOVE its 20-day and ahead on every RS
  horizon (SEZL). Clauses now gated on the real features (`_below_ma20`, `ex_1m`); the
  no-clause case says "it's just had a sharp drop". `_para_weak`/`_cell_weak` said "lately
  it has been falling more than the market" on a months-broken name that has steadied
  short-term (MSFT: above 20-day, positive 1-mo excess) — new `falling_now` branch keeps
  the VERDICT identical, only the tense is honest. Both live-verified in the DOM.
- (Sweep list housekeeping: TATAMOTORS is a DEAD Yahoo ticker post-demerger — use TMCV/TMPV.
  The app's "couldn't read" answer is correct there, not a bug.)

**THE ONE MISS — NTAP green "Looks buyable" (the article's named high-energy decliner):**
NTAP fell −7.1% on Jul 15 and only −1.5% on the 16th; the sharp-down-day gate reads the
LAST bar only, so the shock was invisible → "leader resting". Judges SPLIT on class (one
T, one D: single-bar snapshotting is the declared scope edge) but AGREE on the minimal
fix: extend the existing gate to the last ~3 sessions (any close ≤ −4% → demote green to
the settle/wait cell). Both confirmed it flips NTAP and leaves DDOG/XBI/AAPL/DAVE intact.
**NOT built — held for the user's approval** (it is memory-adjacent, and the user fenced
"give the app memory" work behind a sample-first gate, 2026-07-18). Sample offered in chat.
Also parked from the judges (single-judge, no consensus, do NOT build unasked): emerging
`action_type` "buy"→"watch" (META case); a fixed one-line risk sentence on Neutral greens;
a from-52wk-high gate on fresh greens.

**VERIFIED:** principles test PASS (20 scenarios) · 21-name regression = exactly 1 intended
diff (the MSFT paragraph; 0 tag/action/R:R changes) · 56-name live sweep 0 violations
(recreated `audit_sweep.py`) · fidelity re-run on the fixed engine: AEHR/SEZL/MSFT corrected,
all other reads byte-identical · AEHR + MSFT DOM-verified · console clean.

---

## ✅ AUDIT FIXES SHIPPED — 2026-07-17 (local only, not deployed)

User ordered fixes for #1,2,3,4,7,8,9 + architecture. ALL DONE + VERIFIED. A new
**PRINCIPLES TEST** (`backend/principles_test.py`) now runs JLaw's rules as hard
assertions (P1 never green at the 52-wk high · P2 never green below the 50-day · P3 buy
always above the exit · P4 weak never shows a buy zone · P5 exit below price · P6 R:R
positive+label-correct · P7 no NaN in strings) — it caught all bugs loudly BEFORE the fix
(6 failures) and PASSes after (18 scenarios). Run it after ANY engine change.

- **#1 (52-wk-high falsy-zero) FIXED** — `near_high` now `pct_from_high is not None and
  > -5`. Proven: at-high → "don't chase" (was 🟢 buy).
- **#2 (green-by-default) FIXED** — new `below_trend` phase + `_cell_reclaim`: below the
  50-day → "Below its 50-day line — wait for it to reclaim" for leader AND emerging tiers.
  `resting` (the green buy phase) is now only reachable ABOVE the 50-day. Live proof: IMFA
  (0.26% below its 50-day, RS falling) flipped buy→wait-reclaim — the only 21-name
  regression diff, verified correct.
- **#3 (buy below exit) FIXED — ARCHITECTURAL** — levels are now reconciled at ONE source:
  each cell returns its paired `stop` (dip-buy cells use `_dip_stop`, which drops the exit
  ~1.5×ATR below the dip when the swing low sits above it), and `eff_stop`/lines/ladder/R:R
  all read that one value. Proven: buy 75 / exit 72 (was buy 75 / exit 82). Normal names
  unchanged (swing low already below the dip → `_dip_stop` returns it as-is → 0 regression).
- **#4 (whole-unit rounding) FIXED — ARCHITECTURAL ROOT** — `_money` got the same `<10 →
  2dp` rule `fmtMoney` already had. Proven live: PLUG $2.21, BBAI $2.86, RIOT $9.95 (were
  $2/$3/$10); 387p LSE → "£3.87 / exit £3.61" (was £4/£4).
- **#7 (dead liquidity floor) FIXED** — added `average_volume_10d_calc` to the scan `cols`.
  Live: the 4 OTC grey-market names (BDRBF/TOELF/PWCDF/ENLT) gone; universe 327→208.
- **#8 (verify fails open) FIXED** — `_verify_buyzone` now `return False` on error (drop
  the row) instead of keeping an unverified green row.
- **#9 (impossible Quiet-leaders green dot) FIXED** — tab-aware legend; Quiet leaders shows
  "all near their highs — buy the next dip, not here" (no phantom green line).
- **Folded-in frontend fixes (were "not yet verified"):** chart Target no longer falls back
  to `swing_high` (drew a phantom target the engine denied); buy-zone band now uses the
  NUMERIC `zone.low/high` (was parsing formatted strings → 100× off on GBp).

**VERIFIED:** principles test PASS · 56-name live invariant sweep 0 violations · 21-name
regression 1 intended diff (IMFA) · structural-weak units 7/7 · sub-$10 decimals live · OTC
names gone live · legend live · DOM + console clean on reads and the screener.

**#5 + #6 — DONE (2026-07-17, after the #1-9 batch):**
- **`_floored_stop(entry, structural, atr14, min_atrs)`** — every exit now sits at least
  ~1×ATR below the entry for buy setups (min_atrs=1.0), or just below price for hold-lines
  (min_atrs=0.0). `tight_stop` simplified to a straight 1.5×ATR (the old `max(swing_low,
  price-1.5ATR)` picked the TIGHTER of the two → the coin-flip stop). Applied in every cell
  + risk-off; `eff_stop` reads the one cell stop. New **principles P8**: a buy setup's risk
  ≥ ~1×ATR. Proven: the 16.7:1-off-a-1.5%-stop repro → 8.3 off a real 3% (1.5×ATR) stop;
  regression MU 13.5→2.5, ALAB 11.8→2.0, SNDK 2.8→1.8 (all inflated→sane, 0 tag flips).
- **#6:** the near-zero-risk exit is fully handled by `_floored_stop` — a fresh-low bar can
  never produce a coin-flip stop. NOTE: I first tried excluding today's bar from `_swing`
  and it REGRESSED FIG (dropped swing_high below the 2%-target threshold → target cascaded
  to the far 1-year high → R:R 41.6). Caught by the regression BEFORE shipping; reverted —
  `_swing` keeps today's bar (swing_high feeds the target and today's high is valid), and
  the floored stop does the #6 job cleanly. **Lesson: swing_high (target) and swing_low
  (stop) have opposite needs; don't fix them with one change.**
- **#5 horizon honesty:** when the target is the far 1-year high, the R:R note now appends
  "(measured to its 1-year high, which may be a way off)".

## ✅ DATA-LAYER BATCH — DONE + VERIFIED (2026-07-17)

Each verified against the code before fixing; regression 0 tag/rr diffs (as-of reads don't
hit the intraday paths, established names have real 200-day data), 56-name live sweep 0
violations, principles test now 20 scenarios incl. young-stock M4 coverage (P9), DOM clean.
- **H1 Freshness** — `_freshness(meta)` from Yahoo's `regularMarketTime` +
  `currentTradingPeriod`; read carries `freshness` + an honest **`as_of_str`** ("live —
  updates through the trading day" / "at the {date} close" / "as of {date} (historical)")
  shown on the price line. Read cache now bucketed on ~15 min (was whole-day) so an
  intraday price never freezes and a pre-open read refreshes at the open. LIST scan stays
  daily-cached.
- **H3 Volume** — `_volume_block` time-adjusts today's partial volume by the elapsed
  session fraction (generalises the Kite trick to US/UK via Yahoo meta); <5% into the
  session → ratio None → check reads "Volume — no clear read yet today" instead of a false
  "calm". Verified live: AAPL "calm for this time of day" at 65% session. Also M3: heavy
  volume on a FLAT close now reads "Heavy volume, but the price went nowhere" (was "Heavy
  selling").
- **M4 `above200` tri-state** — None (young name, no 200-day) no longer treated as "below
  it": can't wrongly trip `structural_weak` (now `above200 is False`) and `_cell_weak`
  gives amber "weak" not red "avoid" for unknown. New principles P9 guards it.
- **M7 `rs_line_slope`** — MEASURED, NOT flipped: a raw 10-bar slope disagreed on 13/29
  names and would flip 7 verdict tags — and the flips were WRONG (MSFT/CRM/TEAM broken
  laggards → "avoid"→"wait" on a transient RS uptick, undoing the structural-weak fix). The
  mean-based measure is the more robust leadership signal; only the NAME was misleading —
  documented + added honest `rs_vs_mean` alias, behaviour unchanged.
- **M8 `_add_period`** — log move to match the log-vol (was ~30% overstated), `ddof=1`,
  reworded to not promise reaching the target ("a move this size is roughly a normal
  ~N-week swing for it … not a prediction").
- **M11 `_regime_cached`** — no longer day-caches a failure (`if reg: _put`).
- **M10 news** — non-US symbols skip Alpha Vantage entirely (was truncating `.NS`→base and
  risking a US-ticker collision).

**STILL OPEN (lower severity / out of scope):**
- **M1 (out of #1-9 scope):** a "Not a clear leader" (mixed) name still shows a buy zone
  (tag is "wait", and supports gate on tag). Numbers are coherent; the framing isn't.
- **H4 (out of scope):** zone band vs dip-buy level can name two different entries on the
  contrived stretched-below-20-day case; the critical buy>exit is fixed.

---

## ⚠️ (ORIGINAL AUDIT REPORT — for reference; fixes above) 8 CONFIRMED DEFECTS

User ordered a whole-app audit ("your skin is in the game"). 4 code auditors + a 56-name
live invariant sweep (`scratchpad/audit_sweep.py` — **0 violations**, so these are edge
cases / UK / low-price / list-membership paths a typical-read sweep can't reach).
**Every item below was personally reproduced** (`scratchpad/verify_audit.py`,
`verify_nearhigh.py`, `dot_meaning.py`). NOTHING FIXED YET — user to pick the order.

**HIGH — fails GREEN (the two that matter most):**
1. **`near_high = (pct_from_high or -99) > -5`** (`plain_read.py:112`) — at the exact
   52-wk high `pct_from_high == 0.0` is FALSY → swallowed → phase falls to `resting` →
   🟢 "Looks buyable". PROVEN: at the high → buy; 0.5% below → "don't chase"; 3% below →
   "don't chase"; 8% below → buy. *More* extended = *greener*. Same falsy-zero class as
   the THERMAX `dip_q or 9` bug. Fix: `pct_from_high is not None and pct_from_high > -5`.
2. **`resting` is a FALL-THROUGH** (`plain_read.py:186-193`) — nothing requires a "buy"
   name to be above its 50- or 20-day. PROVEN: leader 10% below its 50-day, 20% off high,
   RS rising → 🟢 "Looks buyable" + R:R 11 "good". Directly contradicts JLaw's core
   50MA/63EMA rule. Fix: make `resting` affirmative (require `above50`).

**HIGH — wrong numbers on the card:**
3. **`_dip_below` ma50 branch can return a buy level BELOW `swing_low`**
   (`plain_read.py:304-311`). PROVEN: "Dips to **$75** → good spot to buy" over "your exit
   line is **$82**". R:R silently `None` (guard `entry > stop` fails closed, says nothing).
   The 2026-07-15 coherence guard fixed `supports` only — not `buy_level`/`lines`/`action`.
4. **`_money` rounds to whole units** (`plain_read.py:24-32`) — the `<10 → 2dp` fix landed
   in `fmtMoney` (frontend) and was never ported. PROVEN: 387p LSE stock → "buy around
   **£4** / exit line **£4**" while `lines` are buy=387 stop=361 (7% apart); zone collapses
   to `single=true`. Hits ALL of UK (default UK list has BP/TSCO/BARC/GLEN in the 300-400p
   band) + any US/IN name <10 units.
5. **R:R has no risk floor + mixes horizons** (`plain_read.py:663-684`) — PROVEN 16.7:1
   "good" off a stop 1.5% away (inside 1 ATR). R:R drives SIZE per JLaw → invites max size
   behind a noise-width stop. Also measures reward to a 52-wk high (months) vs risk to a
   20-day low (days).
6. **`_swing` includes TODAY's bar** (`jlaw_data_core.py:287-289` — `df.tail(win)` not a
   pivot). If today IS the 20-day low, the exit sits at today's low → near-zero risk → the
   inflated R:R in #5, on the "buy" cell.

**HIGH — lists:**
7. **The liquidity floor is DEAD CODE** — `average_volume_10d_calc` read at
   `market_scan.py:313` but NOT in `cols` (`:291-293`) → always `None` → gate never fires.
   Only the 5%-of-floor coarse `Value.Traded` filter survives. Live: OTC grey-market names
   (~$5-6M/day) in today's Buy zone with green dots. `_verify_buyzone` can't catch it — it
   verifies the read, not tradability. Fix: add one string to `cols`.
8. **`_verify_buyzone` FAILS OPEN** (`app.py:567-568` `except: return True`) — keeps the
   row AND leaves the scanner's heuristic dot, which for a buyzone row is always green by
   construction; then day-cached. One Yahoo throttle during the day's single scan = green
   unverified "calm entry" rows until midnight. Fix: `return False`.

**Reported by auditors, NOT yet verified by me:** chart Target falls back to `swing_high`
when the engine says there is none (and mislabels it "1-year high"); buy-zone band parsed
from formatted strings → 100× off on GBp (backend already emits numeric `zone.low/high` —
unused); day-cache freezes a pre-open/partial bar as "today" unlabelled; US volume ratio
not session-adjusted → "calm pullback" all morning (only IN/Kite has `session_fraction`);
`above200` unknown-treated-as-False (<200 bars → `leader` tier unreachable, amber→red);
`rs_line_slope` is position-vs-50-bar-mean, NOT a slope (load-bearing in 4 rules incl.
`structural_weak` AND the weak-vs-emerging boundary the user asked about);
Early lane's "RS rising" claim uses a 21-day excess, not the read's slope (AGCO live);
`_regime_cached` caches its own failure; `_add_period` mixes log/simple returns.

**DOT MEANING — measured live 2026-07-17 (`dot_meaning.py`):** Buy zone = verified, trust
it. **Quiet leaders = green is STRUCTURALLY IMPOSSIBLE** (lane needs ≤3% from the 52w high;
the dot goes hot at 5%) — 0/40 IN, 0/170 US green, yet the green/amber legend still renders.
Fast movers = 20/20 green rows read buy/emerging TODAY (8 IN + 12 US, 0 contradictions) but
nothing enforces it — the dot only mirrors the read's `stretched` axis, never `sliding`/
`deep_fade`/`weak`. Early = 5/6 green agree, AGCO contradicts.

**ARCHITECTURAL (not just coding — corrected after the user challenged the framing):**
green is the DEFAULT (fall-through) rather than earned; two formatters guarantee drift;
levels computed scattered then patched downstream; **no time axis at all** (so JLaw's
4-6-day reclaim window is structurally impossible, not merely "not implemented"); R:R
compares mismatched horizons. Sound: the tier×phase matrix (no cell self-contradicts) and
the two-layer list+verify design.

**AGREED FIX APPROACH (root-cause, so patches can't breed new bugs):** one place computes
ALL levels together and reconciles there (kills #3/#5/#6) · ONE formatter, numbers over the
wire (kills #4 permanently) · green must be EARNED (kills #1/#2 at the root) · "unknown"
never means 0/False · **a PRINCIPLES TEST** — JLaw's rules as executable assertions (never
green above a 52w high · never green below the 50-day · buy always above the exit · risk
never < ~1× daily swing · weak never shows a buy zone) run alongside the 56-name coherence
sweep + the 21-name regression, so no fix can silently undo another.

## PARKED (user decisions 2026-07-17)

- **Target-vs-probable-range honesty line** — pairing R:R with the cone ("Target $205 —
  inside its normal 6-week range" vs "beyond even its wider range"). Proposed after the
  audit showed R:R has no time/probability context. **User: "park this, still not confident
  of this."** Do not build without a fresh ask.
- **MOTILALOFS-class sector override** — TradingView misclassifies it as
  "Technology Services / Internet Software" (it's a financial-services company). Name-keyword
  override proposed; **user: "ignore the Motilal case for now."**

---

## Chart v2 + ladder rewording + white scheme — DONE (2026-07-15, approved samples)

All user-approved via mockups, then "Build it" (Motilal sector-override explicitly SKIPPED):
- **Chart levels are now ANNOTATIONS, not datasets** (`chartjs-plugin-annotation` CDN,
  auto-registers like the zoom plugin): shaded labelled **Buy-zone band** (numeric
  bounds parsed from `supports.zone` strings — commas/₹ stripped), red dashed
  **"Exit {price}" pill**, green **"Target {price} — recent high/1-year high" pill**
  (source derived from `detail.target.note`). Being annotations they're automatically
  OUT of the tooltip and legend (user ask #2). Falls back to a plain buy line when a
  read has no zone; exit-only for weak names.
- **Tooltip**: full date title via `fullDate()` ("15 Jan 2026" — user caught the
  truncation in the sample); body shows only Price / 20 / 50 / 200-day / RS.
- **Line styling** (Sanat cues): price bold dark; 20-day blue [5,4]; 50-day green
  [7,4]; 200-day amber dotted [2,3]; RS purple, right axis titled "RS vs market
  (=100 at start)". Cone + zoom kept.
- **Ladder rungs are LABEL-FIRST**: "Target — recent high · $205 — room above.
  Reward…", "Current price · $191 — …", "Buy zone · $179–$190 — … Supports: …",
  "Exit · $179 — if you buy and it ends a day below this, sell." Weak mini-ladder:
  1-year high / Current price / Exit. The 52-week-vs-recent-high confusion is gone —
  the target rung names its source.
- **"Exit" replaces "safety line"/"sell line" EVERYWHERE** (backend action notes ×5,
  numlab, ladder) — one word, one meaning.
- **Cone captions**: "Typical case (about a 68% chance)" / "Wider case (about a 95%
  chance)" (was 2-in-3 / 19-in-20).
- **Page background WHITE** (body only; `--bg` grey stays for chips/highlights inside
  cards where it now provides the contrast).
- Verified on the rendered page: ATI (buy — band/pills/ladder/RR/cone/tooltip title
  "15 Jan 2026"), CRM (weak — mini-ladder + "your exit line"), engine unit tests 7/7,
  console clean. LOCAL-ONLY — Render deploy still pending.

## Home-page v4 refinements — DONE (2026-07-15, second approved mockup round)

User's v2 critique → v4 (each verified on the rendered page against a written checklist):
1. **Disclaimer** now a QUIET GREY line (2px grey left border, ink2 text) and reworded:
   "A study tool, not a tip sheet — it points to charts worth your attention; the
   decision is always yours. Educational only, never a buy or sell signal." Amber now
   belongs to the mood banner ALONE (they clashed before).
2. **Mood banner** (`.mood` + shared `moodHtml()` used by home AND screener): colored
   dot + 4px left border + bold lead — "Market mood: consolidating. Be selective with
   new buys — fewer, better trades." (trending / under pressure variants).
3. **Study rows**: reason INLINE next to the name ("TXN · resting near its 50-day
   line"), ellipsis when tight, price+% right, long names capped at 55%.
4. **ONE footer line**: "Free public data — prices may lag. Always do your own checks."
   (the educational sentence lives in the disclaimer, not duplicated).
5. **Study list AUTO-BUILDS**: a cold `/api/home` kicks `_kick_scan()` (background
   thread, `_BUILDING` set prevents stacking on the single-flight lock) and returns
   `building:true`; the card shows "Building today's list — about a minute. It fills in
   by itself; you can search meanwhile." and the frontend re-polls every 10s (cap 15)
   until rows appear. Verified NO-TOUCH: fresh server → page loaded once, never
   clicked → filled itself with 48 names.
6. **Home column capped at 620px, centered** (desktop was stretching to 1040px and
   looked sparse vs the approved sample).
7. **BUG FOUND BY THE AUTO-BUILD + FIXED** (`market_scan.friendly_sector`):
   TradingView sends `float('nan')` for a missing industry/sector; NaN is truthy so
   `(x or "").lower()` crashes — the whole US scan died. Guard: `isinstance(x, str)`.
   Pre-existing (would also have hit Render); India data just never tripped it.
8. **Suggest SUFFIX FALLBACK (ABB case, user-reported 2026-07-15):** Yahoo's plain
   search ranks the global brand — "ABB" returns the Swiss parent + ABBV/ABT and
   ABB.NS never appears, so an Indian user got NO Indian rows. `/api/suggest` now
   retries with the market's exchange suffix (IN `.NS` / UK `.L`) when the query is a
   bare token and the first pass had no selected-market rows, and puts those rows on
   top (mirrors `_screen_resolved`). Verified rendered: India + "ABB" → "ABB INDIA
   LIMITED · NSE" first → read opens w/ LIVE badge; US "ABB", "marksans" regressions
   unchanged.

## Home-page redesign v2 — DONE (2026-07-15, user-approved mockup, then "Build it")

History: v1 was built unasked, reverted (user reviews a SAMPLE first — see the
mockup-before-build memory rule). v2 mockup approved in chat, then built:
- **Disclaimer callout** (amber, Sanat wording): "builds a watchlist to study, not a
  buy list…". NO step rail (v1 had one; user cut it).
- **Search**: compact blue "Read ›" button INSIDE the search field (v1's full-width
  black bar was "way too big") + type-ahead dropdown (`/api/suggest`: Yahoo search
  day-cached per (q, market), only engine-readable exchanges via `_EXCH_UI`,
  selected-market first; picking an other-market name switches the pill — verified with
  Marksans under US → NSE pick → India pill + read w/ LIVE badge). ↑/↓/Enter/Esc;
  mousedown-beats-blur.
- **Market pills**: selected = solid blue + ✓.
- **Mood strip** (home + screener share `stripHtml`, reworded per user — old "Market
  check: so-so" sounded wrong): Risk-On "Markets are trending — good conditions for
  buyers." / Neutral "Markets are consolidating — be selective with new buys." /
  Risk-Off "Markets are under pressure — protect money first."
- **"Today's study list"** (`/api/home`): top-3 verified Buy-zone rows (readiness dot,
  today's % green/red, plain why-text) + "see all N ›". PEEKS the momentum cache only —
  never triggers the 30–60s scan; honest cold copy; calm/hot legend only with rows;
  `show("search")` re-runs `loadHome()` (stale-after-scan fix).
- Verified rendered (US+IN, cold+warm, suggestion pick, back-refresh, screener strip
  wording + live Nifty, 0 console errors). LOCAL-ONLY — Render deploy still pending.

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

---

## Screener rework — DONE (2026-07-12)

User-reported gap, verified live: the momentum lanes select for MOTION while JLaw buys
REST — none of the read's "Looks buyable" leaders (MRVL/ARM/KLAC/LRCX/PANW/ALAB/CRDO
that day) appeared in ANY lane. Shipped (commit 6f2bb8c):

- **Buy-zone lane + default tab** — a proven leader (true-RS vs the index over 3 & 6
  months, above the 200-day) whose dip has HAPPENED (≥5% below the 52-week high, week
  floor −15% since a sharp down-week often *creates* the dip), now RESTING ON support
  (above at least one of the 20/50-day, within 1 ATR of one of them — TradingView `ATR`
  + `SMA20` added to the scan), calm today (|change| < 4%). Item carries `dip_q`
  (ATR-distance to support; tab sorts tightest-first) + "resting near its 20/50-day
  line" why-text. Cross-engine validated: 9/10 top candidates read "Looks buyable",
  1 "wait to steady", 0 weak. Gate lessons: must be ON support, not within-1-ATR from
  BENEATH (LSCC/NXPI leak); no max-depth floor (MRVL −28% off-high healthy dip).
- **Readiness dot on every row** in every tab (green "calm spot" / amber = >4 ATRs
  above the 50-day OR |today| > 4%) + legend — actionable names stand out even inside
  Fast movers.
- **Tabs reordered by actionability** with live counts: Buy zone (default) · Early ·
  Quiet leaders · Fast movers. "By sector" is now a **toggle** that groups whichever
  tab is active (was its own tab). Intros reframed: Quiet leaders = the watchlist (buy
  their next dip, not the high); Fast movers = awareness, usually not entries.
- **Market strip** on the screener: regime in plain words (healthy — good hunting /
  so-so — be choosy / weak — go slow), from `_regime_cached` per market. Never shows
  Risk-On/Off jargon or "JLaw".

Still parked from this line of work: a dedicated "tightening / base-building" rank
(volatility-contraction ordering inside Buy zone), and the weak/short list above.

---

## Kite live layer (India) — DONE (2026-07-13) + PENDING DECISIONS

**DONE (commit 1437841):** optional live-NSE layer via the user's gold-study Kite app
(`backend/kite_live.py`; token = user's daily morning login). When live: LIVE badge +
live price/% on IN reads (10-min cache buckets), time-of-day-honest volume check, live
row %s on the India list, live Nifty on the market strip. ANY failure (no token, lapsed
subscription — expected in ~2 months, missing lib) → silent byte-identical Yahoo
fallback; Render always runs the fallback (kiteconnect deliberately NOT in
requirements-prod). Verdicts never consume Kite data — freshness only.

**PENDING DECISIONS (offered to the user 2026-07-13, unanswered):**
- Wire "heavy selling on a down day" into the verdict (PENG showed "Looks buyable"
  beside a red heavy-selling check; currently informational by design).
- Extend read-engine verification to the readiness dots of the Early/Quiet/Fast tabs
  (~+30–60s on the day's first scan) vs accepting conservative amber-on-buyable
  errors (TWST case; recommendation was to accept).
- Wikipedia-fallback one-liner for companies without a page ("A mid-size Electrical
  Products company on the NSE") so the about-line never comes up empty.

**PENDING (bigger): ⭐ Render deploy** — local is ~15 commits ahead of origin; waiting
only on the user's go. Post-push checks: 401 auth, UK pill absent, one read, screener
tabs, health. Prod stays Yahoo-only (no Kite, news off).
