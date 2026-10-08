import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from ..core.config import load_config
from ..core.constants import TIERS
from ..core.errors import ModelError, ReviewRequired
from ..core.numeric import money_string
from ..exposure.validation import validate_rows
from ..hazard.providers import AttachedHazard
from ..hazard.interpretation import validate_scores, enhance
from ..hazard.hotspots import nearest_hotspot
from ..ai.evidence import evidence_signal, usable
from ..ai.evaluation import spread
from ..financial.loss import property_loss, total_loss
from ..financial.ep import ep_curve, average_annual_loss
from ..financial.accumulation import group_losses
from ..reporting.provenance import provenance, exposure_origin

SUPPLIED_SCORE_TOLERANCE = 1e-6

def analyse(rows,config=None,provider=None,evidence=(),allow_partial=False,hotspots=(),ai_adjustment=False,synthetic_only=False,drainage=None):
    """Run the full chain for one portfolio. Pure: no files, network or database.

    ai_adjustment applies approved evidence; drainage (a hazard.drainage.DrainageAdjustment) applies the drainage model.
    Either produces the 'enhanced' run beside the unchanged 'baseline'.
    """
    config=config or load_config();provider=provider or AttachedHazard()
    hotspots=tuple(hotspots);evidence=tuple(evidence)
    applied=usable(evidence,config) if ai_adjustment else []
    adjusting=ai_adjustment or drainage is not None
    assets,issues=validate_rows(rows,synthetic_only)
    results={'baseline':{t:[] for t in TIERS}}
    if adjusting: results['enhanced']={t:[] for t in TIERS}
    drained=0
    excluded=[];hazard_ok=[];changes=[];signals={}
    for asset in assets:
        try:
            scores=provider.scores(asset)
            baseline=validate_scores(scores)
            if not isinstance(provider,AttachedHazard) and len(asset.hazard)==len(TIERS):
                diff=max(abs(asset.hazard[t]-baseline[t]) for t in TIERS)
                if diff>SUPPLIED_SCORE_TOLERANCE:
                    issues.append({'row':None,'loc_id':asset.loc_id,'severity':'warning','code':'supplied_scores_differ',
                                   'message':f'Supplied hazard scores differ from the hazard maps by up to {diff:.3f}; map values used'})
            tag=nearest_hotspot(asset.lat,asset.lon,hotspots,config) if hotspots else None
            if adjusting:
                signal=evidence_signal(asset.lat,asset.lon,applied,config) if ai_adjustment else 0.
                enriched=enhance(baseline,signal,config)
                d_signal=drainage.signal(asset.lat,asset.lon,baseline) if drainage is not None else 0.
                if d_signal>0: enriched=enhance(enriched,d_signal,config,weight=config.drainage_model['weight']); drained+=1
                changed=any(abs(enriched[t]-baseline[t])>1e-12 for t in TIERS)
                changes.append((asset,changed))
                if changed: signals[asset.loc_id]={'evidence_signal':signal,'drainage_signal':d_signal,'baseline':baseline,'adjusted':enriched}
            for tier in TIERS:
                results['baseline'][tier].append(property_loss(asset,baseline[tier],config,tag))
                if adjusting: results['enhanced'][tier].append(property_loss(asset,enriched[tier],config,tag))
            hazard_ok.append(asset)
        except ModelError as exc:
            excluded.append(asset.loc_id)
            issues.append({'row':None,'loc_id':asset.loc_id,'severity':'error','code':exc.code,'message':str(exc)})
    has_errors=any(i['severity']=='error' for i in issues)
    if has_errors and not allow_partial: raise ReviewRequired(issues,len(hazard_ok))
    if not hazard_ok: raise ReviewRequired(issues,0) if has_errors else ModelError('no_modelled_assets','No property has complete usable inputs')
    accepted_tiv=sum((a.tiv_kes for a in assets),Decimal(0))
    covered_tiv=sum((a.tiv_kes for a in hazard_ok),Decimal(0))
    runs={}
    for name,scenarios in results.items():
        totals={t:total_loss(r) for t,r in scenarios.items()}
        runs[name]={'ep_curve':ep_curve(totals,config,covered_tiv),'aal':average_annual_loss(totals,config),'property_losses':scenarios,
                    'breakdowns':{t:group_losses(r,config) for t,r in scenarios.items()}}
        if config.policy_terms['enabled']:
            insured={t:total_loss(r,'insured_loss_kes') for t,r in scenarios.items()}
            runs[name]['insured']={'ep_curve':ep_curve(insured,config,covered_tiv),'aal':average_annual_loss(insured,config),
                                   'terms':dict(config.policy_terms),'note':'Per-risk deductible and limit only; no layers or reinsurance'}
    contribution={'enabled':adjusting,'evidence_enabled':ai_adjustment,'applied_evidence_count':len(applied),
                  'drainage':({**drainage.summary(),'properties_uplifted':drained} if drainage is not None else None),
                  'approved_evidence_count':sum(e.approved for e in evidence),
                  'changed_properties':sum(c for _,c in changes),
                  'spread':spread(changes,hotspots,config) if adjusting and hotspots else None,
                  'property_changes':signals,
                  'approved_evidence_snapshot':[e.to_dict() for e in applied],
                  'note':'Increased loss does not by itself prove improved accuracy; see the hotspot comparison.'}
    if adjusting:
        contribution['loss_delta_kes']={t:money_string(total_loss(results['enhanced'][t])-total_loss(results['baseline'][t])) for t in TIERS}
        contribution['aal_delta_kes']=money_string(Decimal(runs['enhanced']['aal']['aal_kes'])-Decimal(runs['baseline']['aal']['aal_kes']))
    input_fingerprint=hashlib.sha256(json.dumps(rows,sort_keys=True,default=str).encode()).hexdigest()
    return {'input_fingerprint':input_fingerprint,'hazard_provider':type(provider).__name__,'analysis_id':str(uuid4()),
            'created_at':datetime.now(timezone.utc).isoformat(),'currency':'KES',
            'input_count':len(rows),'accepted_count':len(assets),'modelled_count':len(hazard_ok),
            'rejected_count':len(rows)-len(assets),'excluded_from_hazard':excluded,
            'accepted_tiv_kes':money_string(accepted_tiv),'modelled_tiv_kes':money_string(covered_tiv),
            'unmodelled_accepted_tiv_kes':money_string(accepted_tiv-covered_tiv),'partial':has_errors,
            'issues':issues,'runs':runs,'ai_contribution':contribution,'config':config.to_dict(),'config_fingerprint':config.fingerprint,
            'exposure_origin':exposure_origin(hazard_ok),
            'provenance':provenance(config,exposure_origin(hazard_ok)),
            'limitations':['Scenario EP points and AAL use assumed return periods, not a calibrated annual loss distribution.',
            ('Insured loss applies a simple per-property deductible and limit; no layers or reinsurance.' if config.policy_terms['enabled']
             else 'Losses are gross of policy terms; no deductible, limit or reinsurance is applied.'),
            'Depth = score × max_depth_m is an assumption; the score is relative susceptibility, not measured depth.',
            'The JRC Africa residential curve rests on South African and Mozambican functions only; class scales and caps are assumptions.',
            'A zero score means the proxy did not flag the location, not that it cannot flood (drainage-driven flooding is invisible to it).'],
            'hotspot_tagging':{'enabled':bool(hotspots),'hotspot_count':len(hotspots),'radius_m':config.hotspot_tag_radius_m}}
