# Labels follow AGENTS.md §5: REAL, PROXY, SYNTHETIC, ASSUMPTION, AI.
def exposure_origin(assets):
    """How many modelled properties are real vs synthetic, and the label(s) to show."""
    real = sum(not a.synthetic for a in assets)
    synthetic = len(assets) - real
    labels = (["REAL"] if real else []) + (["SYNTHETIC"] if synthetic else [])
    return {"real": real, "synthetic": synthetic, "labels": labels or ["SYNTHETIC"]}


def provenance(config, origin=None):
    origin = origin or {"real": 0, "synthetic": 1, "labels": ["SYNTHETIC"]}
    if origin["real"] and origin["synthetic"]:
        note = f"{origin['real']} real and {origin['synthetic']} synthetic properties"
    elif origin["real"]:
        note = "Real exposure supplied by the user (e.g. a broker submission); values as supplied, not verified by Xpat"
    else:
        note = "Synthetic or test properties; not a real portfolio"
    return [
        {
            "component": "exposure",
            "label": "+".join(origin["labels"]),
            "status": "real"
            if origin["real"] and not origin["synthetic"]
            else "synthetic"
            if not origin["real"]
            else "mixed",
            "note": note,
        },
        {
            "component": "baseline_hazard",
            "label": "PROXY",
            "status": "derived_proxy",
            "note": "Real terrain + OSM rivers, not observed depths; blind to drainage",
        },
        {
            "component": "hotspots",
            "label": "REAL",
            "status": "named_locations",
            "note": "Government-named areas; coordinates approximate (OSM Nominatim); validation and tagging only",
        },
        {
            "component": "score_to_depth",
            "label": "ASSUMPTION",
            "status": "assumed",
            "note": f"depth = score × {config.max_depth_m} m",
        },
        {
            "component": "vulnerability_base_curve",
            "label": "REAL",
            "status": "published",
            "note": config.vulnerability_source,
        },
        {
            "component": "vulnerability_class_adjustments",
            "label": "ASSUMPTION",
            "status": config.vulnerability_status,
            "note": "Per-class JRC depth scale and damage cap",
        },
        {
            "component": "frequency",
            "label": "ASSUMPTION",
            "status": "assumed_uncalibrated",
            "note": "Metadata reference tier→return-period mapping; not fitted to Nairobi rainfall",
        },
        {
            "component": "aal",
            "label": "ASSUMPTION",
            "status": "assumed_uncalibrated",
            "note": f"Zero loss at {config.aal_zero_loss_return_period}-yr; {config.aal_tail} beyond rarest tier",
        },
        {
            "component": "loss",
            "label": "ASSUMPTION",
            "status": "calculated",
            "note": "TIV × damage ratio (ground-up loss)",
        },
        {
            "component": "policy_terms",
            "label": "ASSUMPTION",
            "status": "enabled" if config.policy_terms["enabled"] else "off",
            "note": (
                f"Per-property deductible {config.policy_terms['deductible_pct_of_tiv']:.1%} and limit {config.policy_terms['limit_pct_of_tiv']:.0%} of TIV turn the ground-up loss into the gross loss"
                if config.policy_terms["enabled"]
                else "Off: losses are ground-up"
            ),
        },
        {
            "component": "uncertainty_ranges",
            "label": "ASSUMPTION",
            "status": "assumed_uncalibrated",
            "note": f"Monte Carlo on damage ratio only: σ={config.uncertainty['damage_sigma']:g}, ρ={config.uncertainty['correlation']:g}, {config.uncertainty['trials']} trials",
        },
        {
            "component": "drainage_model",
            "label": "AI",
            "status": "off_by_default",
            "note": f"Drainage-failure probability from OSM drains, culverts and buildings; prior weights (ASSUMPTION) or learned from approved independent evidence; "
            f"uplift only above p = {config.drainage_model['probability_threshold']:g}",
        },
        {
            "component": "AI_uplift",
            "label": "AI",
            "status": "assumed_mapping",
            "note": "Off by default; learned hotspot probability mapped to severity, not measured intensity",
        },
    ]
