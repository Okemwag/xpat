---

**HACKATHON PROBLEM STATEMENT · TEAM A**

**Nairobi Urban Flood Challenge**

*Build an AI-powered flood model for Nairobi, from identifying flood risk to estimating losses for different flood events.*

# Introduction to Reinsurance and CAT Modelling

Insurance is a way of protecting people and businesses against financial losses. A customer pays an insurer a premium, and in return the insurer agrees to pay for certain losses covered by the policy. For example, a Kenyan business may insure its building and contents against flood damage. If a covered flood causes damage, the insurer pays the claim according to the policy terms.

**Reinsurance** is insurance for insurance companies. An insurance company may not want to keep all the risk it has accepted from its customers, especially when a very large loss could affect many policyholders at the same time. It therefore transfers some of that risk to another company called a **reinsurer**. The insurance company that transfers the risk is called the **cedant**.

Catastrophes, or **CAT events**, are a special problem because one event can cause many losses at the same time. For example, heavy rainfall over Nairobi could flood several neighbourhoods and damage hundreds of insured buildings in the same event. This is called **accumulation**: many insured risks are exposed to the same event. An insurer may be able to handle one large claim, but hundreds or thousands of claims from one event can create a much larger financial impact. Reinsurance helps insurers manage this concentration of risk.

A catastrophe model, or **CAT model**, is a computer-based way of estimating how natural hazards could affect insured assets and what the resulting financial losses might be. A CAT model normally brings together four main stages:

- **Hazard:** Describes the physical event, such as flood water and how severe it is at different locations.
- **Vulnerability:** Estimates how much damage an exposed asset may suffer when affected by a particular level of hazard. For example, deeper flood water may cause a higher percentage of damage to a building.
- **Exposure:** Describes what is at risk, such as the location, type and insured value of buildings.
- **Financial engine:** Converts estimated physical damage into financial loss, taking into account insured values and the relevant insurance or reinsurance terms.

A CAT model does not simply ask, "What would happen if a flood occurred?" It also considers how often different levels of flooding could occur. This is where **return periods** become useful. A 100-year return period represents a level of loss associated with an annual probability of approximately 1%, not an event that happens exactly once every 100 years. An underwriter can therefore use a CAT model to understand questions such as, "How large could the loss be from an event with a 1-in-100-year level of severity?"

The results can be shown using an **exceedance probability (EP) curve**. The curve shows the probability that losses will exceed different amounts in a given year. This helps an underwriter understand the range of possible losses, rather than relying only on one expected loss figure. It can support decisions about how much risk to accept, how much reinsurance protection may be needed, and how much capital may be required to withstand severe events.

This hackathon places you inside that process. Team A focuses on urban, surface-water flooding, while Team B focuses on riverine flooding in the Nzoia Basin. In both challenges, you will work through the same basic chain: **Hazard → Vulnerability → Exposure → Financial engine → Loss curve.**

The supplied data provides a starting point, but your task is to use AI or machine learning in a meaningful way that changes the model's output. AI could, for example, improve how hazards are interpreted, estimate vulnerability, identify patterns in exposure, or improve the way losses are simulated. The goal is not simply to add an AI component, but to demonstrate how it improves the catastrophe-modelling process and produces a useful result for an underwriter.

# 1. Introduction

Nairobi's drainage system has not kept up with the city's rapid growth. In a 2026 mapping exercise, the county government identified 37 flood-prone neighbourhoods across the city, from Kiambiu and Dandora in the east to Kileleshwa and Westlands in the west.

Flooding is Kenya's most frequent and most damaging natural peril. Even so, flood risk in Kenya is still largely priced and managed using underwriter judgement and broad global hazard layers rather than a systematic local model.

Global catastrophe-model vendors offer this type of modelling pipeline, but their models are calibrated using proprietary claims data that is not available here.

Your task is to build a working version of that pipeline using only open data and synthetic exposure data. The pipeline should cover hazard, vulnerability, exposure, and financial loss. You must also use AI to improve at least one part of the process in a way that would not be possible with a purely deterministic approach.

## Problem description

A flood catastrophe model normally needs four things:

**Hazard:** Where does flooding happen, and how severe is it?

**Vulnerability:** How much damage does a property suffer at a given flood severity?

**Exposure:** What buildings or assets are in the affected area, and what are they worth?

**Financial engine:** How do we turn the hazard, vulnerability, and exposure information into losses that a risk manager can use?

# 2. Objectives

1. Build an end-to-end flood loss pipeline:

   Ingest hazard data →
   Apply vulnerability functions to estimate damage →
   Assess losses for each property →
   Aggregate property losses by return period →
   Financial engine → Calculate the insured/reinsured financial loss and produce the loss/return-period curve.

2. Use AI in a way that materially enhances the result, rather than simply adding an AI-generated description. Examples include turning unstructured text into structured exposure data, drafting a risk briefing from model output, or helping improve the hazard layer.

3. Produce a return-period loss curve, also called an exceedance probability (EP) curve. This shows the loss associated with different levels of flood rarity and should be understandable to someone who is not a catastrophe modeller.

4. Clearly state every assumption and every use of the provided synthetic data. Do not present placeholder numbers as real observations.

5. Present the results through an interface that any of the stakeholders below could open and understand.

# 3. Stakeholders

Design the output for these readers, not for another engineer:

**Underwriters & risk analysts:** They want a defensible loss estimate and a return period they can use for budgeting, quickly.

**Portfolio / exposure managers:** They care about accumulation, meaning how much insured value is concentrated in the areas most likely to be affected.

**Hackathon judges:** They will assess the modelling approach, genuine use of AI, and how honestly you explain the model's limitations.

**County & disaster-management bodies:** They could benefit from this type of tool if it were eventually made available for public use.

**Cedants & brokers:** A cedant is the insurer that transfers risk to a reinsurer. They and their brokers could eventually benefit from faster and more consistent flood risk quotes.

# 4. Current State

There is currently no locally calibrated flood catastrophe model for Kenyan risks in-house.

Flood exposure is currently assessed using underwriter judgement and broad global hazard references. There is no systematic decision-support tool that produces losses by return period.

There is also no public dataset that directly measures pluvial flood hazard anywhere in Nairobi. Pluvial flooding means surface-water flooding caused when rainfall exceeds the capacity of the ground and drainage system to absorb or carry the water away.

# 5. Desired State

A winning submission should demonstrate a working prototype that:

Ingests a hazard dataset.

Applies a documented and sourced vulnerability/depth-damage function. If no Kenya-specific curve exists, adapt an existing curve transparently.

Runs a synthetic exposure portfolio through the model and produces a loss figure and a return-period curve.

Uses AI somewhere in the process in a way that actually changes the output, rather than simply describing the result.

Makes it clear within the interface which information comes from real data and which information is an assumption.

# 6. Constraints & Assumptions

**CONSTRAINTS**

3-day build window.

No verified, Kenya-specific depth-damage or vulnerability curves exist publicly. Only global or regional curves are available.

**ASSUMPTIONS & WHERE SYNTHETIC DATA IS EXPECTED**

Exposure portfolios must be synthetic. No real client portfolio will be provided. Use the provided synthetic set, or generate/extend your own. Clearly label it as synthetic in your output.

Vulnerability parameters may be adapted rather than copied exactly from a published curve, such as the JRC/Huizinga depth-damage functions. State your source and explain where your parameters differ from the source.

The hazard layer is a proxy, it is not measured flood data. It is built using real terrain elevation and real river-channel data, but it has not been calibrated as a hydrological model. The starter kit's proxy correctly flags 12 of the 24 real named flood hotspots.

A single representative event may be used instead of a full stochastic catalogue. For example, you may treat the most severe hazard tier as a notional "design flood." A stochastic catalogue is a collection of many simulated flood events used to represent the range of possible future events.

# 7. Scope

## In scope

Hazard ingestion from a real, cited dataset, or a documented proxy where no suitable dataset exists.

A documented vulnerability/depth-damage function.

A synthetic exposure portfolio.

A loss engine that produces at least one single-scenario loss and a return-period (EP) curve.

One AI-powered stage that materially changes the output.

A results interface that a non-modeler can understand.

## Out of scope

Reinsurance treaty structuring, layers, or net-of-reinsurance loss.

Any real policy, claims, or portfolio integration.

Multi-peril aggregation across perils or regions.

Full physically based pluvial hydrology. This is acceptable as a stretch attempt only. It is not expected.

# 8. Input Data

You have been given a starter kit rather than just a list of links. This is because there is no ready-made flood hazard dataset for Nairobi. Everything below is in the data/team_a_nairobi/ folder.

## Hazard proxy (provided, ready to use)

| File | What it is |
|---|---|
| nairobi_pluvial_proxy_{common,occasional,moderate,severe,extreme}.tif | Five severity-tiered rasters. Each cell has a score from 0–1 showing relative flood susceptibility. The proxy uses three real signals: basin-scale terrain elevation (45%), local terrain depressions (20%), slope/flatness (15%), and distance to real OpenStreetMap river/stream data (20%). This is not measured flood depth. It is a constructed proxy. |
| nairobi_hotspots_geocoded.csv | 24 of Nairobi's 37 government-named flood-prone neighbourhoods, geocoded to real coordinates. These locations were used to validate the proxy above. The proxy correctly flags 12 of the 24. The 12 misses, including Kibera, Westlands, Lavington, and others, flood because of drainage-system issues that this proxy cannot detect. This is a real and explainable limitation, and an opportunity to improve the model. |
| exposure_nairobi_with_hazard.csv | Recommended starting file. It contains 600 synthetic building locations with hazard scores for all five tiers already attached as columns. No raster lookup is needed. |
| exposure_nairobi_synthetic.csv | The same 600 synthetic locations without the pre-attached hazard scores. Use this if you want to build your own hazard-lookup step or generate a different portfolio. |

## Background & context (external links)

| Dataset | What it is | Link |
|---|---|---|
| Nairobi's 37 flood hotspots | Government mapping exercise, March 2026, providing background on the hotspot list | [the-star.co.ke, 2026-03-15](https://www.the-star.co.ke) |
| Diagnostic of Urban Flooding in Nairobi | 2024 report covering drainage capacity and flood mechanisms | [kenyaclimatedirectory.org](https://kenyaclimatedirectory.org) |
| JRC / Huizinga et al. depth-damage functions | Published global flood depth-damage curves to use as a reference for your vulnerability function | [publications.jrc.ec.europa.eu](https://publications.jrc.ec.europa.eu) |
| 2026 Kenya floods | Background on Kenya's real March 2026 flood event | [en.wikipedia.org](https://en.wikipedia.org) |

# 9. How to Build the Model

Every catastrophe model, from a simple hackathon prototype to the models sold by RMS or Verisk, follows the same basic four-stage pipeline:

**Hazard → Vulnerability → Exposure → Financial engine**

The hazard tells you where flooding occurs and how severe it is. Vulnerability tells you how much damage that severity causes. Exposure tells you what is actually there and what it is worth. The financial engine turns all of this into a loss number and a return-period curve.

The steps below show how to build each part for Team A.

## Step 1: Hazard

You have two ways to start.

**Option 1: Start with the prepared exposure file.** Use exposure_nairobi_with_hazard.csv. Every building already has a hazard score attached for all five severity tiers. This means you can move directly to Step 2 without doing a raster lookup.

**Option 2: Work from the raw proxy yourself.** Use the raw proxy rasters and the exposure file if you want to build your own exposure set or try to improve the hazard layer.

Note that for Nairobi dataset, severity of flooding has been given as a score between 0 – 1. Not flood depth in meters.

Whichever option you choose, you need to decide how the 0–1 susceptibility score represents real-world flood severity. You will need this when you build your vulnerability function in Step 2.

There is no single correct answer. What matters is that your approach is defensible and that you clearly explain what you assumed.

1. You could use them as they are and explain severity as a value between 0-1 with 1 being very severe
2. Convert the severity score to meters. (e.g Assume 1[extreme flooding] is a flood depth, say 4m, then compute flood depth for all locations. Flood depth at a particular location becomes severity_score * 4m .

**What you should end up with:** A flood severity dataset which shows hazard value at each of the five severity tiers, together with a clear explanation of what those values mean.

## Step 2: Vulnerability

Now turn flood severity into building damage.

You do not need to download another dataset for this step. You need to define a damage function that answers a simple question: given this level of flood severity, what percentage of the building's value is damaged?

**Please note that damage function and vulnerability function refer to the same thing and may be used interchangeably in this document.**

Real flood models commonly use a depth-damage curve. This is a function that shows how the percentage of damage increases as flood depth or severity increases.

The general shape is:

Damage is close to zero at low severity.

Damage increases quickly through the middle range.

Damage eventually approaches a ceiling.

A building will rarely lose 100% of its value even in a severe flood, because the land and foundation will usually remain. Even in a severe flood, losses are typically capped at around 80–95% of value.

The curve should also reflect construction type. For example, an informal iron-sheet structure may suffer serious damage at a relatively low severity, while a concrete/RCC building can withstand more flooding before reaching a similar damage level.

Use the JRC's published global flood depth-damage functions, linked in the Input Data section, as your reference. You could also use AI to come up with code for a damage function for flood hazards.

Clearly state how your damage function works and any assumptions you made.

You also have one important decision to make. Your hazard dataset gives you a relative score of how severe flooding could be in a particular location, it does not give flood depth in metres. You therefore need to decide how that score maps to damage. (Check how this can be approached in step 1.)

Build damage tiers directly from the five severity categories instead of creating a continuous curve.

**What you should end up with:** a documented vulnerability function and vulnerability matrix that takes your hazard severity and returns a damage ratio for each building or construction type.

*[Figure 1 in original document]*

## Step 3: Exposure

Use the provided synthetic portfolio and damage matrix from the previous step to estimate financial loss per building along different time periods.

If your AI feature involves taking free-text descriptions of a portfolio and turning them into structured exposure data, use this file as the reference for the structure your AI output should produce.

**What you should end up with:** a structured portfolio containing the buildings/assets you want to model, their characteristics, their values, and the information needed to connect them to the hazard and vulnerability stages.

*[Figure 2 in original document]*

## Step 4: Financial engine

Now turn each building's hazard and vulnerability information into a financial loss. For each building:

1. Look up its hazard severity at each return period or hazard tier.
2. Pass that severity through your vulnerability function.
3. Get the resulting damage ratio.
4. Multiply the damage ratio by the building's insured value. This gives you the loss for that building under that scenario.
5. Repeat this for every building.
6. Add all building losses together to get the portfolio loss for that scenario.

Then repeat this across your return periods or hazard tiers. This gives you a curve showing the relationship between loss and rarity.

This is called an exceedance probability (EP) curve. It shows how much loss can be expected at different probabilities of being exceeded in a given year. It is one of the most important outputs of a catastrophe model because it answers questions such as: What loss should I budget for at the 1-in-100-year level? What about the 1-in-250-year level?

Your five severity tiers do not have explicit "years" attached to them in the way a return-period dataset would. You therefore need to decide what return period each tier could reasonably represent and clearly state that assumption.

**What you should end up with:** a portfolio loss for each scenario and a return-period/EP curve that shows how losses change as the event becomes rarer.

## Step 5: AI intelligence layer (required)

This is the required differentiator. Choose at least one of the options below, or propose your own approach. The important requirement is that the AI must materially change the output. It should not simply write a description of a result that your model has already produced.

Possible approaches include:

**Free-text exposure ingestion:** A team member describes a portfolio in plain English. An LLM turns that description into structured rows that match the shape of the exposure file and outputs the damage ratio and expected financial losses along different return periods.

**Natural-language risk briefing:** Give the model output, including statistics, the EP curve, and the largest losses, to an LLM. Have it produce a short plain-English summary that an underwriter could actually read.

**AI-assisted vulnerability research:** Use an LLM to help find, compare, or adapt published depth-damage curve parameters. Show the reasoning behind the adaptation rather than simply pasting in a number.

**Hazard layer improvement:** This is particularly relevant to Team A. Use an LLM to help identify which additional signals could improve the proxy, such as more hotspot names, drainage infrastructure reports, or informal-settlement boundaries. You could also use AI to turn unstructured hazard-related text into structured input for the model.

**What you should end up with:** an AI component that has a clear effect on the model, its inputs, or its final output, with enough evidence to show what the AI actually contributed.

*[Figure 3 in original document]*

## Step 6: Results interface

Build an interface that a non-modeller can open and understand in under two minutes. At minimum, show:

Total exposure.

Loss at key return periods.

The EP curve.

A breakdown by construction/housing class.

The output from your AI feature.

The technology or dashboard framework you use does not matter. What matters is that the result is understandable and honest about what comes from real data and what comes from assumptions.

**What you should end up with:** a working results interface that lets an underwriter, risk analyst, portfolio manager, or judge understand the model's key outputs without having to inspect the code.

# 10. Potential Solutions

**Geospatial:** Use rasterio/GDAL-family tools for hazard raster lookups.

**Vulnerability curves:** Use sigmoid or piecewise depth-damage functions, with parameters set separately for each construction/housing class.

**Exposure synthesis:** Generate your own portfolio or extend the provided one. An LLM can also parse freeform text or OSM tags into structured exposure rows.

**AI layer:** Use an LLM for natural-language exposure ingestion and risk briefings. You could also use a regression model to fit or adjust vulnerability curves if you create a small synthetic claims dataset to train against.

**Financial engine:** Use direct return-period interpolation or a Monte Carlo year-loss simulation. A Monte Carlo simulation generates many possible annual outcomes to estimate the range of losses.

**Interface:** Use any dashboard framework you know well. A working and honest result is more valuable than a polished interface built on a broken pipeline.

# 11. Deliverables & Evaluation

Submit a working, end-to-end demo and a short written note covering:

Your data sources.

Your assumptions.

Your AI feature.

Judging will give more weight to genuine AI integration and modelling rigour than visual polish. See the hackathon's marking rubric for the full breakdown.

Team A has a harder hazard problem. This is taken into account when the rubric is applied. It does not mean the modelling bar is lower.

# 12. Conclusion

This challenge is deliberately limited to what can be demonstrated with open data in three days.

You have been given a validated hazard proxy as a starting point, not as the final answer. The most interesting submissions will be those that go beyond its known limitations, especially the drainage-driven flooding that the current proxy misses.

# Glossary

| Term | Plain-English meaning |
|---|---|
| **Accumulation** | The concentration of many insured assets in the same area or exposed to the same event. A single flood can therefore produce many claims at once. |
| **Broker** | A company or professional that helps arrange insurance or reinsurance between the customer or insurer and the risk-taking company. A reinsurance broker may help a cedant place a risk with reinsurers. |
| **Catastrophe (CAT) model** | A computer model used to estimate the frequency and financial impact of severe events such as floods, earthquakes or storms. It combines hazard, vulnerability, exposure and financial information. |
| **Cedant** | An insurance company that transfers some of its risk to a reinsurer. In this challenge, the cedant is the insurer whose risks are being considered. |
| **Damage ratio** | The estimated proportion of an asset's value that is damaged by a hazard. For example, a damage ratio of 0.30 means the model estimates damage equal to 30% of the relevant asset value. |
| **Depth-damage function (vulnerability curve)** | A relationship that estimates the percentage of damage to an asset for different flood depths. Greater water depth will often correspond to greater damage, although the relationship depends on the asset and assumptions used. |
| **Design flood** | A flood level or event chosen as a reference for planning or engineering purposes, often associated with a particular return period such as 1-in-100-year flooding. |
| **Deterministic** | Based on a specific, fixed scenario rather than a range of randomly generated possibilities. For example, applying one particular flood raster to the exposure is a deterministic scenario. |
| **EP curve (exceedance probability)** | A curve showing the probability that an annual loss will exceed different loss amounts. It helps an underwriter understand the likelihood of both moderate and very large losses. |
| **Exposure** | The assets that could be affected by a hazard, together with information such as their location, type and value. In this challenge, the exposure consists mainly of the supplied synthetic buildings and their insured values. |
| **Financial engine** | The part of a CAT model that converts physical damage into financial loss. It applies asset values and, where relevant, insurance or reinsurance terms to estimate the resulting loss. |
| **GDAL and rasterio** | GDAL is a widely used software library and command-line toolkit for working with geospatial data. Rasterio is a Python library that makes it easier to read, write and process raster datasets such as GeoTIFF files. |
| **Geocoded** | Data that has been assigned a geographic location, usually using coordinates such as latitude and longitude. A geocoded building can therefore be placed on a map. |
| **GeoTIFF** | A common file format for storing geospatial raster data. A GeoTIFF contains both the raster values and information that tells software where the data belongs geographically. |
| **Hazard** | The physical event or condition that can cause damage, such as floodwater. In a CAT model, hazard data describes where the event occurs and how severe it is. |
| **Hotspot** | A location identified as having relatively high hazard or risk compared with surrounding areas. In the Nairobi challenge, hotspots refer to areas identified for the flood analysis and validation. |
| **Hydrological model** | A model used to represent how water moves through or collects within an area, often using rainfall, terrain, rivers and other information. It can help estimate how much water reaches a particular location. |
| **JRC / Huizinga curves** | Flood vulnerability relationships associated with research by the European Commission's Joint Research Centre (JRC) and Huizinga. They are commonly used as reference relationships between flood depth and damage for different types of assets. |
| **Layers** | In insurance and reinsurance, a layer is a defined portion of loss between a lower and upper financial limit. Layers are outside the scope of this challenge. |
| **Monte Carlo simulation** | A method that runs a model many times using different randomly generated inputs or scenarios. It is commonly used to estimate a range of possible outcomes and their probabilities. |
| **OpenStreetMap (OSM)** | An open geographic database containing information about places, roads, buildings and other features contributed by users and organisations around the world. |
| **Peril** | A type of event or hazard that can cause loss or damage, such as flood, earthquake, fire or windstorm. This challenge focuses on flood as the peril. |
| **Pluvial flood** | Flooding caused when rainfall produces more surface water than the ground, drainage system or waterways can carry away. It is often described as surface-water or urban flooding. |
| **Proxy** | A substitute measure used when the exact variable of interest is unavailable. A proxy does not directly measure the real thing, so its limitations and assumptions should be stated clearly. |
| **Raster** | A grid of regularly spaced cells used to represent geographic information. Each raster cell stores a value for a small area on the ground, such as flood depth or susceptibility. |
| **RCC** | In the context of catastrophe modelling, RCC refers to reinforced concrete construction. Construction type matters because different buildings can experience different levels of damage from the same flood conditions. |
| **Return period** | A way of describing how unusual an event or loss is based on its annual probability. For example, a 100-year return period corresponds to an annual exceedance probability of approximately 1%; it does not mean the event occurs exactly once every 100 years. |
| **Riverine (fluvial) flood** | Flooding that occurs when a river or other watercourse exceeds its capacity and water spreads onto surrounding land. Team B focuses on this type of flooding in the Nzoia Basin. |
| **Sigmoid function** | An S-shaped mathematical function that changes gradually between lower and higher values. It can be useful for modelling relationships where the rate of change is not constant. |
| **Stochastic catalogue** | A large collection of simulated events designed to represent the range of events that could occur, including events that have not occurred in the historical record. It can be used to estimate event frequencies and loss probabilities. |
| **Susceptibility score** | A numerical value representing how susceptible a location is to a particular hazard. In Team A, the supplied 0–1 values are a constructed proxy for surface-water flood susceptibility rather than measured flood depths. |
| **Synthetic data** | Data created for modelling or testing rather than directly observed from real-world assets or events. Synthetic data should be clearly identified so that model results are not presented as observations of real insured risks. |
| **Treaty** | A reinsurance arrangement under which a reinsurer agrees in advance to accept a defined class or portfolio of risks from a cedant. Treaty structures are outside the scope of this challenge. |

*Nairobi Urban Flood Challenge · Catastrophe Modelling Hackathon · Team A*

---

**About the objectives.** This is my reading, not part of the document. The five objectives give us our checklist. Each item below needs to be clearly visible in what we submit:

1. **The full pipeline.** Hazard, then vulnerability, then per-property loss, then aggregation by return period, then the financial engine and the EP curve. Every link has to work from start to finish.
2. **AI that changes the numbers.** An AI-written summary of the results is not enough on its own. The strongest fit for Team A is improving the hazard layer: the proxy misses 12 of the 24 named hotspots, including Kibera, Westlands and Lavington, because it can't see drainage problems. The document's conclusion signals that this is what judges want to see.
3. **An EP curve a non-modeller can read.** We also have to state which return period we assign to each of the five tiers, because the data doesn't give them.
4. **Every assumption stated.** That includes how the 0–1 score maps to depth or damage, the vulnerability parameters compared with JRC/Huizinga, the return-period assignments, and labelling the exposure data as synthetic.
5. **A results interface a stakeholder can understand in under two minutes.** At minimum it shows total exposure, losses at key return periods, the EP curve, a breakdown by construction class and the AI output. It also needs to mark clearly what comes from real data and what is assumed.