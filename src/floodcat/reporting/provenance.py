# Labels follow AGENTS.md §5: REAL, PROXY, SYNTHETIC, ASSUMPTION, AI.
def provenance(config):
    return [
        {'component':'exposure','label':'SYNTHETIC','status':'synthetic','note':'Generated for the hackathon starter kit; not real client properties'},
        {'component':'baseline_hazard','label':'PROXY','status':'derived_proxy','note':'Real terrain + OSM rivers, not observed depths; blind to drainage'},
        {'component':'hotspots','label':'REAL','status':'named_locations','note':'Government-named areas; coordinates approximate (OSM Nominatim); validation and tagging only'},
        {'component':'score_to_depth','label':'ASSUMPTION','status':'assumed','note':f'depth = score × {config.max_depth_m} m'},
        {'component':'vulnerability_base_curve','label':'REAL','status':'published','note':config.vulnerability_source},
        {'component':'vulnerability_class_adjustments','label':'ASSUMPTION','status':config.vulnerability_status,'note':'Per-class JRC depth scale and damage cap'},
        {'component':'frequency','label':'ASSUMPTION','status':'assumed_uncalibrated','note':'Metadata reference tier→return-period mapping; not fitted to Nairobi rainfall'},
        {'component':'aal','label':'ASSUMPTION','status':'assumed_uncalibrated','note':f'Zero loss at {config.aal_zero_loss_return_period}-yr; {config.aal_tail} beyond rarest tier'},
        {'component':'loss','label':'ASSUMPTION','status':'calculated','note':'TIV × damage ratio (gross)'},
        {'component':'policy_terms','label':'ASSUMPTION','status':'enabled' if config.policy_terms['enabled'] else 'off',
         'note':(f"Per-risk deductible {config.policy_terms['deductible_pct_of_tiv']:.1%} and limit {config.policy_terms['limit_pct_of_tiv']:.0%} of TIV; no layers or reinsurance"
                 if config.policy_terms['enabled'] else 'Off: losses are gross')},
        {'component':'uncertainty_ranges','label':'ASSUMPTION','status':'assumed_uncalibrated',
         'note':f"Monte Carlo on damage ratio only: σ={config.uncertainty['damage_sigma']:g}, ρ={config.uncertainty['correlation']:g}, {config.uncertainty['trials']} trials"},
        {'component':'AI_uplift','label':'AI','status':'assumed_mapping','note':'Off by default; learned hotspot probability mapped to severity, not measured intensity'},
    ]
