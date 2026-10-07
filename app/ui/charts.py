"""Charts follow one palette: blue = baseline model, orange = AI-adjusted; classes use slots 1–4 in fixed order."""
from decimal import Decimal
import altair as alt
import pandas as pd
import pydeck as pdk
from floodcat.core.constants import CLASSES
from floodcat.vulnerability.functions import damage_from_depth
from . import state

SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100']
BASE, AI = SERIES[0], SERIES[1]
SEQUENTIAL = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b']

def _bn(value):
    return float(Decimal(value))/1e9

def ep_frame(report, run, name):
    return pd.DataFrame([{'Return period (years)': p['return_period_years'], 'Loss (KES bn)': _bn(p['loss_kes']),
                          'Loss': state.kes(p['loss_kes'], compact=False), 'Annual chance': f"{p['annual_exceedance_probability']:.1%}",
                          '% of insured value': state.pct(p['loss_pct_of_tiv']), 'Tier': p['tier'], 'Series': name}
                         for p in report['runs'][run]['ep_curve']])

def ep_chart(report, compare_ai=False):
    data = ep_frame(report, 'baseline', 'Baseline model')
    domain, colors = ['Baseline model'], [BASE]
    if compare_ai and 'enhanced' in report['runs']:
        data = pd.concat([data, ep_frame(report, 'enhanced', 'With AI drainage evidence')])
        domain.append('With AI drainage evidence'); colors.append(AI)
    ticks = sorted(data['Return period (years)'].unique().tolist())
    x = alt.X('Return period (years):Q', scale=alt.Scale(type='log'),
              axis=alt.Axis(values=ticks, labelExpr="'1-in-' + datum.value", title='Event rarity (assumed return period)', grid=False))
    y = alt.Y('Loss (KES bn):Q', title='Portfolio loss (KES bn)', axis=alt.Axis(gridOpacity=0.4))
    color = alt.Color('Series:N', scale=alt.Scale(domain=domain, range=colors),
                      legend=alt.Legend(orient='top', title=None) if len(domain) > 1 else None)
    tooltip = ['Series', 'Tier', alt.Tooltip('Return period (years):Q', title='Return period (yrs)'), 'Annual chance', 'Loss', '% of insured value']
    base = alt.Chart(data).encode(x=x, y=y, color=color)
    hover = alt.selection_point(fields=['Return period (years)'], nearest=True, on='pointerover', empty=False)
    lines = base.mark_line(strokeWidth=2)
    points = base.mark_point(filled=True, size=70, stroke='white', strokeWidth=2).encode(tooltip=tooltip).add_params(hover)
    rule = alt.Chart(data).mark_rule(color='#9ca3af', strokeWidth=1).encode(x=x).transform_filter(hover)
    return (lines + points + rule).properties(height=340)

def class_bars(items):
    data = pd.DataFrame([{'Class': state.class_label(i['id']), 'Loss (KES m)': float(Decimal(i['loss_kes']))/1e6,
                          'Loss': state.kes(i['loss_kes'], compact=False), 'Insured value': state.kes(i['tiv_kes'], compact=False),
                          'Properties': i['property_count'], 'Share of loss': f"{i['loss_share_pct']:.1f}%"} for i in items])
    bars = alt.Chart(data).mark_bar(color=BASE, cornerRadiusEnd=4, height=22).encode(
        y=alt.Y('Class:N', sort='-x', title=None), x=alt.X('Loss (KES m):Q', title='Loss (KES m)', axis=alt.Axis(gridOpacity=0.4)),
        tooltip=['Class', 'Properties', 'Insured value', 'Loss', 'Share of loss'])
    labels = bars.mark_text(align='left', dx=4, fontSize=12).encode(text='Share of loss:N', color=alt.value('#52514e'))
    return (bars + labels).properties(height=40*len(data)+30)

def vulnerability_chart(cfg, depth_max=None, marks=None):
    depth_max = depth_max or max(3.0, cfg.max_depth_m*1.2)
    steps = [depth_max*i/120 for i in range(121)]
    data = pd.DataFrame([{'Depth (m)': d, 'Damage ratio': damage_from_depth(d, c, cfg), 'Class': state.class_label(c)} for c in CLASSES for d in steps])
    domain = [state.class_label(c) for c in CLASSES]
    chart = alt.Chart(data).mark_line(strokeWidth=2).encode(
        x=alt.X('Depth (m):Q', title='Assumed flood depth (m)', axis=alt.Axis(grid=False)),
        y=alt.Y('Damage ratio:Q', axis=alt.Axis(format='%', gridOpacity=0.4), scale=alt.Scale(domain=[0, 1])),
        color=alt.Color('Class:N', scale=alt.Scale(domain=domain, range=SERIES), legend=alt.Legend(orient='top', title=None)),
        tooltip=['Class', alt.Tooltip('Depth (m):Q', format='.2f'), alt.Tooltip('Damage ratio:Q', format='.1%')])
    layers = [chart]
    cap_rule = alt.Chart(pd.DataFrame({'y': [cfg.max_depth_m]})).mark_rule(strokeDash=[4, 4], color='#9ca3af').encode(x='y:Q')
    layers.append(cap_rule)
    if marks is not None and len(marks):
        layers.append(alt.Chart(marks).mark_point(filled=True, size=90, color=AI, stroke='white', strokeWidth=2).encode(
            x='Depth (m):Q', y='Damage ratio:Q', tooltip=['Return period', alt.Tooltip('Depth (m):Q', format='.2f'), alt.Tooltip('Damage ratio:Q', format='.1%')]))
    return alt.layer(*layers).properties(height=320)

def _ramp(value, top):
    if top <= 0 or value <= 0: return [180, 180, 180, 140]
    idx = min(len(SEQUENTIAL)-1, int(value/top*(len(SEQUENTIAL)-1)+0.5))
    h = SEQUENTIAL[idx].lstrip('#')
    return [int(h[i:i+2], 16) for i in (0, 2, 4)] + [220]

def portfolio_map(rows, hotspots=(), evidence=(), radius_by='tiv'):
    """rows: dicts with lat, lon, loss (float), tiv (float), plus tooltip fields."""
    top = max((r['loss'] for r in rows), default=0)
    tiv_top = max((r['tiv'] for r in rows), default=1) or 1
    data = [{**r, 'color': _ramp(r['loss'], top), 'radius': 60+340*(r['tiv']/tiv_top)**0.5} for r in rows]
    layers = [pdk.Layer('ScatterplotLayer', data=data, get_position='[lon, lat]', get_fill_color='color', get_radius='radius',
                        radius_min_pixels=2, radius_max_pixels=18, pickable=True, stroked=True, get_line_color=[255, 255, 255, 200],
                        line_width_min_pixels=1)]
    if hotspots:
        hs = [{'name': h.name, 'lat': h.lat, 'lon': h.lon, 'tooltip': f'Named flood hotspot: {h.name}'} for h in hotspots]
        layers.append(pdk.Layer('ScatterplotLayer', data=hs, get_position='[lon, lat]', get_radius=140, radius_min_pixels=5,
                                filled=False, stroked=True, get_line_color=[235, 104, 52, 255], line_width_min_pixels=2, pickable=True))
        layers.append(pdk.Layer('TextLayer', data=hs, get_position='[lon, lat]', get_text='name', get_size=12, get_color=[60, 60, 60, 255],
                                get_pixel_offset=[0, -14], background=True, get_background_color=[255, 255, 255, 200]))
    if evidence:
        ev = [{'lat': e.lat, 'lon': e.lon, 'tooltip': f'AI evidence: {e.location_name} ({e.mechanism})'} for e in evidence]
        layers.append(pdk.Layer('ScatterplotLayer', data=ev, get_position='[lon, lat]', get_radius=1000, filled=True,
                                get_fill_color=[74, 58, 167, 40], stroked=True, get_line_color=[74, 58, 167, 200], line_width_min_pixels=1, pickable=True))
    lat = sum(r['lat'] for r in rows)/len(rows) if rows else -1.28
    lon = sum(r['lon'] for r in rows)/len(rows) if rows else 36.82
    return pdk.Deck(layers=layers, initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=10.5),
                    tooltip={'html': '{tooltip}', 'style': {'fontSize': '12px'}}, map_style=None)
