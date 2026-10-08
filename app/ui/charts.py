"""Charts follow one palette: blue = baseline model, orange = AI-adjusted; classes use slots 1–4 in fixed order."""
import html
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

def ep_chart(report, compare_ai=False, run_key='baseline', basis='gross', ranges=None):
    """basis: 'gross' or 'insured'. ranges: uncertainty_ranges() output to draw a shaded likely range."""
    def frame(run, name):
        source = report['runs'][run] if basis == 'gross' else {'ep_curve': report['runs'][run]['insured']['ep_curve']}
        return ep_frame({'runs': {run: source}}, run, name)
    data = frame('baseline', 'Baseline model')
    domain, colors = ['Baseline model'], [BASE]
    if compare_ai and 'enhanced' in report['runs']:
        data = pd.concat([data, frame('enhanced', 'With AI drainage evidence')])
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
    layers = [lines, points, rule]
    if ranges is not None:
        band_rows = []
        for run, name, colour in (('baseline', 'Baseline model', BASE), ('enhanced', 'With AI drainage evidence', AI)):
            if run not in ranges or (run == 'enhanced' and not compare_ai): continue
            sim = ranges[run]['insured' if basis == 'insured' else 'gross']
            low, high = sim['interval_pct']
            band_rows += [{'Return period (years)': s['return_period_years'], 'low': _bn(s['p_low_kes']), 'high': _bn(s['p_high_kes']),
                           'Series': name, 'Likely range': f"{state.kes(s['p_low_kes'])} – {state.kes(s['p_high_kes'])} ({low:g}th–{high:g}th pct)"}
                          for s in sim['by_tier'].values()]
        band = alt.Chart(pd.DataFrame(band_rows)).mark_area(opacity=0.18).encode(
            x=x, y='low:Q', y2='high:Q', color=color, tooltip=['Series', 'Likely range'])
        layers.insert(0, band)
    return alt.layer(*layers).properties(height=340)

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

def portfolio_map(rows, hotspots=(), evidence=(), color_by='loss'):
    """rows: dicts with lat, lon, loss, tiv, score (floats) plus tooltip. color_by: 'loss' or 'score'."""
    key = 'score' if color_by == 'score' else 'loss'
    top = 1.0 if key == 'score' else max((r['loss'] for r in rows), default=0)
    tiv_top = max((r['tiv'] for r in rows), default=1) or 1
    data = [{**r, 'color': _ramp(r[key], top), 'radius': 60+340*(r['tiv']/tiv_top)**0.5} for r in rows]
    layers = [pdk.Layer('ScatterplotLayer', data=data, get_position='[lon, lat]', get_fill_color='color', get_radius='radius',
                        radius_min_pixels=2, radius_max_pixels=18, pickable=True, stroked=True, get_line_color=[255, 255, 255, 200],
                        line_width_min_pixels=1)]
    if hotspots:
        hs = [{'name': h.name, 'lat': h.lat, 'lon': h.lon, 'tooltip': f'Named flood hotspot: {html.escape(h.name)}'} for h in hotspots]
        layers.append(pdk.Layer('ScatterplotLayer', data=hs, get_position='[lon, lat]', get_radius=140, radius_min_pixels=5,
                                filled=False, stroked=True, get_line_color=[235, 104, 52, 255], line_width_min_pixels=2, pickable=True))
        layers.append(pdk.Layer('TextLayer', data=hs, get_position='[lon, lat]', get_text='name', get_size=12, get_color=[60, 60, 60, 255],
                                get_pixel_offset=[0, -14], background=True, get_background_color=[255, 255, 255, 200]))
    if evidence:
        ev = [{'lat': e.lat, 'lon': e.lon, 'tooltip': f'AI evidence: {html.escape(e.location_name)} ({html.escape(e.mechanism)})'} for e in evidence]
        layers.append(pdk.Layer('ScatterplotLayer', data=ev, get_position='[lon, lat]', get_radius=1000, filled=True,
                                get_fill_color=[74, 58, 167, 40], stroked=True, get_line_color=[74, 58, 167, 200], line_width_min_pixels=1, pickable=True))
    lat = sum(r['lat'] for r in rows)/len(rows) if rows else -1.28
    lon = sum(r['lon'] for r in rows)/len(rows) if rows else 36.82
    return pdk.Deck(layers=layers, initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=10.5),
                    tooltip={'html': '{tooltip}', 'style': {'fontSize': '12px'}}, map_style=None)

BAND_GREY = '#9ca3af'

def ylt_chart(curves, report, compare_ai=False, basis='gross'):
    """EP curve from the simulated year-loss table: log return-period axis to 10,000 years, grey bootstrap band,
    and the five scenario points the simulation is built from."""
    series = [('baseline', 'Baseline model', BASE)]
    if compare_ai and 'enhanced' in curves: series.append(('enhanced', 'With AI drainage evidence', AI))
    lines, bands, points = [], [], []
    for run, name, _ in series:
        sim = curves[run]['insured' if basis == 'insured' else 'gross']
        low, high = sim['band_pct']
        for p in sim['curve']:
            rp = p['return_period_years']
            lines.append({'Return period (years)': rp, 'Loss (KES bn)': _bn(p['loss_kes']), 'Series': name,
                          'In words': state.rp_sentence(rp, p['loss_kes']),
                          'Simulation range': f"{state.kes(p['band_low_kes'])} – {state.kes(p['band_high_kes'])} ({low:g}th–{high:g}th pct)",
                          'Annual chance': f'{1/rp:.2%}' if rp < 1000 else f'{1/rp:.3%}'})
            bands.append({'Return period (years)': rp, 'low': _bn(p['band_low_kes']), 'high': _bn(p['band_high_kes']), 'Series': name})
        source = report['runs'][run] if basis == 'gross' else report['runs'][run]['insured']
        for p in source['ep_curve']:
            points.append({'Return period (years)': p['return_period_years'], 'Loss (KES bn)': _bn(p['loss_kes']), 'Series': name,
                           'Scenario': f"{p['tier']} tier (assumed 1-in-{p['return_period_years']:g})",
                           'In words': state.rp_sentence(p['return_period_years'], p['loss_kes'])})
    domain = [s[1] for s in series]; colors = [s[2] for s in series]
    ticks = [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 10000]
    x = alt.X('Return period (years):Q', scale=alt.Scale(type='log', domain=[1, 10000]),
              axis=alt.Axis(values=ticks, labelExpr="'1-in-' + format(datum.value, ',')", title='Return period (log scale)', grid=False))
    y = alt.Y('Loss (KES bn):Q', title='Annual loss (KES bn)', axis=alt.Axis(gridOpacity=0.4))
    color = alt.Color('Series:N', scale=alt.Scale(domain=domain, range=colors), legend=alt.Legend(orient='top', title=None) if len(series) > 1 else None)
    band = alt.Chart(pd.DataFrame(bands)).mark_area(opacity=0.25).encode(
        x=x, y='low:Q', y2='high:Q', color=alt.Color('Series:N', scale=alt.Scale(domain=domain, range=[BAND_GREY]+[AI]*(len(series)-1)), legend=None))
    hover = alt.selection_point(fields=['Return period (years)', 'Series'], nearest=True, on='pointerover', empty=False)
    data = pd.DataFrame(lines)
    line = alt.Chart(data).mark_line(strokeWidth=2).encode(x=x, y=y, color=color)
    hits = alt.Chart(data).mark_point(size=60, opacity=0).encode(x=x, y=y, tooltip=['In words', 'Simulation range', 'Annual chance', 'Series']).add_params(hover)
    dot = alt.Chart(data).mark_point(filled=True, size=70, stroke='white', strokeWidth=2).encode(x=x, y=y, color=color).transform_filter(hover)
    scen = alt.Chart(pd.DataFrame(points)).mark_point(shape='diamond', filled=True, size=80, stroke='white', strokeWidth=1.5).encode(
        x=x, y=y, color=color, tooltip=['Scenario', 'In words'])
    rarest = max(p['Return period (years)'] for p in points)
    edge = alt.Chart(pd.DataFrame({'x': [rarest]})).mark_rule(strokeDash=[4, 4], color=BAND_GREY).encode(x='x:Q')
    return alt.layer(band, edge, line, scen, hits, dot).properties(height=380)

def damage_vs_score_chart(cfg, reference=None):
    """Figure-1 view: damage ratio against the 0–1 hazard score, one curve per class (through depth = score × max depth)."""
    from floodcat.vulnerability.functions import damage_ratio
    scores = [i/100 for i in range(101)]
    domain = [state.class_label(c) for c in CLASSES]
    data = pd.DataFrame([{'Hazard score': s, 'Damage ratio': damage_ratio(s, c, cfg), 'Class': state.class_label(c),
                          'In words': f"{state.class_label(c)} at score {s:.2f} (≈{s*cfg.max_depth_m:.2f} m): "
                                      f"{damage_ratio(s, c, cfg):.0%} of rebuild value damaged"} for c in CLASSES for s in scores])
    color = alt.Color('Class:N', scale=alt.Scale(domain=domain, range=SERIES), legend=alt.Legend(orient='top', title=None))
    x = alt.X('Hazard score:Q', title='Hazard score (0–1)', axis=alt.Axis(grid=False))
    y = alt.Y('Damage ratio:Q', axis=alt.Axis(format='%', gridOpacity=0.4), scale=alt.Scale(domain=[0, 1]))
    hover = alt.selection_point(fields=['Hazard score'], nearest=True, on='pointerover', empty=False)
    layers = [alt.Chart(data).mark_line(strokeWidth=2).encode(x=x, y=y, color=color),
              alt.Chart(data).mark_point(opacity=0, size=40).encode(x=x, y=y, tooltip=['In words']).add_params(hover),
              alt.Chart(data).mark_point(filled=True, size=60, stroke='white').encode(x=x, y=y, color=color).transform_filter(hover)]
    if reference:
        ref = pd.DataFrame([{'Hazard score': 1.0, 'Damage ratio': v, 'Class': state.class_label(c),
                             'In words': f'Reference dashboard (Figure 1) ≈ {v:.0%} at score 1 for {state.class_label(c)}'} for c, v in reference.items()])
        layers.append(alt.Chart(ref).mark_point(shape='cross', size=140, strokeWidth=2).encode(x=x, y=y, color=color, tooltip=['In words']))
    return alt.layer(*layers).properties(height=340)

def hotspot_check_map(points):
    """Named hotspots: filled = flagged by the proxy, hollow = missed. Labels carry the status, not colour alone."""
    data = [{'lat': p['lat'], 'lon': p['lon'], 'name': f"{p['name']} {'✓' if p['flagged_any_tier'] else '✗'}",
             'tooltip': f"<b>{html.escape(p['name'])}</b><br/>{'Flagged' if p['flagged_any_tier'] else 'Missed'} by the proxy<br/>common-tier score {p['common']:.3f}",
             'fill': [42, 120, 214, 230] if p['flagged_any_tier'] else [255, 255, 255, 0]} for p in points]
    layers = [pdk.Layer('ScatterplotLayer', data=data, get_position='[lon, lat]', get_radius=500, radius_min_pixels=6, radius_max_pixels=14,
                        get_fill_color='fill', stroked=True, get_line_color=[42, 120, 214, 255], line_width_min_pixels=2, pickable=True),
              pdk.Layer('TextLayer', data=data, get_position='[lon, lat]', get_text='name', get_size=11, get_color=[40, 40, 40, 255],
                        get_pixel_offset=[0, -16], background=True, get_background_color=[255, 255, 255, 210])]
    return pdk.Deck(layers=layers, initial_view_state=pdk.ViewState(latitude=-1.285, longitude=36.84, zoom=10.3),
                    tooltip={'html': '{tooltip}'}, map_style=None)


def donut(rows, label, value, title=None, colors=None, fmt=None, height=220):
    """Share of a total. rows: list of dicts. Categories keep fixed palette order (largest first)."""
    data = pd.DataFrame(rows)
    if data.empty or data[value].sum() == 0: return None
    domain = list(data[label])
    palette = colors or (SERIES+['#e87ba4', '#008300', '#4a3aa7', '#e34948'])[:len(domain)]
    data['Share'] = data[value]/data[value].sum()
    tooltip = [label, alt.Tooltip('Share:Q', format='.0%')] + ([fmt] if fmt else [])
    base = alt.Chart(data).encode(theta=alt.Theta(f'{value}:Q', stack=True),
                                  color=alt.Color(f'{label}:N', scale=alt.Scale(domain=domain, range=palette), legend=alt.Legend(orient='right', title=None)),
                                  tooltip=tooltip)
    chart = base.mark_arc(innerRadius=55, outerRadius=90, stroke='white', strokeWidth=2)
    return chart.properties(height=height, title=title or '')

def hbars(rows, label, value, value_title, text=None, color=None, height_per=28, sort='-x', fmt=None):
    """Horizontal bars for a ranked list (one series, one colour)."""
    data = pd.DataFrame(rows)
    if data.empty: return None
    bars = alt.Chart(data).mark_bar(color=color or BASE, cornerRadiusEnd=4, height=max(12, height_per-8)).encode(
        y=alt.Y(f'{label}:N', sort=sort, title=None), x=alt.X(f'{value}:Q', title=value_title, axis=alt.Axis(gridOpacity=0.4, format=fmt or '')),
        tooltip=[c for c in data.columns if not c.startswith('_')])
    layers = [bars]
    if text: layers.append(bars.mark_text(align='left', dx=4, fontSize=11).encode(text=f'{text}:N', color=alt.value('#6b6b66')))
    return alt.layer(*layers).properties(height=height_per*len(data)+20)

def columns_chart(rows, x, y, y_title, color=None, height=220, x_title=None, sort=None):
    data = pd.DataFrame(rows)
    if data.empty: return None
    return alt.Chart(data).mark_bar(color=color or BASE, cornerRadiusEnd=4).encode(
        x=alt.X(f'{x}:N', sort=sort, title=x_title, axis=alt.Axis(labelAngle=0)), y=alt.Y(f'{y}:Q', title=y_title, axis=alt.Axis(gridOpacity=0.4)),
        tooltip=list(data.columns)).properties(height=height)

def timeline(rows, x, y, y_title, height=200):
    data = pd.DataFrame(rows)
    if data.empty: return None
    return alt.Chart(data).mark_bar(color=BASE, cornerRadiusEnd=3).encode(
        x=alt.X(f'{x}:T', title=None), y=alt.Y(f'{y}:Q', title=y_title, axis=alt.Axis(gridOpacity=0.4)), tooltip=list(data.columns)).properties(height=height)

def tornado(rows, height_per=30):
    """Sensitivity: change in a measure for each scenario versus the base (negative left, positive right)."""
    data = pd.DataFrame(rows)
    if data.empty: return None
    color = alt.condition(alt.datum.Change > 0, alt.value(SERIES[1]), alt.value(BASE))
    bars = alt.Chart(data).mark_bar(cornerRadius=3, height=max(12, height_per-10)).encode(
        y=alt.Y('Scenario:N', sort=alt.EncodingSortField('Abs', order='descending'), title=None),
        x=alt.X('Change:Q', title='Change in average annual loss vs current (%)', axis=alt.Axis(gridOpacity=0.4)), color=color,
        tooltip=['Scenario', alt.Tooltip('Change:Q', format='+.0f', title='Change (%)'), 'AAL'])
    rule = alt.Chart(pd.DataFrame({'x': [0]})).mark_rule(color='#9ca3af').encode(x='x:Q')
    return alt.layer(bars, rule).properties(height=height_per*len(data)+20)

def scenario_lines(rows, base_name, height=320):
    """Sensitivity: loss against return period, one line per assumption scenario; the current assumptions drawn thicker in blue.
    rows: dicts with Scenario, Return period (years), Loss (KES bn), Loss."""
    data = pd.DataFrame(rows)
    if data.empty: return None
    others = [s for s in dict.fromkeys(data['Scenario']) if s != base_name]
    domain = [base_name] + others
    palette = [BASE] + ['#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#9ca3af'][:len(others)]
    ticks = sorted(data['Return period (years)'].unique().tolist())
    x = alt.X('Return period (years):Q', scale=alt.Scale(type='log'), axis=alt.Axis(values=ticks, labelExpr="'1-in-' + datum.value", title='Assumed return period', grid=False))
    y = alt.Y('Loss (KES bn):Q', title='Portfolio loss (KES bn)', axis=alt.Axis(gridOpacity=0.4))
    color = alt.Color('Scenario:N', scale=alt.Scale(domain=domain, range=palette), legend=alt.Legend(orient='right', title=None, labelLimit=260))
    width = alt.condition(alt.datum.Scenario == base_name, alt.value(3.5), alt.value(1.5))
    lines = alt.Chart(data).mark_line(point=alt.OverlayMarkDef(size=40, filled=True)).encode(x=x, y=y, color=color, strokeWidth=width,
                                                                                               tooltip=['Scenario', alt.Tooltip('Return period (years):Q', title='Return period'), 'Loss'])
    return lines.properties(height=height)
