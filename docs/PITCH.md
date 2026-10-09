# Xpat: 5-minute pitch and live demo

A spoken script with the clicks for the live demo. Speaking time is about 650 words at a steady pace; the demo actions
fit inside it. **Say** = words to speak. **Do** = what the person at the keyboard does. Every figure below is from the
synthetic starter portfolio, so say "synthetic" whenever you quote one.

| Time | Part | Who |
|---|---|---|
| 0:00 – 0:25 | The problem | Speaker |
| 0:25 – 0:50 | What we built | Speaker (flow diagram on screen) |
| 0:50 – 3:40 | Live demo | Speaker + driver |
| 3:40 – 4:25 | Why you can trust it | Speaker |
| 4:25 – 5:00 | Who it helps, and the close | Speaker |

---

## Before you go on stage (15 minutes earlier)

Run these once in Git Bash, from the project folder:

```bash
cd ~/OneDrive/Desktop/xpat
uv sync --extra dev --extra geo --extra ui --extra ai
set -a; source .env; set +a
export FLOODCAT_DEMO_LOGINS=1          # one-click sign-in buttons for the demo roles
export FLOODCAT_SYNTHETIC_ONLY=1       # the demo accepts synthetic data only (the brief's rule)
uv run flood-cat init-db
uv run flood-cat seed-demo             # creates "Kenya Re (demo)" with one account per role
uv run --extra ui --extra ai --extra geo python scripts/run_app.py
```

Then, in the browser at **http://127.0.0.1:8501** (use exactly this address):

1. **Approve one piece of flood evidence** so the AI step has something to show.
   - Sign in → **Demo accounts** → **Analyst** → **AI flood evidence** → **Add manually**: a place the map misses, for
     example *Kibera*, mechanism *Drainage failure*, a quote from a real report, *independent of the hotspot list* ticked.
   - Sign out → **Demo accounts** → **Reviewer** → **AI flood evidence** → **Evidence library** → **Approve**.
     (A different person must approve: separation of duties.)
2. Sign out, then sign in as **Head of Underwriting** (one click). Leave this tab on the sign-in page for the demo.
3. Open a second tab on **docs/WORKFLOW.md** (or the Xpat Solution Flow page) for the diagram.
4. Ask the home-page assistant one question in advance ("What can the model not see?") so an answer is already on
   screen if you have no time to wait for one live.
5. Check the drainage layers exist (`runtime/drainage/osm_layers.json`). If not, skip the Hazard checks step.

Keep this cheat sheet open on the presenter's phone:

| Figure (synthetic portfolio) | Value |
|---|---|
| Properties / insured value | 600 / KES 63.64 bn |
| 1-in-100 year loss | KES 1.70 bn (2.67% of value) |
| 1-in-250 year loss | KES 2.65 bn (4.16% of value) |
| Average annual loss (AAL) | KES 125.9 m |
| AI evidence demo (`outputs/ai_effect.md`) | AAL KES 125.9 m → 139.6 m; 21 properties raised |
| Named flood areas flagged | terrain map 12 of 24; with drainage layers 21 of 24 (not validated) |

---

## 0:00 – 0:25 · The problem

**Say:**
> "In April 2024, Nairobi had its heaviest rains in two decades. More than 20,000 families were displaced, mostly in
> informal settlements (WRI, 2026). Yet no insurer in Kenya has a locally built flood catastrophe model. Underwriters price flood
> on judgement and global maps, and there is no public measure of surface-water flooding anywhere in Nairobi.
> So nobody can say, with numbers, what a 1-in-100 year flood would cost a portfolio."

## 0:25 – 0:50 · What we built

**Do:** show the flow diagram (second tab).

**Say:**
> "Xpat is a working flood catastrophe model for Nairobi. A property list goes in. We look up flood hazard at every
> property, apply a published damage curve, add up the losses and turn them into a loss curve by return period, with
> insured and reinsured views. AI comes in at exactly two points, and both change the numbers: it reads messy broker
> documents into property data, and it brings in drainage evidence the terrain map cannot see. Everything after that is
> fixed, traceable arithmetic."

## 0:50 – 3:40 · Live demo

### 0:50 · Sign in (5 seconds)

**Do:** sign-in page → **Administrator / User** choice is visible → **Demo accounts** → **Head of Underwriting**.

**Say:**
> "Each person signs in with their own role. I'm the head of underwriting at a demo reinsurer."

### 0:55 · Run a portfolio (40 seconds)

**Do:** **Portfolio** → **Sample portfolio** → **Run the sample portfolio**. It lands on **Overview**.

**Say:**
> "This is the 600-property synthetic portfolio from the starter kit, labelled SYNTHETIC everywhere it appears. Total
> insured value 63.6 billion shillings. The headline an underwriter can budget with: a 1-in-100 year flood costs about
> 1.7 billion, 2.7% of value. The average annual loss is about 126 million."

**Do:** point at the loss curve; hover one point to show the tooltip.

**Say:**
> "This is the exceedance-probability curve from 10,000 simulated years. Read it left to right: rarer floods, bigger
> losses. Hover any point and it tells you in words: '1-in-500 year loss, so many shillings'. The grey band is the
> simulation range, not a confidence interval."

### 1:35 · Honest about the hazard (25 seconds)

**Do:** **Data & honesty**, showing the map of the 24 named flood areas.

**Say:**
> "Here is the limit we start from. The hazard map is a proxy from real terrain and rivers. It flags only 12 of the 24
> flood areas the county names. The misses, like Kibera, Westlands and Lavington, flood because drains fail, and terrain
> can't see drains. That gap is exactly where we pointed the AI."

### 2:00 · AI that changes the result (50 seconds)

**Do:** **AI flood evidence** → **Evidence library** (the approved Kibera item) → **Impact on losses** → **Re-run the
current portfolio with AI evidence**.

**Say:**
> "The AI reads flood reports and Kenyan news and pulls out the place, the cause and a word-for-word quote. Nothing
> changes until a named reviewer approves it: I can't approve my own evidence. Once approved, hazard rises near that
> place, and the losses change. In our measured demo, average annual loss moved from 126 to 140 million. We show before
> and after, because a higher loss is not proof of a better model."

**Do (if time and drainage layers are built):** **Hazard checks** → **Drainage model**, showing *Named hotspots flagged*.

**Say:**
> "We also built a drainage layer from OpenStreetMap drains and building density. It raises the hit rate from 12 to 21
> of the 24 named areas. We say plainly that this is not validated: building density does most of the work."

### 2:50 · The underwriting decision (40 seconds)

**Do:** **Underwriting decision** → premium **400,000,000**, share **20** → **Get recommendation**.

**Say:**
> "Now the question an underwriter actually has: should I write this, and how much? The organisation's own rules
> answer. Here is plain advice: what to do, why, and the conditions, including 'this is synthetic data, do not quote
> on it'. Pricing shows how the technical premium is built from the annual loss, and whether the offer is adequate,
> thin or inadequate. Accumulation shows how much loss we'd hold in each square kilometre, including risks we've
> already written. AI can explain this, but it has no way to change the outcome. A person records the decision, and
> overriding the rules needs a written reason."

### 3:30 · The assistant (10 seconds)

**Do:** **Overview**, scrolled to the **Xpat assistant**, showing the answer prepared earlier (or ask a new question if
the room allows).

**Say:**
> "And anyone, a broker or a county officer, can ask the assistant. It answers from our documentation, cites its
> sources and flags any figure it can't trace."

## 3:40 – 4:25 · Why you can trust it

**Say:**
> "Three rules hold the whole system together. First, every number carries a label: real, proxy, synthetic,
> assumption or AI. You can see on every chart where it came from. Second, AI is never allowed to set a flood depth, a
> damage ratio or a loss. It can only supply data that passes the same checks as a spreadsheet, or evidence a person
> approved, and every figure it writes is checked against the model. Third, we state our limits: the hazard is a proxy,
> return periods are assumed, and the damage curve is the published JRC Africa curve, adapted per construction type and
> not calibrated to Kenyan claims. All of that is in the app and in our report."

## 4:25 – 5:00 · Who it helps, and the close

**Say:**
> "Underwriters get a defensible loss by return period in minutes. Portfolio managers see where value and loss pile up.
> Brokers and cedants get faster, consistent quotes from their own documents. County teams get plain flood notes for
> each area, in English and Kiswahili, with no financial data. The next step is calibration: real claims and measured
> flood depths would turn this proxy into a priced model. Xpat: a flood loss curve for Nairobi, honest about what it
> knows. Thank you."

---

## If something goes wrong

| Problem | What to do |
|---|---|
| A live AI call is slow (over 10 seconds) | Keep talking; the evidence step uses evidence approved earlier, so no AI call is needed live |
| AI is unavailable | Say "AI is off here; the model still runs". The pipeline and decision work without it |
| The app will not start ("port unavailable") | `netstat -ano \| findstr :8501`, then `taskkill //PID <number> //F`, and start again |
| Sign-in shows "site cannot be reached" | Open exactly `http://127.0.0.1:8501`, not `localhost` |
| No demo account buttons | `export FLOODCAT_DEMO_LOGINS=1`, run `uv run flood-cat seed-demo`, restart the app |
| No time for the decision step | Skip to "Why you can trust it" at 3:40; the decision is the first thing to drop |

## Questions judges are likely to ask

**"Is this accurate?"**
> "We don't claim accuracy. The hazard is a proxy and nothing is calibrated to Kenyan claims. What we claim is
> traceability: every number can be followed back to its input and assumption, and we test the model's invariants,
> such as loss rising with return period and property losses adding up to the total."

**"How is the AI more than a description?"**
> "It changes what goes into the model. Documents become property rows that would not exist otherwise, and approved
> drainage evidence raises the hazard and the loss. We report the before and after for both."

**"Why do return periods go 10 to 250 when the tier is called 'common'?"**
> "Tier names describe how extreme a cell is, not how often it floods. 'Common' keeps the widest footprint, so it is
> the rarest event: 1-in-250. That mapping is an assumption from the dataset's reference dashboard, stated in our
> config."

**"The brief says reinsurance is out of scope. Why is it here?"**
> "Objective 1 asks for insured and reinsured loss, so we show an illustrative quota share and excess of loss to
> answer it. It is clearly labelled as an assumption, not a real treaty, and we don't offer treaty structuring."

**"Did you use real client data?"**
> "No. The demo runs in synthetic-only mode with the starter portfolio. The product can label real uploads, but that
> is future work, outside this brief."

**"How did you improve the hazard, and does it work?"**
> "Reviewed drainage evidence and a drainage layer from OpenStreetMap. The layer flags 21 of 24 named areas against 12,
> but we tested it on those same areas and density drives most of it, so we call it promising, not validated. A
> Sentinel-1 satellite check is built to test it independently."

**"What would you do with more time?"**
> "Calibrate against claims and measured flood depths, validate the drainage layer on satellite flood maps, and replace
> the assumed return periods with ones fitted to Nairobi rainfall."
