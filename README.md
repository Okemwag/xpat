<p align="center">
  <img src="logo.png" alt="Xpat logo" width="190">
</p>

# Xpat

### Localized catastrophe-risk intelligence for African insurance markets

**We turn flood information into financial risk intelligence.**

Xpat helps insurers and reinsurers understand where a portfolio is exposed to flooding, what it could lose under different scenarios, which properties and places drive those losses, and how much trust to place in the result. Nairobi urban flooding is the first use case for a broader catastrophe-risk intelligence product.

## Why Xpat exists

An insurer may know the total value of the properties it covers without knowing how much of that value is concentrated in places that could flood during the same event. A reinsurer considering that portfolio needs more than a map or a single risk score. They need a clear view of the possible financial loss and the assumptions behind it.

That is difficult in Nairobi. Flooding can arise from heavy rain, overwhelmed or blocked drainage, runoff across built-up surfaces, low-lying ground, and nearby waterways. Available flood information is incomplete, and a broad regional map can miss a very local drainage problem. At the same time, a property's location, construction, and insured value can be imperfect or inconsistent.

Xpat is designed to bring those pieces together and answer the questions that matter to an underwriting decision:

> **What is exposed? What could be lost? Where is the loss concentrated? Why does the estimate change? What should be investigated before taking the risk?**

## What the product does

Xpat follows the path from a portfolio of insured properties to an explainable view of potential flood loss:

| Area | Question it answers |
|---|---|
| **Exposure** | Where are the properties, what are they made of, and how much value is at risk? |
| **Flood hazard** | Which locations have higher flood susceptibility under the available scenarios? |
| **Vulnerability** | How might different types of buildings be damaged at a given level of hazard? |
| **Financial impact** | What is the estimated loss for each property and the portfolio as a whole? |
| **Accumulation** | Are large amounts of value or loss concentrated in the same area? |
| **Explanation** | Which inputs, assumptions, and uncertainties drive the result? |

The intended result is an underwriting assessment that can be traced from a portfolio-level figure back to the individual properties and assumptions that produced it. It should help an underwriter identify concentrations, compare scenarios, and decide where further investigation is needed.

## The Nairobi demonstration

Xpat accepts real portfolios — a CSV or Excel schedule, or a broker document such as a placement memo (PDF or Word), read by AI with every value quoted and checked. Real data is labelled REAL in every result; contact details are removed before any AI sees a document, and nothing uploaded is stored as a file.

The current demonstration uses **600 synthetic Nairobi properties** across four construction categories: informal iron-sheet, semi-permanent, permanent masonry, and reinforced concrete. Each property has a location and an insured value. Five supplied flood-susceptibility scenarios provide the starting hazard view.

The demonstration can validate the portfolio, identify value inconsistencies, calculate illustrative damage and loss for each property, and aggregate those results across the portfolio. It also shows how losses vary across the five scenarios and where insured value and modelled loss are concentrated. The results can be reviewed and exported with their assumptions and provenance.

The supplied portfolio states **KES 63.64 billion in total insured value**. That is the value used in the baseline calculation so the result remains traceable to the supplied records. A separate description of the dataset gives a total near **KES 6.36 billion**, and the stated property values are approximately ten times floor area multiplied by cost per square metre. The source of this difference has not been confirmed. Xpat flags it and shows an alternative calculation based on area and cost instead of silently changing the portfolio.

The supplied baseline hazard identifies **12 of 24** geocoded, government-named flood-prone areas when a positive score is treated as detection. This is a useful check on the starting map. It does **not** establish that the model accurately predicts floods across Nairobi. Thirteen additional named areas from the wider list of 37 still need sourced locations and review.

## How an underwriter would use Xpat

The intended experience begins with a portfolio review. Xpat highlights missing or questionable property information before a financial result is accepted. The underwriter then examines where insured value is located, compares it with flood susceptibility, and inspects the properties that contribute most to the modelled loss.

For each scenario, the underwriter can see the portfolio loss, a breakdown by construction type and area, and a loss-versus-rarity view. A property-level explanation connects the value at risk, its hazard score, the assumed damage relationship, and the resulting loss. The final assessment brings together the findings, evidence, assumptions, and open questions so the underwriter can make a documented decision.

On the **Underwriting decision** page the underwriter enters the offered premium (for 100% of the risk) and the offered share. The organisation's own rules — set by the head of underwriting — recommend **accept**, **take a smaller share** or **decline**, showing each rule's check: price against a technical premium (modelled annual loss with an uncertainty load, at a target loss ratio), our share of the 1-in-250 loss and of insured value against capacity limits, and how much of the schedule could be modelled. AI can explain the recommendation and suggest questions for the broker, but it cannot change it. A person records the final call; overriding the rules needs a written reason, and decisions above the authority limits need the head of underwriting. Starter rules are in `configs/underwriting_rules.json` and are an assumption, not market guidance.

Every analysis can be downloaded as a **PDF** or **Word** report (headline figures, loss curve, concentrations, assumptions, provenance, limitations, and any AI briefing and decisions) or as an **Excel** workbook with every table and every property's loss in every scenario as numbers.

## Where AI fits

Xpat uses Gemini in a few clearly bounded places. First, a portfolio can be described in plain English and turned into validated property records. Second, and more importantly, the AI focuses on flood evidence that ordinary maps may miss. Reports about flooding, drainage failures, and affected neighbourhoods can contain useful local information, but they arrive as unstructured text. The workflow extracts the reported place, event, flood mechanism, and supporting passage; preserves the source; and requires a named reviewer's approval when a location or claim is uncertain.

Approved evidence informs a **documented adjustment** to the baseline hazard assessment. Xpat recalculates losses and shows exactly which properties and portfolio figures changed. The financial calculation itself remains governed by explicit model assumptions: an AI-generated statement is not treated as a flood depth, damage ratio, or monetary loss.

Gemini also drafts plain-English explanations — an underwriting briefing of the results and the reasoning behind an underwriting recommendation. Both are written only from figures the model produced; every number is checked against them, and neither can change a result or a recommendation.

Eight further AI features extend this for every user. They are documented in [docs/AI_ENHANCEMENTS.md](docs/AI_ENHANCEMENTS.md):

- a **drainage-aware hazard model** that targets the places the terrain map misses
- a **news harvester** that fills the evidence review queue
- a **satellite (Sentinel-1) flood check** that tests any hazard map against observed water
- **storey counts** from Open Buildings heights
- a **schedule quality reviewer**
- **Ask the results**, plain questions answered only from the run's figures
- **referral and quote memos** for underwriters
- **public risk notes** in English and Kiswahili for county teams

Each one is labelled and checked the same way as the features above.

**This enhancement is built but not validated.** The app reports the named-hotspot hit rate before and after, using only evidence independent of the county's hotspot list; any claim that it improves the model still requires independent evaluation. A higher estimate of loss alone is not proof of better risk assessment.

## What the current results mean

The Nairobi demonstration is an **uncalibrated prototype** built to make the catastrophe-modelling journey visible and testable. Its results require the following context:

- The 600 properties are invented for the exercise. They are not a real insurer's holdings.
- The supplied hazard values describe **relative susceptibility**. They are not measured water depths or the probability that a property will flood in a particular year.
- The relationships used to turn susceptibility into damage are illustrative. They have not been validated against Kenyan flood claims.
- The years assigned to the five scenarios are assumptions. The resulting loss curve is a comparison of assumed scenarios, not a calibrated annual loss forecast.
- The reported losses represent a gross damage estimate based on property value. Policy deductibles, limits, and reinsurance arrangements have not been applied.
- A zero score means the supplied proxy did not flag that location. It does not prove that the location cannot flood, particularly where drainage is the main cause.
- Named hotspot coordinates represent approximate neighbourhood locations, not verified positions of flooded buildings.

These distinctions are part of the product's purpose. A useful risk assessment should show what is known, what was assumed, and what remains unresolved.

## Running Xpat

The full approach, assumptions, results and limitations are in **[docs/REPORT.md](docs/REPORT.md)**; the organisation and security work is
tracked in **[docs/ORGANISATION_CHECKLIST.md](docs/ORGANISATION_CHECKLIST.md)**.

```bash
cp .env.example .env   # then set GEMINI_API_KEY or OLLAMA_MODEL (AI), RESEND_API_KEY / RESEND_FROM (e-mail)
make install           # uv sync with dev, geo, ui and ai extras
make db                # optional: local PostgreSQL (set FLOODCAT_DATABASE_URL in .env); otherwise SQLite is used
make app               # migrate, then sign-in/API server on :8000 and the interface on :8501
make test              # full test suite
```

**Local AI with Ollama.** To keep documents on your own machine, run a local model instead of Gemini: `ollama pull llama3.2:3b`, then in `.env` set
`FLOODCAT_AI_PROVIDER=ollama` and `OLLAMA_MODEL=llama3.2:3b` (`OLLAMA_HOST` defaults to `http://127.0.0.1:11434`). Every AI output goes through the
same checks as Gemini's. Small local models are much slower on a CPU and less reliable at reasoning; raise `OLLAMA_TIMEOUT_S` if requests time out.

**Registering.** On the sign-in page, choose **User** or **Administrator**, then **Create an account**:
- **Administrator → Create an organisation:** you become its administrator (owner, plus head of underwriting so you can use
  the model) and are signed in straight away.
- **User → Request an account:** your account is created and your request goes to the administrators of the organisation
  whose allowed e-mail domain matches yours. They approve it and choose your roles in **Administration → Users &
  invitations**; you can sign in once approved.

There is no e-mail confirmation step, so administrators should check who is asking before approving a request.
Registration is on by default outside production; set `FLOODCAT_ALLOW_SIGNUP=1` to allow it in production.
Open the app at the address in `FLOODCAT_APP_URL` (default `http://127.0.0.1:8501`). The sign-in cookie belongs to
that address. The default is `127.0.0.1` rather than `localhost` because on many Windows machines `localhost` resolves to
IPv6 first while the local servers listen on IPv4, so the browser reports "site cannot be reached".

**First organisation from the command line.** An administrator can also create an organisation and invite its owner:

```bash
uv run flood-cat create-org "Your company" owner@company.com --domains company.com
```

The owner receives an invitation e-mail (without Resend configured, it is kept in the database outbox). Owners then invite colleagues,
assign roles and set up company single sign-on from **Administration** in the app. `uv run flood-cat create-platform-admin you@xpat.io`
creates an Xpat staff account for the platform console.

**Demo.** Set `FLOODCAT_ALLOW_GUEST=1` to offer **View demo**: a separate, temporary workspace with the sample portfolio — useful for
judges, off for customer deployments.

**Production.** `docker compose --profile app up` runs PostgreSQL, migrations, the API, the interface, ClamAV and a Caddy reverse proxy
that serves everything on one HTTPS domain (`XPAT_DOMAIN`). Set `FLOODCAT_ENV=production` and `FLOODCAT_SECRET_KEY`
(`uv run flood-cat generate-secret-key`). Schedule `make retention` daily and `make alerts` every few minutes.

## The longer-term vision

Xpat is being shaped for insurers, reinsurers, brokers, and other organisations that need to understand catastrophe exposure in African markets. Nairobi flood is the starting point. The broader vision is to combine localized hazard intelligence, portfolio exposure, vulnerability research, and transparent financial analysis across more regions and, eventually, more perils.

The goal is to support a better decision, not merely produce a more colourful flood map: **what risk is being taken, what could it cost, what drives the estimate, and what needs checking next?**
