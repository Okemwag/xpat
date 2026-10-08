"""Submission note (problem statement §11): data sources, assumptions and AI feature, with diagrams and charts.

Every figure is computed from the model, configs/default.json and the saved evaluations in outputs/ at build time.
Writes outputs/xpat_submission_report.pdf.

Usage: uv run --extra geo --with reportlab --with matplotlib --with pillow python scripts/build_submission_report.py
(run scripts/demo_ai_effect.py first so outputs/ai_effect.json exists)
"""

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from build_vulnerability_explainer import (  # noqa: E402  (shared styles, charts and helpers)
    ACCENT, CLASS_COLOR, CLASS_LABEL, INK, MUTED, fig_classes, png, styles, table,
)
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer  # noqa: E402
from floodcat.core.constants import TIERS  # noqa: E402
from floodcat.financial.ylt import ylt_for_report  # noqa: E402
from floodcat.hazard.hotspots import hotspot_check  # noqa: E402
from floodcat.services.runtime import Runtime  # noqa: E402

OUT = ROOT / "outputs" / "xpat_submission_report.pdf"
LABEL_COLOR = {"REAL": "#1baf7a", "PROXY": "#8e6bbf", "SYNTHETIC": "#7f8c8d", "ASSUMPTION": "#eda100", "AI": "#eb6834"}


def footer(canvas, doc):
    from reportlab.lib import colors

    canvas.saveState()
    canvas.setFont("DejaVu", 7.5)
    canvas.setFillColor(colors.HexColor(MUTED))
    canvas.drawString(1.8 * cm, 1.1 * cm, "Xpat · Nairobi urban flood model · submission note (Team A)")
    canvas.drawRightString(A4[0] - 1.8 * cm, 1.1 * cm, f"Page {doc.page}")
    canvas.restoreState()


def kes(v):
    v = Decimal(str(v))
    if abs(v) >= 10**9:
        return f"KES {v / 10**9:,.2f} bn"
    return f"KES {v / 10**6:,.1f} m" if abs(v) >= 10**6 else f"KES {v / 10**3:,.0f} k"


def load(name):
    p = ROOT / "outputs" / name
    return json.loads(p.read_text()) if p.exists() else None


# Diagram helpers ------------------------------------------------------------------------------------------------
def box(ax, x, y, w, h, title, sub="", label=None, fc="#f4f7fb", ec=ACCENT, title_size=8.4):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06", fc=fc, ec=ec, lw=1.2))
    ax.text(x + w / 2, y + h * (0.64 if sub else 0.5), title, ha="center", va="center", fontsize=title_size,
            weight="bold", color=INK)
    if sub:
        ax.text(x + w / 2, y + h * 0.3, sub, ha="center", va="center", fontsize=6.8, color=MUTED)
    if label:
        ax.text(x + w - 0.04, y + h + 0.02, label, ha="right", va="bottom", fontsize=5.8, color="white", weight="bold",
                bbox=dict(boxstyle="round,pad=0.18", fc=LABEL_COLOR.get(label, "#7f8c8d"), ec="none"))


def arrow(ax, a, b, color=ACCENT, style="-|>", ls="-", lw=1.3, rad=0.0):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle=style, mutation_scale=11, color=color, lw=lw, linestyle=ls,
                                 connectionstyle=f"arc3,rad={rad}"))


def canvas(w, h, xlim, ylim):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.axis("off")
    return fig, ax


def diagram_pipeline():
    """Inputs → four model stages → financial engine → outputs, with where the AI enters."""
    fig, ax = canvas(10, 5.2, (0, 10), (0, 5.4))
    inputs = [("Hazard maps", "5 GeoTIFF tiers, 0–1 score", "PROXY", 4.2), ("Exposure", "CSV, Excel, PDF, Word, text", "SYNTHETIC", 3.1),
              ("JRC depth-damage", "Huizinga et al. 2017", "REAL", 2.0), ("Assumptions", "configs/default.json", "ASSUMPTION", 0.9)]
    for t, s, lab, y in inputs:
        box(ax, 0.1, y, 1.9, 0.75, t, s, lab, fc="#ffffff")
    stages = [("1 · Hazard", "score at each property\n→ assumed depth", 2.5), ("2 · Vulnerability", "depth → damage ratio\nper class, capped", 4.15),
              ("3 · Exposure", "value × damage ratio\n× exposed share", 5.8), ("4 · Financial", "per scenario, AAL,\n10,000 simulated yrs", 7.45)]
    for t, s, x in stages:
        box(ax, x, 2.45, 1.45, 1.0, t, s)
    for (_, _, x1), (_, _, x2) in zip(stages, stages[1:]):
        arrow(ax, (x1 + 1.45, 2.95), (x2, 2.95))
    arrow(ax, (2.0, 4.55), (2.5, 3.3), rad=-0.2)
    arrow(ax, (2.0, 3.45), (5.8, 3.2), rad=-0.15, color="#9aa4ae")
    arrow(ax, (2.0, 2.35), (4.15, 2.75), rad=0.15, color="#9aa4ae")
    arrow(ax, (2.0, 1.25), (7.45, 2.5), rad=0.2, color="#9aa4ae")
    box(ax, 9.0, 3.55, 0.95, 0.75, "EP curve", "1–10,000 yr", fc="#eef6ee", ec="#1baf7a")
    box(ax, 9.0, 2.6, 0.95, 0.75, "Who pays", "ground-up · gross\n· net loss", fc="#eef6ee", ec="#1baf7a")
    box(ax, 9.0, 1.65, 0.95, 0.75, "Where", "class · area\nproperty AAL", fc="#eef6ee", ec="#1baf7a")
    for y in (3.92, 2.97, 2.02):
        arrow(ax, (8.9, 2.95), (9.0, y), color="#1baf7a")
    ai = [("Free-text & documents", "→ property rows", 5.8, 4.3), ("Flood reports & evidence", "→ hazard uplift", 2.5, 4.3),
          ("Briefing · assistant", "→ checked figures", 7.45, 0.45)]
    for t, s, x, y in ai:
        box(ax, x - 0.15, y, 1.75, 0.65, t, s, "AI", fc="#fff4ee", ec="#eb6834", title_size=7.6)
    arrow(ax, (6.62, 4.3), (6.52, 3.45), color="#eb6834", ls="--")
    arrow(ax, (3.32, 4.3), (3.22, 3.45), color="#eb6834", ls="--")
    arrow(ax, (8.27, 2.45), (8.27, 1.1), color="#eb6834", ls="--")
    ax.text(9.95, 0.15, "Every number carries a label: REAL · PROXY · SYNTHETIC · ASSUMPTION · AI", ha="right", fontsize=7.4, color=MUTED)
    return fig


def diagram_platform():
    fig, ax = canvas(10, 3.4, (0, 10), (0, 3.6))
    box(ax, 0.1, 1.35, 1.6, 0.9, "Browser", "underwriters, judges,\ncounty teams")
    box(ax, 2.3, 2.2, 2.3, 1.0, "Interface (Streamlit)", "dashboards, upload, review,\nreports · port 8501")
    box(ax, 2.3, 0.4, 2.3, 1.0, "Sign-in & API (FastAPI)", "accounts, sessions, roles,\n/v1 endpoints · port 8000")
    box(ax, 5.3, 1.35, 2.2, 0.9, "Model runtime", "hazard, vulnerability,\nfinancial engine (in-process)")
    box(ax, 5.3, 2.7, 2.2, 0.75, "Organisation data", "PostgreSQL · audit log", fc="#ffffff")
    box(ax, 5.3, 0.1, 2.2, 0.75, "Starter kit & outputs", "rasters, OSM layers", fc="#ffffff")
    box(ax, 8.1, 2.2, 1.8, 0.9, "Gemini (cloud)", "consent each time;\ncontacts removed", "AI", fc="#fff4ee", ec="#eb6834")
    box(ax, 8.1, 0.95, 1.8, 0.9, "Ollama & local\nembeddings", "nothing leaves\nthe server", "AI", fc="#fff4ee", ec="#eb6834")
    for a, b in (((1.7, 1.95), (2.3, 2.6)), ((1.7, 1.65), (2.3, 1.0)), ((4.6, 2.7), (5.3, 1.95)), ((4.6, 2.9), (5.3, 3.05)),
                 ((4.6, 0.9), (5.3, 3.0)), ((6.4, 1.35), (6.4, 0.85)), ((7.5, 1.9), (8.1, 2.6)), ((7.5, 1.7), (8.1, 1.4))):
        arrow(ax, a, b)
    return fig


def diagram_tiers(cfg, flagged):
    """Nested footprints: the narrowest tier is the most frequent event, the widest the rarest."""
    fig, ax = canvas(10, 3.2, (0, 10), (0, 3.4))
    colors = ["#1f4e79", "#2a78d6", "#6aa6e8", "#a9cdf3", "#dbeafb"]
    for i, t in enumerate(reversed(TIERS)):
        k = len(TIERS) - 1 - i
        w, h = 1.2 + 0.85 * k, 0.55 + 0.5 * k
        ax.add_patch(Rectangle((2.6 - w / 2, 1.6 - h / 2), w, h, fc=colors[k], ec="white", lw=1.5))
    for k, t in enumerate(TIERS):
        ax.text(2.6, 1.6 + (0.25 + 0.25 * k) - 0.05 if k else 1.6, f"{t}", ha="center", va="center", fontsize=7,
                color="white" if k < 2 else INK)
    ax.text(2.6, 0.1, "Each tier contains the one inside it", ha="center", fontsize=7.5, color=MUTED)
    rows = [("Tier", "Map flagged", "Assumed event", "Reading")] + [
        (t, f"{flagged[t]:.0%}", f"1-in-{cfg.return_periods[t]:g}", "most frequent" if t == TIERS[0] else "rarest" if t == TIERS[-1] else "")
        for t in TIERS]
    for i, r in enumerate(rows):
        y = 3.0 - i * 0.48
        for j, (x, v) in enumerate(zip((4.95, 6.05, 7.25, 8.75), r)):
            ax.text(x, y, v, fontsize=8, ha="left", weight="bold" if i == 0 else "normal", color=INK)
    ax.text(5.4, 0.1, "Tier names describe how extreme a map cell is, not how often it floods.", fontsize=7.5, color=MUTED)
    return fig


def diagram_ai_loop():
    fig, ax = canvas(10, 3.6, (0, 10), (0, 3.8))
    steps = [("Reports", "ReliefWeb · uploads\n· GDELT news"), ("Redact & chunk", "e-mails, phones\nremoved; sentences"),
             ("Local embeddings", "BGE-small, on\nthis server"), ("Drainage score", "vs river / other\ndescriptions"),
             ("Place & factor", "OSM names;\nnoisy-OR over reports")]
    for i, (t, s) in enumerate(steps):
        box(ax, 0.1 + i * 1.98, 2.4, 1.7, 1.0, t, s, "AI" if i in (2, 3) else None,
            fc="#fff4ee" if i in (2, 3) else "#f4f7fb", ec="#eb6834" if i in (2, 3) else ACCENT)
        if i:
            arrow(ax, (0.1 + (i - 1) * 1.98 + 1.7, 2.9), (0.1 + i * 1.98, 2.9))
    lower = [("Named reviewer", "approves each place\n(maker–checker)"), ("Hazard uplift", "s′ = 1 − (1−s)(1−w·f·signal)\nwithin 1 km"),
             ("Enhanced run", "beside the unchanged\nbaseline"), ("Evidence of effect", "loss before/after ·\nhotspot hit rate")]
    for i, (t, s) in enumerate(lower):
        box(ax, 8.02 - i * 2.42, 0.4, 1.95, 1.0, t, s, fc="#eef6ee" if i == 3 else "#f4f7fb",
            ec="#1baf7a" if i == 3 else ACCENT)
        if i:
            arrow(ax, (8.02 - (i - 1) * 2.42, 0.9), (8.02 - i * 2.42 + 1.95, 0.9))
    arrow(ax, (8.97, 2.4), (8.97, 1.4))
    ax.text(5.0, 3.62, "Nothing changes a loss until a person approves it; AI output is checked by fixed rules first.",
            ha="center", fontsize=7.6, color=MUTED)
    return fig


# Charts ---------------------------------------------------------------------------------------------------------
def chart_ep(base, ylt, cfg):
    y = ylt["baseline"]["gross"]
    fig, ax = plt.subplots(figsize=(6.6, 3.2))
    rp = [p["return_period_years"] for p in y["curve"]]
    ax.fill_between(rp, [float(p["band_low_kes"]) / 1e9 for p in y["curve"]], [float(p["band_high_kes"]) / 1e9 for p in y["curve"]],
                    color="#9aa4ae", alpha=0.3, lw=0, label="5–95% of re-sampled years")
    ax.plot(rp, [float(p["loss_kes"]) / 1e9 for p in y["curve"]], color=ACCENT, lw=2, label="ground-up loss, 10,000 simulated years")
    for key, color, name in (("insured", "#1baf7a", "gross loss"), ("net", "#eb6834", "net loss")):
        if key in ylt["baseline"]:
            c = ylt["baseline"][key]["curve"]
            ax.plot([p["return_period_years"] for p in c], [float(p["loss_kes"]) / 1e9 for p in c], color=color, lw=1.3, ls="--", label=name)
    ax.scatter([p["return_period_years"] for p in base["ep_curve"]], [float(p["loss_kes"]) / 1e9 for p in base["ep_curve"]],
               marker="D", color=INK, zorder=4, s=22, label="five hazard scenarios (ground-up)")
    rarest = max(cfg.return_periods.values())
    ax.axvline(rarest, color=MUTED, ls=":", lw=1)
    ax.text(rarest * 1.1, ax.get_ylim()[1] * 0.08, "beyond: damage\nuncertainty only", fontsize=7, color=MUTED)
    ax.set_xscale("log")
    ax.set_xlim(1, 10000)
    ax.set_xticks([1, 10, 100, 1000, 10000], ["1", "10", "100", "1,000", "10,000"])
    ax.set_xlabel("Return period (years, log scale)")
    ax.set_ylabel("Portfolio loss (KES bn)")
    ax.grid(alpha=0.25)
    ax.legend(frameon=False, fontsize=7, loc="upper left")
    ax.set_title("Loss against rarity (EP curve)", loc="left")
    return fig


def chart_who_pays(base, tier="occasional"):
    """Waterfall for one scenario: ground-up → deductible → above the limit → gross → quota share → catastrophe XL → net."""
    from floodcat.reporting.terms import waterfall

    steps = waterfall(base, tier)
    fig, ax = plt.subplots(figsize=(6.8, 3.0))
    level = 0.0
    for i, (key, label, amount) in enumerate(steps):
        v = float(amount) / 1e9
        if key in ("ground_up", "gross", "net"):
            ax.bar(i, v, color=ACCENT, width=0.6)
            level, top = v, v
        else:
            ax.bar(i, -v, bottom=level + v, color="#eb6834", width=0.6)
            top = level
            level += v
        ax.text(i, top + 0.03, f"{abs(v):.2f}", ha="center", fontsize=7.5)
    ax.set_xticks(range(len(steps)), [s[1].replace("Catastrophe excess of loss", "Cat. excess\nof loss").replace(" loss", "\nloss")
                                      .replace("Above the limit", "Above\nthe limit") for s in steps], fontsize=7)
    ax.set_ylabel("KES bn")
    ax.grid(axis="y", alpha=0.25)
    ax.set_title("From ground-up to net loss, 1-in-100 flood", loc="left")
    return fig


def chart_portfolio(base):
    cons = {c["id"]: c for c in base["breakdowns"][TIERS[-1]]["construction"]}
    order = list(CLASS_LABEL)
    tiv = [float(cons[c]["tiv_kes"]) / 1e9 if c in cons else 0 for c in order]
    loss = [cons[c]["loss_share_pct"] if c in cons else 0 for c in order]
    total = sum(tiv) or 1
    fig, ax = plt.subplots(figsize=(6.6, 2.4))
    y = range(len(order))
    ax.barh([i + 0.2 for i in y], [t / total * 100 for t in tiv], height=0.38, color="#c9d6e3", label="share of insured value")
    ax.barh([i - 0.2 for i in y], loss, height=0.38, color=[CLASS_COLOR[c] for c in order], label="share of 1-in-250 loss")
    ax.set_yticks(list(y), [CLASS_LABEL[c] for c in order])
    ax.invert_yaxis()
    ax.set_xlabel("%")
    ax.legend(frameon=False, fontsize=7.2, loc="lower right")
    ax.set_title("Value, not fragility, drives the loss", loc="left")
    return fig


def chart_ai_effect(b, cfg):
    fig, ax = plt.subplots(figsize=(6.6, 2.6))
    labels = [f"1-in-{cfg.return_periods[t]:g}" for t in TIERS]
    before = [float(b["before"]["loss_kes"][t]) / 1e9 for t in TIERS]
    after = [float(b["after"]["loss_kes"][t]) / 1e9 for t in TIERS]
    x = range(len(labels))
    ax.bar([i - 0.18 for i in x], before, width=0.36, color=ACCENT, label="without evidence")
    ax.bar([i + 0.18 for i in x], after, width=0.36, color="#eb6834", label="with AI-read evidence (simulated approval)")
    ax.set_xticks(list(x), labels)
    ax.set_ylabel("KES bn")
    ax.legend(frameon=False, fontsize=7.2, loc="upper left")
    ax.grid(axis="y", alpha=0.25)
    ax.set_title("AI-read drainage evidence changes the loss", loc="left")
    return fig


# Document -------------------------------------------------------------------------------------------------------
def build():
    rt = Runtime()
    cfg = rt.config
    rows = rt.sample_rows()
    report = rt.run(rows)
    base = report["runs"]["baseline"]
    ylt = ylt_for_report(report, rows, cfg)
    check = hotspot_check(rt.hotspots, rt.hazard)
    import numpy as np

    flagged = {}
    for t in TIERS:
        a = rt.hazard.grids[t][0]
        flagged[t] = float(((np.ma.getdata(a) > 0) & ~np.ma.getmaskarray(a)).sum() / (~np.ma.getmaskarray(a)).sum())
    ai_effect, ingest_eval, drain_eval, imd_eval = load("ai_effect.json"), load("ingestion_eval.json"), load("drainage_eval.json"), load("imd_evaluation.json")
    curve = {p["return_period_years"]: p for p in base["ep_curve"]}
    st = styles()
    st["h1"].keepWithNext = 1  # a heading never ends a page on its own
    S = []
    P = lambda text, s="body": S.append(Paragraph(text, st[s]))  # noqa: E731

    def H(text):
        S.append(Paragraph(text, st["h1"]))

    def fig(f, width, caption):
        image = png(f, width)
        image.keepWithNext = 1  # the caption stays with its figure
        S.append(image)
        S.append(Paragraph(caption, st["cap"]))

    # Cover
    S.append(Paragraph("Xpat — Nairobi urban flood model", st["title"]))
    S.append(Paragraph("Submission note, Team A: data sources, assumptions and the AI feature, with how each part of the brief is met. "
                       f"Generated {date.today().isoformat()} from the model itself (config {cfg.version}, fingerprint "
                       f"{cfg.fingerprint[:12]}).", st["sub"]))
    S.append(table([
        ["Measure (synthetic starter portfolio)", "Value"],
        ["Properties · insured value", f"{report['modelled_count']} · {kes(report['modelled_tiv_kes'])} (SYNTHETIC)"],
        ["1-in-100 ground-up loss (scenario)", f"{kes(curve[100.0]['loss_kes'])} ({curve[100.0]['loss_pct_of_tiv']:.2f}% of value)"],
        ["1-in-250 ground-up loss (scenario)", f"{kes(curve[250.0]['loss_kes'])} ({curve[250.0]['loss_pct_of_tiv']:.2f}% of value)"],
        ["Average annual loss: ground-up · gross · reinsurance recoveries · net",
         f"{kes(base['aal']['aal_kes'])} · {kes(base['insured']['aal']['aal_kes'])} · {kes(base['reinsurance']['ceded']['aal']['aal_kes'])} · "
         f"{kes(base['reinsurance']['net']['aal']['aal_kes'])}"],
        ["Named flood areas flagged by the hazard proxy", f"{check['flagged_any_tier']} of {check['hotspot_count']} (the brief's known limit)"],
        ["AI free-text ingestion, held-out cases fully correct",
         f"{ingest_eval['summary']['cases_fully_correct']} of {ingest_eval['summary']['cases']}" if ingest_eval else "not run"],
    ], [8.6, 8.8], st))
    S.append(Spacer(1, 8))
    H("1. How it works")
    fig(diagram_pipeline(), 17.4, "Diagram 1. The four-stage pipeline the brief prescribes (hazard → vulnerability → exposure → financial "
        "engine), its inputs with their labels, and where the AI enters (orange, dashed).")
    fig(diagram_platform(), 17.4, "Diagram 2. The running system: a web interface and a sign-in/API server over one in-process model; "
        "organisation data and the audit log in PostgreSQL; AI through Gemini (with consent) or models on the server.")

    # Data sources
    H("2. Data sources")
    S.append(table([
        ["Data", "Use", "Label"],
        ["Five pluvial proxy rasters (starter kit): terrain elevation, depressions, slope (Copernicus GLO-30) and distance to OSM rivers", "Hazard score at each property, per tier", "PROXY"],
        ["24 geocoded government-named flood hotspots (county list, March 2026; OSM Nominatim)", "Validation and accumulation tags only, never exposure or training", "REAL (names), approximate points"],
        ["600-building starter portfolio (starter kit)", "Exposure for every published figure", "SYNTHETIC"],
        ["Huizinga, de Moel & Szewczyk (2017), JRC105688, Table 3-1, Africa residential", "Base depth-damage curve", "REAL"],
        ["OpenStreetMap (Geofabrik Kenya extract, Oct 2026; ODbL): buildings, places, drains", "Drainage model layers, place names in reports, infrastructure check", "REAL / PROXY"],
        ["Flood reports: ReliefWeb (public), uploads, GDELT news", "Drainage evidence after human review", "AI-read, reviewed"],
        ["Uploads by users: schedules and broker documents", "Exposure when real data is used", "REAL or SYNTHETIC, declared"],
    ], [8.2, 6.4, 2.8], st))

    # Hazard and vulnerability
    H("3. Hazard: five tiers and what they mean")
    fig(diagram_tiers(cfg, flagged), 17.4, "Diagram 3. The five tiers are nested threshold cuts of one susceptibility surface. A frequent flood "
        "reaches only the most susceptible cells (extreme, 5%); a rare one reaches the widest area (common, 40%). Return periods are ASSUMED.")
    P(f"<b>Score to depth (ASSUMPTION).</b> The score is relative susceptibility, not depth. We use depth = score × {cfg.max_depth_m:g} m — "
      "a Team A judgement of street and household flood depth, not a cited figure, and the largest single lever on every loss "
      "(4 m multiplies losses by about 2.4). The brief's 4 m example is kept as a sensitivity case.")
    H("4. Vulnerability: a sourced curve, adapted transparently")
    fig(fig_classes(cfg), 13.5, "Figure 1. Damage against hazard score per construction class: the JRC Africa residential curve read at "
        "depth ÷ class scale (0.5 / 0.75 / 1.0 / 1.3), capped at 95 / 90 / 85 / 80%. Diamonds: the brief's reference dashboard.")
    damage = {c: {t: [] for t in TIERS} for c in CLASS_LABEL}
    for t in TIERS:
        for r in base["property_losses"][t]:
            if r["hazard_score"] > 0:
                damage[r["housing_class"]][t].append(r["damage_ratio"])
    S.append(table([["Mean damage ratio of flagged properties"] + [f"{t} (1-in-{cfg.return_periods[t]:g})" for t in TIERS]] + [
        [CLASS_LABEL[c]] + [f"{sum(v) / len(v):.1%}" if v else "—" for v in (damage[c][t] for t in TIERS)] for c in CLASS_LABEL
    ], [4.6] + [2.56] * 5, st))
    P("The damage tiers by severity category that §9 Step 2 asks for: the average damage ratio of the properties each tier flags, "
      "by class, from the same curves. The full vulnerability matrix (class × score) is on the Assumptions page.", "small")

    # Results
    H("5. Exposure and the financial engine")
    fig(chart_portfolio(base), 14.5, "Figure 2. Reinforced concrete holds most of the insured value and most of the loss, even though "
        "informal iron-sheet housing is the most fragile class.")
    fig(chart_ep(base, ylt, cfg), 14.5, "Figure 3. The loss/return-period (EP) curve: five scenario points and 10,000 simulated years with "
        "their re-sampling band; gross-loss and net-loss curves dashed. Beyond 1-in-250 no rarer flood is modelled.")
    fig(chart_who_pays(base), 14.5, "Figure 4. The 1-in-100 flood from ground-up to net loss: owners bear the deductible (1%) and anything "
        "above the limit; the quota share (30%) and the catastrophe excess of loss reduce the gross loss to the net loss. "
        "Terms and programme are illustrative ASSUMPTIONS.")
    from floodcat.reporting.terms import TERMS, waterfall

    S.append(table([["Term", "Meaning"]] + [[n, d] for _, n, d in TERMS], [4.2, 13.2], st))
    S.append(Spacer(1, 6))
    S.append(table([["Return period", "Ground-up", "Deductible", "Gross loss", "Quota share", "Cat. XL", "Net loss"]] + [
        [f"1-in-{p['return_period_years']:g}"] + [kes(abs(v)) for k, _, v in waterfall(base, p["tier"]) if k != "limit"]
        for p in base["ep_curve"]
    ] + [["Average annual loss", kes(base["aal"]["aal_kes"]), "", kes(base["insured"]["aal"]["aal_kes"]), "", "",
          kes(base["reinsurance"]["net"]["aal"]["aal_kes"])]],
        [3.0, 2.45, 2.3, 2.45, 2.4, 2.3, 2.5], st))

    # AI
    H("6. The AI feature, and evidence that it changes the output")
    P("The brief asks for AI that <b>materially changes</b> the result, with evidence of what it contributed. Two routes do, and both are "
      "measured below; a third (the briefing and assistant) explains results with every figure checked against the model.")
    if ai_effect and ai_effect.get("free_text_ingestion"):
        a = ai_effect["free_text_ingestion"]
        P(f"<b>A · Free-text and document ingestion.</b> A plain-English description or a broker document becomes validated property rows "
          f"(same schema as a CSV), so the AI decides what is modelled. Held-out example: “{a['description']}” → {a['model']} produced "
          f"{a['rows']} rows (" + "; ".join(f"{g['count']} × {g['housing_class']} in {g['location_name']}" for g in a["groups"]) +
          f"), every quote verified in the text; modelled 1-in-250 loss {kes(a['result']['loss_kes']['common'])}. "
          + (f"On the 12 held-out cases: {ingest_eval['summary']['cases_fully_correct']} fully correct." if ingest_eval else ""))
    P("<b>Reading a whole submission.</b> The same single AI call also reads the document as a whole, and fixed rules then: "
      "(1) <b>locate data points across the text</b> — sums insured, premium, shares, deductions, period, parties, deductibles, "
      "extensions — each kept only if its quote and number are found word-for-word; (2) <b>separate relevant from irrelevant</b> "
      "clauses, with a reason (a bush-fire clause is set aside; a debris-removal extension is kept because it adds to a loss); "
      "(3) <b>cross-reference the building with risk indicators</b> — construction against the damage curve, occupancy against "
      "the residential curve, the location against the hazard map and the named flood areas; (4) <b>summarise flood history</b> as "
      "a dated timeline, or say there is none and what to ask the broker; (5) <b>calculate implied metrics</b> — premium rate and "
      "per mille, premium after deductions, share arithmetic checks, and modelled loss against premium once the model has run. "
      "The premium and share then pre-fill the underwriting decision.")
    fig(diagram_ai_loop(), 17.4, "Diagram 4. The drainage-evidence loop: flood reports are read on the server by a local embedding model; "
        "places get a drainage-deficit factor; a named reviewer approves; approved evidence raises hazard nearby.")
    if ai_effect:
        b = ai_effect["flood_reports"]
        P(f"<b>B · Flood reports → drainage evidence.</b> Three DEMONSTRATION reports (SYNTHETIC, approval simulated) about places away from "
          f"the named hotspots: the local model found " + ", ".join(f"{p['place']} ({p['factor']:.2f})" for p in b["places"]) +
          f". Applied to the starter portfolio, {b['changed_properties']} properties' hazard rose and the average annual loss moved from "
          f"{kes(b['before']['aal_kes'])} to {kes(b['after']['aal_kes'])}.")
        fig(chart_ai_effect(b, cfg), 14.0, "Figure 5. Portfolio loss per scenario without and with the AI-read evidence. A higher loss is "
            "not proof of a better model; the named-hotspot hit rate (independent evidence only) is the check.")
    rows_ = [["AI check", "Result", "What it shows"]]
    if ingest_eval:
        rows_.append(["Free-text ingestion, 12 held-out descriptions", f"{ingest_eval['summary']['cases_fully_correct']}/12 fully correct",
                      "Extraction of class, count, value, place; quotes verified"])
    if drain_eval:
        t = drain_eval["splits"]["test"]
        rows_.append(["Drainage-passage scoring, held-out passages", f"precision {t['precision']:.0%}, recall {t['recall']:.0%}",
                      "Separates drainage failure from river overflow (0 rivers flagged)"])
    if imd_eval:
        h = imd_eval["hotspots"]
        rows_.append(["Building-density check vs 24 named areas", f"{h['flagged_terrain_only']} → {h['flagged_with_index']} of 24",
                      "What density alone explains; 3 marginal; weak evidence"])
    S.append(table(rows_, [6.2, 4.4, 6.8], st))
    P("Safeguards: AI output is untrusted data and is re-validated by fixed rules; it never sets a depth, damage ratio or loss directly; "
      "contact details are removed before any AI call and users consent before text goes to Gemini; nothing reaches losses until a "
      "named reviewer approves.", "small")

    # Interface and assumptions
    H("7. The interface")
    S.append(table([
        ["Stakeholder", "Where to look", "What they see first"],
        ["Underwriters & risk analysts", "Overview · Loss curve · Underwriting decision", "Loss at 1-in-10…10,000, AAL, who pays, accept / share / decline advice"],
        ["Portfolio & exposure managers", "Accumulation map · Property explorer", "Value and loss by area and property, each property's AAL"],
        ["Judges", "Data & honesty · Methods · Assumptions", "Real vs assumed, the 12/24 check, every assumption editable"],
        ["County & disaster bodies", "Public risk notes · Hazard checks", "Plain English and Kiswahili notes, drainage and satellite checks"],
        ["Cedants & brokers", "Portfolio upload", "CSV, Excel, PDF, Word or a description → results in one flow"],
    ], [4.2, 5.4, 7.8], st))
    P("The minimum the brief asks for is on the first screen: total exposure, losses at key return periods, the EP curve, the breakdown "
      "by construction class and the AI output. Every chart carries what it shows, how to read it and where it comes from, with labels.", "small")
    H("8. Main assumptions")
    S.append(table([
        ["Assumption", "Value", "Basis"],
        ["Tier → return period", " / ".join(f"{cfg.return_periods[t]:g}" for t in TIERS) + " years", "Direction from nested footprints; years assumed"],
        ["Score → depth", f"score × {cfg.max_depth_m:g} m", "Team judgement; biggest lever"],
        ["Class depth scales · caps", "0.5 / 0.75 / 1.0 / 1.3 · 95 / 90 / 85 / 80%", "Construction reasoning · brief's 80–95% guidance"],
        ["Deductible · limit", f"{cfg.policy_terms['deductible_pct_of_tiv']:.0%} · {cfg.policy_terms['limit_pct_of_tiv']:.0%} of value per property", "Illustrative policy terms"],
        ["Quota share · catastrophe XL", f"{cfg.reinsurance['quota_share_cession']:.0%} · above {cfg.reinsurance['xol_retention_pct_of_tiv']:.0%} up to {cfg.reinsurance['xol_limit_pct_of_tiv']:.0%} of value per catastrophe", "Illustrative programme, not a treaty"],
        ["AAL", "zero below 1-in-2; rarest loss held beyond 1-in-250", "Stated integration choices"],
        ["Uncertainty", "damage σ 0.4, correlation 0.5; 200 bootstraps of 10,000 years", "Judgement; not confidence intervals"],
    ], [4.2, 6.2, 7.0], st))
    P("Full register (A1–A22) in docs/REPORT.md §12; every value lives in configs/default.json and is editable on the Assumptions page.", "small")

    # Compliance
    H("9. The brief, section by section")
    S.append(table([
        ["Brief", "Requirement", "Status", "Where"],
        ["§2.1", "End-to-end pipeline to insured/reinsured loss and EP curve", "Met", "Diagram 1; §5 (ground-up → gross → net); Overview"],
        ["§2.2", "AI that materially enhances the result", "Met", "§6 A and B, measured"],
        ["§2.3", "EP curve readable by a non-modeller", "Met", "Figure 3; tooltips in words"],
        ["§2.4", "Every assumption and synthetic use stated", "Met", "§8; labels on every number; Data & honesty"],
        ["§2.5", "Interface any stakeholder can use", "Met", "§7; one-form sign-up, demo accounts"],
        ["§3", "Designed for the five stakeholder groups", "Met", "§7 table"],
        ["§5", "Ingest hazard; sourced curve; synthetic run → loss and curve; AI; real vs assumed", "Met", "§3–§6"],
        ["§6", "Synthetic exposure labelled; curve source and differences; proxy limits", "Met", "§2–§4; 12/24 stated"],
        ["§7 in scope", "Hazard, vulnerability, exposure, loss engine, one AI stage, interface", "Met", "All sections"],
        ["§7 out of scope", "Treaty structuring, layers, net-of-reinsurance loss", "Exceeded (by choice)",
         "Illustrative quota share + layer for Objective 1's “reinsured” loss; labelled, switchable"],
        ["§9 Steps 1–4", "Severity dataset; matrix and tiers; structured exposure; scenario losses and EP", "Met", "§3–§5"],
        ["§9 Step 5", "AI with evidence of contribution", "Met", "§6; outputs/ai_effect.md"],
        ["§9 Step 6", "Exposure, key losses, EP, class breakdown, AI output on one screen", "Met", "Overview"],
        ["§10", "Raster lookups, per-class curves, Monte Carlo year-loss simulation", "Met", "rasterio lookup; 10,000-year YLT"],
        ["§11", "Working demo and a short note on data, assumptions and AI", "Met", "make app; this note"],
    ], [1.9, 7.0, 2.6, 5.9], st))

    H("10. Limitations")
    for item in [
        "The hazard is a terrain-and-river proxy, not a flood model: it flags 12 of 24 named areas and cannot see drainage on its own.",
        "Return periods and the score-to-depth conversion are assumptions; the curve compares assumed scenarios, not a calibrated forecast.",
        "The damage curve is regional (South Africa, Mozambique) and adapted by judgement; nothing is calibrated to Kenyan claims.",
        "The AI-evidence demonstration uses invented reports with simulated approval; real reports and a real reviewer are needed for a claim of skill.",
        "Policy terms and the reinsurance programme are illustrative; no reinstatements, aggregate covers or second events in a year.",
    ]:
        P(f"• {item}")
    P("Reproduce: make app · make outputs · make eval-ingestion · make eval-drainage · make eval-imd · scripts/demo_ai_effect.py · "
      "scripts/build_submission_report.py. Detail: docs/REPORT.md.", "small")

    doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.8 * cm,
                            title="Xpat — Nairobi urban flood model: submission note", author="Xpat (Team A)",
                            subject="Data sources, assumptions and AI feature")
    doc.build(S, onFirstPage=footer, onLaterPages=footer)
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    build()
