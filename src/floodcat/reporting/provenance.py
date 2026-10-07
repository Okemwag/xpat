def provenance(config):
    return [
        {'component':'exposure','status':'synthetic','note':'Uploaded records are not real client properties'},
        {'component':'baseline_hazard','status':'derived_proxy','note':'Real terrain + OSM inputs, not observed depths'},
        {'component':'vulnerability','status':config.vulnerability_status,'note':config.vulnerability_source},
        {'component':'frequency','status':'assumed_uncalibrated','note':'Metadata reference mapping; not fitted to Nairobi rainfall'},
        {'component':'loss','status':'calculated','note':'TIV × damage ratio; no deductibles, limits or reinsurance terms'},
        {'component':'AI_uplift','status':'assumed_mapping','note':'Learned hotspot probability mapped to severity; not measured flood intensity'},
    ]
