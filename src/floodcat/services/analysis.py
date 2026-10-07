from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from ..core.config import ModelConfig
from ..core.constants import TIERS
from ..core.errors import ModelError
from ..core.numeric import money_string
from ..exposure.validation import validate_rows
from ..hazard.providers import AttachedHazard
from ..hazard.interpretation import validate_scores, enhance
from ..ai.evidence import evidence_signal
from ..financial.loss import property_loss, total_loss
from ..financial.ep import ep_curve
from ..financial.accumulation import group_losses
from ..reporting.provenance import provenance

def analyse(rows,config=None,provider=None,model=None,evidence=(),allow_partial=False):
    config=config or ModelConfig();provider=provider or AttachedHazard()
    evidence=tuple(evidence)
    assets,issues=validate_rows(rows)
    results={'baseline':{t:[] for t in TIERS}}
    if model: results['enhanced']={t:[] for t in TIERS}
    excluded=[];changed=0;hazard_ok=[];prediction_details={}
    for asset in assets:
        try:
            baseline=validate_scores(provider.scores(asset))
            enriched=None
            if model:
                features=dict(asset.features)
                # Evidence signal is always calculated from approved evidence; CSV cannot override it.
                features['evidence_signal']=evidence_signal(asset,evidence,config)
                features['baseline_common']=baseline['common']
                probability=model.predict(features)
                enriched=enhance(baseline,probability,config)
                changed+=any(abs(enriched[t]-baseline[t])>1e-12 for t in TIERS)
                prediction_details[asset.loc_id]={'features':features,'hotspot_susceptibility_probability':probability}
            for tier in TIERS:
                results['baseline'][tier].append(property_loss(asset,baseline[tier],config))
                if model: results['enhanced'][tier].append(property_loss(asset,enriched[tier],config))
            hazard_ok.append(asset)
        except ModelError as exc:
            excluded.append(asset.loc_id)
            issues.append({'loc_id':asset.loc_id,'severity':'error','code':exc.code,'message':str(exc)})
    if any(i['severity']=='error' for i in issues) and not allow_partial:
        raise ModelError('portfolio_review_required','Resolve validation/coverage errors or explicitly allow partial analysis: '+str(issues))
    if not hazard_ok: raise ModelError('no_modelled_assets','No property has complete usable inputs')
    accepted_tiv=sum((a.tiv_kes for a in assets),Decimal(0))
    covered_tiv=sum((a.tiv_kes for a in hazard_ok),Decimal(0))
    runs={}
    for name,scenarios in results.items():
        totals={t:total_loss(r) for t,r in scenarios.items()}
        runs[name]={'ep_curve':ep_curve(totals,config),'property_losses':scenarios,
                    'breakdowns':{t:group_losses(r,config) for t,r in scenarios.items()},
                    'high_risk_tiv_kes':{t:money_string(sum((Decimal(r['tiv_kes']) for r in items if r['hazard_score']>=config.high_risk_threshold),Decimal(0))) for t,items in scenarios.items()}}
    contribution={'enabled':bool(model),'changed_properties':changed,'model_fingerprint':model.fingerprint if model else None,
                  'held_out_evaluation':model.artifact.get('evaluation') if model else None,
                  'loss_delta_kes':{t:money_string(total_loss(results['enhanced'][t])-total_loss(results['baseline'][t])) for t in TIERS} if model else {},
                  'approved_evidence_count':sum(e.approved for e in evidence),'prediction_details':prediction_details,
                  'approved_evidence_snapshot':[e.to_dict() for e in evidence if e.approved],
                  'note':'No enhancement claimed without a trained artifact. Increased loss does not by itself prove improved accuracy.'}
    import hashlib,json
    input_fingerprint=hashlib.sha256(json.dumps(rows,sort_keys=True,default=str).encode()).hexdigest()
    return {'input_fingerprint':input_fingerprint,'hazard_provider':type(provider).__name__,'analysis_id':str(uuid4()),'created_at':datetime.now(timezone.utc).isoformat(),'currency':'KES',
            'input_count':len(rows),'accepted_count':len(assets),'modelled_count':len(hazard_ok),
            'rejected_count':len(rows)-len(assets),'excluded_from_hazard':excluded,
            'accepted_tiv_kes':money_string(accepted_tiv),'modelled_tiv_kes':money_string(covered_tiv),
            'unmodelled_accepted_tiv_kes':money_string(accepted_tiv-covered_tiv),'partial':any(i['severity']=='error' for i in issues),
            'issues':issues,'runs':runs,'ai_contribution':contribution,'config':config.to_dict(),'config_fingerprint':config.fingerprint,
            'provenance':provenance(config),'limitations':['Scenario EP points use assumed frequencies, not a calibrated annual loss distribution.',
            'No AAL, insured-policy loss or net reinsurance loss is claimed.','Default vulnerability values are illustrative; replace with sourced research before submission.']}
