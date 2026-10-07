from decimal import Decimal
from ..core.constants import TIERS
from ..core.errors import ModelError
from ..core.numeric import money_string

def _check_order(totals):
    values=[totals[t] for t in TIERS]
    if any(a>b for a,b in zip(values,values[1:])):
        raise ModelError("nonmonotonic_loss", "Loss decreases as assumed return period rises")

def ep_curve(totals,config,tiv=None):
    _check_order(totals)
    return [dict(tier=t,return_period_years=config.return_periods[t],annual_exceedance_probability=1/config.return_periods[t],
                 loss_kes=money_string(totals[t]),
                 loss_pct_of_tiv=float(totals[t]/tiv*100) if tiv else None,
                 frequency_status='assumed_uncalibrated') for t in TIERS]

def average_annual_loss(totals,config):
    """Trapezoid integral of loss over annual exceedance probability.

    Assumptions (config): loss falls linearly to zero at aal_zero_loss_return_period
    (more frequent events cause no loss) and, for 'hold_rarest', stays at the rarest
    tier's loss for every rarer event. Both are stated choices, not fitted.
    """
    _check_order(totals)
    points=[(Decimal(1)/Decimal(str(config.aal_zero_loss_return_period)),Decimal(0))]
    points+=[(Decimal(1)/Decimal(str(config.return_periods[t])),totals[t]) for t in TIERS]
    body=sum(((p0-p1)*(l0+l1)/2 for (p0,l0),(p1,l1) in zip(points,points[1:])),Decimal(0))
    tail=points[-1][0]*points[-1][1]
    return {'aal_kes':money_string(body+tail),'tail_contribution_kes':money_string(tail),
            'zero_loss_return_period_years':config.aal_zero_loss_return_period,'tail_method':config.aal_tail,
            'status':'assumed_uncalibrated',
            'method':'Trapezoid over annual exceedance probability through the five assumed return-period points'}
