# Xpat solution flow, from input to decision

How a property list becomes a flood loss curve and an underwriting decision, where AI enters, what it is allowed to
change, and how each step is checked. Every step below exists in the code (`src/floodcat`, `app/`).

Legend for the diagrams: plain boxes are fixed model steps, **blue** boxes are AI stages, **amber** marks a decision a
person makes, and **dotted** lines are independent checks that never change a loss.

## 1. The end-to-end flow

```mermaid
flowchart TB
    subgraph IN["Inputs"]
        I1["Property schedule<br/>CSV or Excel; sample of 600 Nairobi properties<br/><i>SYNTHETIC, or REAL if declared</i>"]
        I2["Hazard maps<br/>5 GeoTIFF tiers from Copernicus GLO-30 terrain + OSM rivers<br/><i>PROXY; tier to return period is an ASSUMPTION</i>"]
        I3["Damage curve<br/>Huizinga et al. 2017 (JRC105688), Africa residential<br/><i>REAL curve; class scales and caps are ASSUMPTIONS</i>"]
        I4["Policy terms<br/>deductible and limit per property; storeys<br/><i>ASSUMPTION</i>"]
        I5["Model settings<br/>configs/default.json: return periods, AAL rule,<br/>reinsurance terms, simulation seed<br/><i>ASSUMPTION</i>"]
    end

    subgraph AI["AI stages"]
        A1["AI reader<br/>broker PDF, Word, text, plain English<br/>→ property rows, every value quoted<br/>quotes verified, places found on OSM<br/>storeys from building-height maps"]
        A2["Flood evidence and drainage<br/>reports and Kenyan news → place, cause, verbatim quote<br/>drainage model from OSM drains and buildings<br/>(off unless switched on)"]
        R{{"Named reviewer approves"}}
    end

    subgraph PIPE["Model pipeline: same input, same result"]
        P1["1. Exposure contract<br/>every row passes one rule set, file or AI<br/>real or synthetic declared per row<br/>schedule check proposes fixes you tick"]
        P2["2. Hazard lookup<br/>score 0–1 per property in 5 tiers<br/>read as 1-in-10 … 1-in-250 years<br/>a score is susceptibility, not depth"]
        P3["3. Vulnerability<br/>assumed depth = score × 1.5 m<br/>→ share of value damaged, per class<br/>capped at 80–95%, never 100%"]
        P4["4. Loss per property<br/>insured value × damage share<br/>× share of storeys that can flood<br/>sum of properties = scenario loss"]
        P5["5. Financial engine<br/>loss per return period, average annual loss<br/>ground-up → insured → reinsured (illustrative)<br/>10,000 simulated years → EP curve and range<br/>accumulation by area and construction"]
    end

    CHK["Independent checks<br/>24 county-named flood areas: terrain map flags 12 of 24;<br/>with drainage layers 21 of 24 (not validated)<br/>Sentinel-1 satellite flood map<br/>never used to train or to change losses"]

    subgraph OUT["Outputs"]
        O1["Results interface<br/>Overview, Loss curve, Accumulation map,<br/>Property explorer, Assumptions,<br/>Data & honesty, PDF / Word / Excel reports"]
        O2["Underwriting decision<br/>accept, smaller share or decline<br/>pricing, accumulation, plain advice<br/>a person records the call"]
        O3["AI writers<br/>briefing, assistant, Ask the results,<br/>referral and quote memos, public notes<br/>every figure checked; cannot change one"]
    end

    I1 --> P1
    I2 --> P2
    I3 --> P3
    I4 --> P4
    I5 --> P5
    A1 -- "rows" --> P1
    A2 --> R -- "raise scores near approved evidence" --> P2
    P1 -- "valid rows" --> P2
    P2 -- "scores per tier" --> P3
    P3 -- "damage shares" --> P4
    P4 -- "property losses" --> P5
    P2 -. "scores before / after AI" .-> CHK
    P5 -- "EP curve, AAL, losses, accumulation" --> O1
    P5 --> O2
    P5 --> O3

    classDef ai fill:#e2edfb,stroke:#1d66c4,color:#15222c;
    classDef human fill:#fbefd9,stroke:#a8670e,color:#15222c;
    classDef check fill:none,stroke:#3f7a52,stroke-dasharray:6 4;
    class A1,A2,O3 ai;
    class R,O2 human;
    class CHK check;
```

AI feeds only two stages. It turns documents into property rows (stage 1) and, after a named reviewer approves the
evidence, raises hazard near drainage problems (stage 2). Stages 3 to 5 take no AI input: AI may never set a depth, a
damage share or a loss. The dotted checks compare the hazard with real places and satellite data but never change a loss.

## 2. From results to an underwriting decision

```mermaid
flowchart LR
    M["Model results<br/>annual loss, 1-in-250 loss, value"] --> E
    O["The offer<br/>premium for 100%, share offered"] --> E
    RU["Organisation rules<br/>set by head of underwriting"] --> E
    B["Written book<br/>risks already accepted, by area"] --> E
    E["Rules engine<br/>price: offered ÷ technical premium<br/>capacity: 1-in-250 loss, value,<br/>and loss per 1 km area with the book<br/>data: share of records modelled<br/>the tightest limit sets the share"]
    E --> REC["Recommendation<br/>accept, smaller share or decline"]
    E --> WHY["Why, in plain words<br/>advice and conditions<br/>pricing and accumulation"]
    REC --> AIX["AI explains, drafts memo<br/>no field for the outcome"]
    WHY --> P{{"A person decides<br/>override needs a reason<br/>over authority → head of underwriting"}}
    P --> AU["Audit log<br/>decision, reason and rules"]
    AU -- "accepted risks join the book" --> B

    classDef ai fill:#e2edfb,stroke:#1d66c4,color:#15222c;
    classDef human fill:#fbefd9,stroke:#a8670e,color:#15222c;
    class AIX ai;
    class P human;
```

The recommendation comes from fixed rules, so the same offer always gives the same answer. AI can explain it or draft a
referral or quote letter, but its output has no field for the outcome or share. The decision a person records is
checked against the rules again on the server, and accepted risks count against the next decision in the same area.

## 3. Where AI is used, and how it is held to account

AI runs on Google Gemini or a local Llama model, chosen by each person within their organisation's rules. When the
organisation keeps client data on its own server, documents and real results only ever go to the local model.

| AI stage | Goes in | What AI does | Checked by | Changes the numbers? |
|---|---|---|---|---|
| AI reader | Broker PDF, Word, text, plain English | Turns text into property rows, one verbatim quote per value | Quote must appear in the source; places located on OpenStreetMap; same validation as a CSV; a person reviews every row | **Yes:** decides what is modelled |
| Flood evidence | Flood reports, Kenyan news (GDELT) | Extracts place, cause and a verbatim quote | Quote check; independence from the county list flagged; a named reviewer approves before anything changes | **Yes:** raises hazard near approved drainage evidence. Demo: AAL KES 125.9 m → 139.6 m |
| Drainage model | OSM drains, culverts, buildings | Drainage-failure probability per place | Never trained on the 24 named areas; hit rate reported in the same terms (12 → 21 of 24) | **Only when switched on** |
| Building storeys | Open Buildings height map | Proposes storey counts where blank | A person accepts each one; normal validation | **Yes:** only lower floors flood |
| Schedule check | Flags from fixed data checks | Explains each problem and suggests a question for the broker | No field for a value or fix; figures checked | No |
| Writers | The run's fact pack and Xpat's documentation | Briefing, assistant, memos, public notes in English and Kiswahili | Every number checked against the facts; sources cited; untraceable figures flagged | No |

## 4. What comes out, for the sample portfolio

Labels: SYNTHETIC portfolio · PROXY hazard · ASSUMED return periods.

| Measure | Value | Plain English |
|---|---|---|
| Insured value | KES 63.64 bn | 600 synthetic properties |
| 1-in-100 year loss | KES 1.70 bn | 2.67% of value; an assumed 1% chance each year of a loss at least this large |
| 1-in-250 year loss | KES 2.65 bn | 4.16% of value; an assumed 0.4% chance each year |
| Average annual loss | KES 125.9 m | long-run yearly average implied by the curve |

Ground-up figures from `outputs/nairobi_day1_results.md` (generated 8 October 2026). Illustrative only: nothing is
calibrated to Kenyan claims.

## 5. Safeguards on every path

- E-mail addresses and phone numbers are removed before any text reaches an AI model, and people consent each time.
- AI output is treated as untrusted data: re-checked by fixed code, never allowed to set a depth, damage share or loss.
- Every number shows where it came from: REAL, PROXY, SYNTHETIC, ASSUMPTION or AI.
- Every change and AI call is written to the organisation's audit log, with the model used.
- The hazard map flags 12 of the 24 county-named flood areas on its own. This limit is stated on every results page.
