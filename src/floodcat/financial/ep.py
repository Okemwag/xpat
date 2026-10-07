from ..core.constants import TIERS
from ..core.errors import ModelError
from ..core.numeric import money_string

def ep_curve(totals,config):
    values=[totals[t] for t in TIERS]
    if any(a>b for a,b in zip(values,values[1:])):
        raise ModelError("nonmonotonic_loss", "Loss decreases as assumed return period rises")
    return [dict(tier=t,return_period_years=config.return_periods[t],annual_exceedance_probability=1/config.return_periods[t],
                 loss_kes=money_string(totals[t]),frequency_status='assumed_uncalibrated') for t in TIERS]
