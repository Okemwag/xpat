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

The current demonstration uses **600 synthetic Nairobi properties** across four construction categories: informal iron-sheet, semi-permanent, permanent masonry, and reinforced concrete. Each property has a location and an insured value. Five supplied flood-susceptibility scenarios provide the starting hazard view.

The demonstration can validate the portfolio, identify value inconsistencies, calculate illustrative damage and loss for each property, and aggregate those results across the portfolio. It also shows how losses vary across the five scenarios and where insured value and modelled loss are concentrated. The results can be reviewed and exported with their assumptions and provenance.

The supplied portfolio states **KES 63.64 billion in total insured value**. That is the value used in the baseline calculation so the result remains traceable to the supplied records. A separate description of the dataset gives a total near **KES 6.36 billion**, and the stated property values are approximately ten times floor area multiplied by cost per square metre. The source of this difference has not been confirmed. Xpat flags it and shows an alternative calculation based on area and cost instead of silently changing the portfolio.

The supplied baseline hazard identifies **12 of 24** geocoded, government-named flood-prone areas when a positive score is treated as detection. This is a useful check on the starting map. It does **not** establish that the model accurately predicts floods across Nairobi. Thirteen additional named areas from the wider list of 37 still need sourced locations and review.

## How an underwriter would use Xpat

The intended experience begins with a portfolio review. Xpat highlights missing or questionable property information before a financial result is accepted. The underwriter then examines where insured value is located, compares it with flood susceptibility, and inspects the properties that contribute most to the modelled loss.

For each scenario, the underwriter can see the portfolio loss, a breakdown by construction type and area, and a loss-versus-rarity view. A property-level explanation connects the value at risk, its hazard score, the assumed damage relationship, and the resulting loss. The final assessment brings together the findings, evidence, assumptions, and open questions so the underwriter can make a documented decision.

## Where AI fits

Xpat uses Gemini in two places. First, a portfolio can be described in plain English and turned into validated property records. Second, and more importantly, the AI focuses on flood evidence that ordinary maps may miss. Reports about flooding, drainage failures, and affected neighbourhoods can contain useful local information, but they arrive as unstructured text. The workflow extracts the reported place, event, flood mechanism, and supporting passage; preserves the source; and requires a named reviewer's approval when a location or claim is uncertain.

Approved evidence informs a **documented adjustment** to the baseline hazard assessment. Xpat recalculates losses and shows exactly which properties and portfolio figures changed. The financial calculation itself remains governed by explicit model assumptions: an AI-generated statement is not treated as a flood depth, damage ratio, or monetary loss.

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

The full approach, assumptions, results and limitations are in **[docs/REPORT.md](docs/REPORT.md)**.

```bash
make install        # uv sync with dev, geo, ui and ai extras
make app            # Streamlit interface at http://localhost:8501
make test           # full test suite
make outputs        # rebuild the published results in outputs/
```

Copy `.env.example` to `.env` and set `GEMINI_API_KEY` to enable the AI features; without it the app runs and says AI is off. Set `FLOODCAT_ADMIN_USER` and `FLOODCAT_ADMIN_PASSWORD` to create the first admin. Judges can use **Explore as guest**. No database is needed; runs, evidence and accounts are kept under `runtime/store/`.

## The longer-term vision

Xpat is being shaped for insurers, reinsurers, brokers, and other organisations that need to understand catastrophe exposure in African markets. Nairobi flood is the starting point. The broader vision is to combine localized hazard intelligence, portfolio exposure, vulnerability research, and transparent financial analysis across more regions and, eventually, more perils.

The goal is to support a better decision, not merely produce a more colourful flood map: **what risk is being taken, what could it cost, what drives the estimate, and what needs checking next?**
