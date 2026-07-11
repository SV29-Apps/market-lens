# Market Lens — read logic (the JLaw rules the app follows)

How the plain-English read is decided, and the JLaw principle behind each rule.
Keep this in sync with `backend/plain_read.py` — if you change the code, update here.

---

## The verdict (green / amber / red)

Computed from the engine's numbers (relative strength, moving averages, distance
from the 52-week high, market regime).

**Shape of the code (matrix refactor, 2026-07-11 — same rules, safer structure):** the
verdict is a **2-axis matrix** in `plain_read._CELLS`. Axis 1 = **leadership tier**
(weak / leader / emerging / mixed). Axis 2 = **pullback health** (deep_fade / sliding /
stretched / resting). One cell = one complete package — tag, headline, paragraph, action
box and chart buy-line are built together, so a "wait" headline can never sit above a
"buy now" box. Verified behaviour-identical on the refactor day: 0 diffs across a
21-name regression, 17/17 unit tests. To change a rule: edit a cell, or move an axis
boundary — don't add an `elif`.

- **Buy-ready (green)** — a leader (beating the market over 3 & 6 months, above its
  200-day) that is **resting at a calmer spot** (not stretched, not near its high,
  didn't just pop). *JLaw: only buy the strongest names, and only at a low-risk edge.*
  **The 6-month lead must be > 2 pts (2026-07-11)** — a hairline +0.1% "lead" is noise;
  such names read as **emerging** instead (blind-judge finding, AMBA case). The screener's
  Early lane mirrors this with a ≥2-pt *lagging* requirement, so a borderline name can't
  sit in "Early" while the read calls it a proven leader.
- **Strong, wait (amber)** — a leader, **but** it's stretched, near its 1-year high,
  or just jumped. *JLaw: never chase — wait for a pullback to a low-risk entry.*
  **"Stretched" is measured in the stock's OWN volatility (2026-07-11): > 4×ATR above
  the 50-day = stretched, > 7×ATR = parabolic — the same graded scale the setup-check
  dot uses, so the verdict and the dot can never contradict. (Replaced the old flat
  ">12% above the 50-day", which JLaw rejects — a volatile stock 13% above its 50-day
  can be a normal wobble; a quiet stock 8% above can be genuinely stretched.)**
- **Pulled back hard — let it steady (amber, "wait")** — a 3-&-6-month leader that is
  now pulling back **un-healthily**: its **RS line has turned DOWN** (lagging, not leading,
  during the dip), it's **below its 20-day**, and it's **>18% below its 1-year high**. Not
  a clean buyable dip — a drop this deep is often news-driven, so wait for it to stop
  falling and turn back up before buying. *JLaw's "normal vs abnormal pullback": a deep
  decline where the stock stops showing relative strength must prove it repairs first. This
  is the read that used to give a deep-faded leader (e.g. NBIS) a naive "buy the dip."
  (Added 2026-07-06.)*
- **Pulling back — wait for it to steady (amber, "wait")** — the *milder cousin* of the
  above: a 3-&-6-month leader that would otherwise be a clean **buy**, but is **still
  sliding below its 20-day** with its **RS line falling** — even though the drawdown isn't
  deep (< 18% off the high). It hasn't *steadied* yet, so it isn't a "buy now" — wait for it
  to settle and reclaim its short-term line. *JLaw: buy the pullback when it steadies /
  reclaims, don't catch a leader mid-fall. Requires BOTH below-20-day AND falling-RS (a
  rising-RS or above-20 leader stays "buy"), so it fires narrowly. Added 2026-07-06 from the
  5-July fidelity re-test (LSCC/OSS-type "buy into a still-sliding leader").*
- **Gaining strength — don't chase (amber, "wait")** — NOT yet a 3-&-6-month leader,
  BUT the **RS line is turning up** in an intact long uptrend (above 200-day) and it's
  **beating the market lately** (1m or 3m excess > 0) — and it just ran/near-high. A real
  emerging move, but wait for a pullback. *(Added 2026-07-02.)*
- **Early — just turning up (amber, "emerging")** — same emerging signal but at a
  reasonable spot (reclaiming its trend, not extended/popped). Gets a **starter-position,
  tight-stop, "size small — not a confirmed leader yet"** action. *JLaw's "early leader /
  Stage 1→2 turn" — real but earlier-stage and higher risk. This is the read that used to
  wrongly land fresh-momentum / turnaround names (APP, HOOD, RDDT, MDB) on "not a clear
  leader." (Added 2026-07-02; widened 2026-07-06 — see below.)*
  - **Two ways in (2026-07-06):** (a) an **intact long uptrend** — above the 200-day and
    beating the market over 1m or 3m; OR (b) an **early repair** that has **reclaimed BOTH
    its 20- and 50-day lines with the RS line rising** even while **still below the
    200-day** (a Stage 1→2 turnaround from lower down). Path (b) is what catches names like
    **NOW, APP, FIG** that had reclaimed their short/medium trend but sat under the 200-day,
    so the old rule dropped them onto "not a clear leader."
- **Getting weaker / avoid (red/amber)** — below its recent trend lines and lagging
  the market. *JLaw: relative weakness is the mirror of the leadership we want.*
- **Not a clear leader (amber)** — no fresh strength (RS not turning up, or no recent
  outperformance): genuinely mixed → point the user at stronger names.

**Market gate (fixed 2026-07-11):** in a **Risk-Off** market, ANY buy-now — an established
leader's buy **or** an emerging starter-buy — is downgraded to "wait", and the WHOLE card
moves together: headline, paragraph, action box and the chart's buy line (the old gate
rewrote only the headline, leaving a "good spot to buy" box under a "go slow" banner).
Classify order: weak_now → **established leader** (RS 3m&6m>0 + above 200; within this, in
order: deep-faded → "pulled back hard"; **still-sliding below-20-day + falling-RS **OR a >4% DOWN day today** →
"pulling back, wait to steady"** (checked BEFORE the chase test since 2026-07-11 — a one-day
+4% bounce or being near its high must not flip a still-sliding leader back to "buy the
dip". The >4%-down-day arm is the MIRROR of just-popped, added 2026-07-11 MDB case: a big
red day is mid-fall, not a calm entry; emerging names get "Early turn — but let it settle
first" instead of a starter-buy); extended/near-high/just-popped → "strong, don't chase";
else → "buy") →
**emerging** (intact-uptrend path *or* early-repair path, see above) → else mixed →
then the Risk-Off market gate above. Emerging/wait get supports + the news lens like a leader.

---

## The three setup checks (three-state: good / watch / bad)

These are shown as coloured dots, **not** ✓/✗ ticks — because some factors are
context-dependent, not simply good or bad. A dot's colour is the signal:
🟢 supportive · 🟠 watch / neutral · 🔴 warning.

### 1. Over-extension  (ATR — one graded scale, shared with the verdict; 2026-07-11)
- 🟢 **Not over-extended** — price is within ~4×ATR of the 50-day.
- 🟠 **Stretched above its average — a dip is safer** — 4–7×ATR above the 50-day
  (the same threshold that makes the verdict say "don't chase").
- 🟠 **Over-extended (parabolic) — risky** — more than ~7×ATR above the 50-day.
- *JLaw measures "extended" in volatility (ATR) terms, not a flat %.* It's a *caution*
  (amber), not a hard negative — strong stocks can stay extended for a while.

### 2. Volume — **DIRECTION-AWARE** (the important one)
Volume only means something **in the direction of the move**:
- 🟢 **Strong buying — heavy volume, price up** — heavy volume while rising = buyers /
  conviction. This is what a **breakout / buyable gap up** looks like. GOOD.
- 🟢 **Calm pullback — quiet selling** — a dip on low volume = healthy digestion. GOOD.
  **Except on a >4% down day** (🟠 "Sharp down day — let it settle", 2026-07-11): a big
  red day isn't "calm" whatever the ratio says — intraday the session's volume is still
  filling up, so a low ratio can be an artifact.
- 🟢 **Trading is calm** — normal volume, nothing notable.
- 🔴 **Heavy selling right now** — heavy volume while **falling** = distribution /
  people exiting. This is the only volume warning.
- *JLaw ("Bad Price Action"): a pullback on heavy volume is "off"; a breakout NEEDS
  heavy volume. So heavy volume is a red flag ONLY when the stock is going down.*
  (Fixed 2026-07-01 — the check used to flag all heavy volume as bad, which wrongly
  penalised strong up-days like ASML's +5.7% breakout.)

### 3. Relative strength  (judged over a MEANINGFUL horizon, not a recent wiggle)
- 🟢 **Beating the market** — ahead of the market over **6 months** (a genuine leader).
- 🟠 **Lagging — but turning up lately** — behind over 6 months (often below its 200-day)
  but its RS has ticked up recently (a bounce / early turnaround, not yet a leader).
- 🔴 **Falling behind the market** — behind and still weakening.
- *JLaw's #1 rule: relative strength first — but a laggard bouncing off lows is not a
  leader. Must match the verdict: don't show green "beating the market" for a name the
  verdict calls "not a clear leader."* (Fixed 2026-07-01 — the check used to use only the
  RS line's short-term slope, so a 6-month laggard like IDBI, below its 200-day but
  bouncing, wrongly lit green while the verdict said "not a clear leader.")

---

## Reward vs risk  (the "is it worth getting in?" number)

Shown in the read for buy / wait / emerging names (skipped for weak/avoid — there's no buy):
- **reward** = target − entry (the buy zone); **target cascade (2026-07-11):** the
  recent swing high when it's >2% above; else the **1-year high** when that's >2% above
  (an older ceiling is still the next objective — a stock at the top of its recent range
  but 29% under its yearly high has plenty to measure to, SMLMAH case); else none.
- **risk** = entry − stop (safety line). **Emerging starters use the TIGHT stop** —
  ~1.5×ATR below the price, never deeper than the swing low (2026-07-11: a "keep it
  tight" starter was showing a swing-low stop 23% below, HOOD case). Leaders/weak names
  keep the swing-low line.
- **ratio** = reward ÷ risk.
- 🟢 **≥ 2 : 1** — good (could gain more than you'd risk).
- 🟠 **1–2 : 1** — modest (reward roughly matches risk).
- 🔴 **< 1 : 1** — poor (you'd risk more than you could gain).
- 🟠 **can't be measured here** — no RECENT high above the price to use as a target
  (honest no-number case; wording fixed 2026-07-11 — the test is the recent swing high,
  not the 1-year high, and the copy now says so). Thresholds are applied to the ROUNDED
  ratio the user sees, so "1.0" can never read as "poor".
- *JLaw: reward:risk sets your SIZE, not whether to participate — but a poor ratio is a
  strong reason to pass or size tiny. Pulled-back leaders show better ratios than
  extended ones (more room to target, tighter stop). Added 2026-07-01.*

## The action box (what to do)

- **Buy-ready** → a buy zone around the current price + a safety line (stop) below.
- **Wait (don't chase)** → a "buy on a dip to ~X" level (nearest support **below** the
  current price: 20-day, else 50-day, else 10-day, else ~3% down) + the safety line.
- **Wait (still sliding / deep fade)** → a no-number "let it steady first, then it's a
  safer spot" box (deliberately NO dip level — it hasn't stopped falling).
- **Wait (Risk-Off market gate)** → "the market itself is weak — a risky time for new
  buys; market steadies and this holds its level → worth a look" + owner's safety line.
- **Emerging** → a small-starter box ("size small, keep the stop tight — not a
  confirmed leader yet").
- **Weak** → an exit line: stays above X → keep; ends a day below X → sell.

Stop / safety line = the recent swing low — except **emerging starters**, which use the
tight ~1.5×ATR stop (capped at the swing low; see Reward vs risk above). The chart's
stop line and the plan ladder show whichever stop the read actually uses.

---

## Pull-back zone + stacked supports  (`_supports`, added 2026-07-01)

Shown for buy / wait / emerging names. **Layout (2026-07-11): the read's lower half is
ONE price-ladder card** ("The plan — every number in one place": target with reward:risk
on the same line → current price → buy zone with its named supports → safety line →
deeper floors + rough timing as small print) **plus ONE merged dot-list** ("Checks" =
setup checks + chart signals, greens first). The timing line only renders when a real
target exists (same >2% rule as the target itself). Weak/avoid names skip the ladder —
their exit box carries the one number that matters. Instead of one buy level, the zone
lists the supports **below** the current price:
- Candidate levels: the **10 / 20 / 50 / 200-day lines**, the **recent low**, and the
  nearest **round number** below the price (added 2026-07-11; step scales with price —
  10 under 250, 50 under 1000, 100 under 5000, else 500 — and the 0.5% de-dup drops it
  when it sits on top of a moving-average line).
- Keep only levels **below** the price (a support you're already above is where a dip
  could find footing), nearest first; de-dup levels within 0.5% of each other.
- The **zone** = the stacked levels clustered at the top (each within ~6% of the one
  above it); deeper levels are still listed individually.
- Skipped for weak/avoid (they get an exit line, not a buy zone).
- *JLaw / Sanat: a real entry is a **zone** where supports stack, not a single number —
  seeing the 10/20/50-day + prior base line up tells you where buyers step in.*

---

## News factored into the read — "News check"  (`news_sentiment`, `_news_lens`, 2026-07-01)

Headlines alone give a deterministic app nothing to compute, so this uses **sentiment**
(a number) and lets it move the *guidance*, the way the JLaw skill let news move the call.
- **Source:** **Alpha Vantage `NEWS_SENTIMENT`** — a **free key** in env `ALPHAVANTAGE_API_KEY`.
  We aggregate the **relevance-weighted** per-ticker sentiment of recent (~14-day) articles
  into one score, banded to: *very negative ≤ −0.35 · negative ≤ −0.15 · mixed < 0.15 ·
  positive < 0.35 · very positive ≥ 0.35*.
- **It does NOT change the verdict `tag`.** The tag stays purely price-based, identical to
  what the many-name "Strong" list computes — so **list ↔ read never contradict**. News is a
  separate, clearly-labelled **"News check"** banner under the verdict. (The list can't fetch
  news: Alpha Vantage's free tier is 25 req/day, and a list load deep-reads ~30 names.)
- **How it nudges the guidance** (`_news_lens`, keyed to the price tag):
  - Leader pulling back (buy/wait) + **negative** news → *caution* (amber): "a dip on bad
    news can be real damage, not a calm pullback — let it steady before buying." *(JLaw's
    normal-vs-structural test: a fall WITH a bad catalyst is structural.)*
  - Leader (buy/wait) + **positive** news → *confirm* (green): "the move looks real" (and for
    a stretched *wait* name, "some good news may already be in the price").
  - Weak/avoid + **negative** news → *reinforce* (red): "the weakness has a reason — treat the
    fall as real."
  - Weak/avoid + **positive**, or **mixed** either way → *info* (grey): price read stands.
  - **Event-gap aware:** if a big recent bar exists (≥3% gap, engine's `recent_gaps`), the
    caution line adds "it also moved sharply recently, so this is likely news-driven."
- **Honest limit:** full "catalyst vs mechanical" nuance is an LLM job (the parked Max read);
  this is a deterministic sentiment nudge + event-gap awareness.
- **Fetched on the single-read path only**, daily-cached per symbol. **Runs key-free by
  default** — no key / non-US ticker with no coverage / rate-limit → no "News check", price
  read stands unchanged.

---

## Chart signals — JLaw price-action edges  (`_patterns`, `signalsHtml`, 2026-07-06)

A "**What the chart is showing**" box under the chart, translating JLaw's STEP-3 price-action
edges into plain language. Like the News check, it is **informational and does NOT change the
verdict `tag`** (verified: 0 tag changes across 16 names) — it just tells the reader what the
most recent bar / gap / relative-strength picture is doing. At most **2 signals**, ranked, each
with a green (constructive) or amber (caution) dot.

- **Only the UNAMBIGUOUS, snapshot-computable edges** are included, from `last_candle`
  (color / body-% / wick-%), `recent_gaps` (`{gap_pct, dir}`), and RS vs regime:
  - **Gapped up** (buyable-gap-up) — a recent up-gap ≥3% while holding above the 50-day (leader).
    *JLaw BGU entry edge; big gaps are news → check the reason.*
  - **Gapped down** — a recent down-gap ≤ −3%. *Usually news-driven; let it steady.*
  - **Holding up in a soft market** — Neutral/Risk-Off regime + strong RS (3m&6m) + above the
    50-day. *JLaw's core pullback edge: relative strength when the market is weak.*
  - **Long lower tail** (lower wick ≥45%, small body) — dipped then closed near the high =
    shakeout / reversal look. **Long upper tail** (upper wick ≥45%) — pushed up then sold back
    = rejection, don't chase. **Big green / red body** (≥65% of range, with the day's direction)
    = conviction buying / heavy selling.
- **Deliberately EXCLUDED** (need more than the snapshot, or an LLM): **engulfing** (the engine
  exposes only the last candle, not the prior bar), **first-touch** (needs touch history),
  **base/flag** structure, **volume-expansion signature**, **MACD**, full **M.E.T.A. confluence**.
  These stay in the full JLaw *skill* (LLM) — see `market-lens/FUTURE_FEATURES.md`.

---

## Probability cone — "how far could it move?"  (`_chart_payload` cone, `coneHtml`, 2026-07-06)

A shaded **fan** projected forward on the chart showing the stock's **normal range of
outcomes** over ~6 weeks — a *distribution*, deliberately **NOT a forecast of direction**.

- **Method (standard expected-move / GBM cone):** stdev of the last **60 daily log-returns**
  → `dvol`; for each future trading day `t` up to **H=30 (~6 weeks)**, bands are
  `price · exp(±k · dvol · √t)` for k=1 (±1σ) and k=2 (±2σ). **No drift** — centred on today's
  price (over 6 weeks the drift term is noise and would inject a fake direction call).
- **Bands widen as √t** (variance grows linearly in time). Computed in **log space** → a proper
  lognormal, never-negative, slightly asymmetric cone.
- **Honest framing (enforced in the caption):** "typical case ~2 in 3" (±1σ ≈ 68%) and "wider
  ~19 in 20" (±2σ ≈ 95%) are *model* probabilities under normality — real coverage is looser
  (fat tails / earnings gaps), so the wording stays soft ("~", "usually", "not which way").
- **Aligns with JLaw's "think in probabilities / plan for scenarios"** — the quantitative
  version of his refusal to predict a single price ("no crystal ball").
- **Known limit (backlog):** a single **earnings gap** inside the horizon can exceed ±2σ — the
  one thing a realized-vol cone can't see. Verified: math matches an independent recompute to
  ~1e-5; independent quant review = "ship as-is".

---

## Source principles (from the JLaw corpus)

- *Art of Selling — Normal vs Abnormal* and *Bad Price Action*: judge a pullback by
  **how** it falls and **what** it breaks, not just that it fell; volume is directional.
- *Relative Strength*: three tells — positive price divergence, MA leadership, rising
  RS line. Only buy leaders.
- *Risk/Reward & Stop-Loss*: risk control above conviction; a hard stop is the line.
