const { useEffect, useMemo, useRef, useState } = React;

function asNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function isScoreColumn(col) {
  return col && (col.startsWith('norm_') || col.endsWith('_score'));
}

function displayValue(feature, col) {
  const raw = asNumber(feature.properties[col]);
  if (raw === null) return null;
  return isScoreColumn(col) ? raw * 100 : raw;
}

function fmt(value, unit) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'No data';
  if (unit === 'currency') return '$' + Math.round(value).toLocaleString();
  if (unit === 'percent') return value.toFixed(1) + '%';
  if (unit === 'miles') return value.toFixed(1) + ' mi';
  return value.toFixed(1);
}

function interpolate(a, b, t) { return Math.round(a + (b - a) * t); }
function colorFor(value, min, max, higherWorse) {
  if (value === null || !Number.isFinite(value)) return '#d1d5db';
  const t = max === min ? 0.5 : Math.max(0, Math.min(1, (value - min) / (max - min)));
  const x = higherWorse ? t : 1 - t;
  const low = [34, 197, 94], mid = [250, 204, 21], high = [220, 38, 38];
  const left = x < .5 ? low : mid;
  const right = x < .5 ? mid : high;
  const tt = x < .5 ? x * 2 : (x - .5) * 2;
  return `rgb(${interpolate(left[0], right[0], tt)}, ${interpolate(left[1], right[1], tt)}, ${interpolate(left[2], right[2], tt)})`;
}

function prioritySort(layer, mode) {
  if (mode === 'score') return 'lowest';
  return layer.rawDirection === 'higher_worse' ? 'highest' : 'lowest';
}

const INTERSECTION_METRICS = [
  { key: 'income', label: 'Household income', column: 'median_hh_income', unit: 'currency' },
  { key: 'hospital', label: 'Hospital distance', column: 'hospital_distance_mi', unit: 'miles' },
  { key: 'poverty', label: 'Poverty', column: 'pct_poverty', unit: 'percent' },
  { key: 'housing', label: 'Housing cost pressure', column: 'pct_rent_burdened', unit: 'percent' },
  { key: 'uninsured', label: 'Uninsured rate', column: 'pct_uninsured', unit: 'percent' },
  { key: 'internet', label: 'Home internet access', column: 'pct_broadband', unit: 'percent' },
  { key: 'disability', label: 'Disability', column: 'pct_disability', unit: 'percent' },
  { key: 'education', label: 'High school or higher', column: 'pct_hs_or_higher', unit: 'percent' },
  { key: 'snap', label: 'SNAP reliance', column: 'pct_snap', unit: 'percent' },
  { key: 'unemployment', label: 'Unemployment', column: 'unemployment_rate', unit: 'percent' },
  { key: 'eviction', label: 'Eviction pressure', column: 'eviction_risk_score', unit: 'score', scale: 100 },
  { key: 'overall', label: 'Overall opportunity score', column: 'uoi_score', unit: 'score', scale: 100 }
];

function metricByKey(key) {
  return INTERSECTION_METRICS.find(m => m.key === key) || INTERSECTION_METRICS[0];
}

function metricValue(feature, metric) {
  const value = asNumber(feature.properties[metric.column]);
  if (value === null) return null;
  return metric.scale ? value * metric.scale : value;
}

function quantile(values, q) {
  const clean = values.filter(v => Number.isFinite(v)).sort((a, b) => a - b);
  if (!clean.length) return null;
  const pos = (clean.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  if (clean[base + 1] !== undefined) return clean[base] + rest * (clean[base + 1] - clean[base]);
  return clean[base];
}

function conditionMatches(value, condition, threshold) {
  if (value === null || threshold === null) return false;
  return condition === 'bottom' ? value <= threshold : value >= threshold;
}

function conditionText(metric, condition, threshold) {
  const side = condition === 'bottom' ? 'bottom quartile' : 'top quartile';
  const op = condition === 'bottom' ? '<=' : '>=';
  return `${metric.label}: ${side} (${op} ${fmt(threshold, metric.unit)})`;
}

function Main({ tracts, commissionDistricts }) {
  const mapRef = useRef(null);
  const layerRef = useRef(null);
  const districtLayerRef = useRef(null);
  const [appMode, setAppMode] = useState('single');
  const [layerKey, setLayerKey] = useState('overall');
  const [mode, setMode] = useState('score');
  const [showDistricts, setShowDistricts] = useState(false);
  const [metricAKey, setMetricAKey] = useState('income');
  const [conditionA, setConditionA] = useState('bottom');
  const [metricBKey, setMetricBKey] = useState('hospital');
  const [conditionB, setConditionB] = useState('top');
  const layers = window.BERN_LAYERS || [];
  const layer = layers.find(l => l.key === layerKey) || layers[0];
  const effectiveMode = layer.key === 'overall' ? 'score' : mode;
  const column = effectiveMode === 'score' ? layer.scoreCol : layer.rawCol;
  const unit = effectiveMode === 'score' ? 'score' : layer.rawUnit;
  const title = effectiveMode === 'score' ? `${layer.shortLabel} score` : layer.rawLabel;
  const metricA = metricByKey(metricAKey);
  const metricB = metricByKey(metricBKey);

  const rows = useMemo(() => tracts.features.map(f => ({ feature: f, value: displayValue(f, column) })).filter(r => r.value !== null), [tracts, column]);
  const stats = useMemo(() => {
    const values = rows.map(r => r.value).sort((a,b) => a-b);
    const avg = values.reduce((a,b) => a+b, 0) / values.length;
    return { min: values[0], max: values[values.length - 1], avg };
  }, [rows]);

  const intersection = useMemo(() => {
    const valuesA = tracts.features.map(f => metricValue(f, metricA)).filter(v => v !== null);
    const valuesB = tracts.features.map(f => metricValue(f, metricB)).filter(v => v !== null);
    const thresholdA = quantile(valuesA, conditionA === 'bottom' ? 0.25 : 0.75);
    const thresholdB = quantile(valuesB, conditionB === 'bottom' ? 0.25 : 0.75);
    const ranked = tracts.features.map(feature => {
      const a = metricValue(feature, metricA);
      const b = metricValue(feature, metricB);
      const matchA = conditionMatches(a, conditionA, thresholdA);
      const matchB = conditionMatches(b, conditionB, thresholdB);
      const scoreA = valuesA.length ? valuesA.filter(v => conditionA === 'bottom' ? v >= a : v <= a).length / valuesA.length * 100 : 0;
      const scoreB = valuesB.length ? valuesB.filter(v => conditionB === 'bottom' ? v >= b : v <= b).length / valuesB.length * 100 : 0;
      return { feature, a, b, matchA, matchB, priority: (scoreA + scoreB) / 2 };
    });
    return {
      thresholdA,
      thresholdB,
      validCount: tracts.features.filter(f => metricValue(f, metricA) !== null && metricValue(f, metricB) !== null).length,
      matches: ranked.filter(r => r.matchA && r.matchB).sort((a, b) => b.priority - a.priority),
      ranked
    };
  }, [tracts, metricAKey, conditionA, metricBKey, conditionB]);

  useEffect(() => {
    if (!mapRef.current) {
      mapRef.current = L.map('map', { scrollWheelZoom: true });
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
      }).addTo(mapRef.current);
    }
    if (layerRef.current) layerRef.current.remove();
    if (districtLayerRef.current) {
      districtLayerRef.current.remove();
      districtLayerRef.current = null;
    }

    if (appMode === 'intersection') {
      const colors = {
        both: '#be123c',
        a: '#2563eb',
        b: '#f59e0b',
        neither: '#e5e7eb'
      };
      layerRef.current = L.geoJSON(tracts, {
        style: (f) => {
          const a = metricValue(f, metricA);
          const b = metricValue(f, metricB);
          const matchA = conditionMatches(a, conditionA, intersection.thresholdA);
          const matchB = conditionMatches(b, conditionB, intersection.thresholdB);
          const group = matchA && matchB ? 'both' : matchA ? 'a' : matchB ? 'b' : 'neither';
          return { color: '#334155', weight: .7, fillColor: colors[group], fillOpacity: group === 'both' ? .86 : .5 };
        },
        onEachFeature: (f, lyr) => {
          const p = f.properties;
          const a = metricValue(f, metricA);
          const b = metricValue(f, metricB);
          lyr.bindTooltip(`<strong>${p.tract_label || 'Tract ' + p.NAME}</strong><br>${metricA.label}: ${fmt(a, metricA.unit)}<br>${metricB.label}: ${fmt(b, metricB.unit)}`);
        }
      }).addTo(mapRef.current);
      if (showDistricts && commissionDistricts) {
        districtLayerRef.current = L.geoJSON(commissionDistricts, {
          style: () => ({ color: '#111827', weight: 2.2, dashArray: '6 4', fillOpacity: 0 }),
          onEachFeature: (f, lyr) => lyr.bindTooltip(`<strong>${f.properties.DistrictName || 'Commission District ' + f.properties.District}</strong>`)
        }).addTo(mapRef.current);
      }
      mapRef.current.fitBounds(layerRef.current.getBounds(), { padding: [20, 20] });
      return;
    }

    const higherWorse = effectiveMode === 'raw' && layer.rawDirection === 'higher_worse';
    layerRef.current = L.geoJSON(tracts, {
      style: (f) => {
        const v = displayValue(f, column);
        return { color: '#334155', weight: .7, fillColor: colorFor(v, stats.min, stats.max, higherWorse), fillOpacity: v === null ? .25 : .78 };
      },
      onEachFeature: (f, lyr) => {
        const p = f.properties;
        const v = displayValue(f, column);
        lyr.bindTooltip(`<strong>${p.tract_label || 'Tract ' + p.NAME}</strong><br>${title}: ${fmt(v, unit)}`);
      }
    }).addTo(mapRef.current);
    if (showDistricts && commissionDistricts) {
      districtLayerRef.current = L.geoJSON(commissionDistricts, {
        style: () => ({ color: '#111827', weight: 2.2, dashArray: '6 4', fillOpacity: 0 }),
        onEachFeature: (f, lyr) => lyr.bindTooltip(`<strong>${f.properties.DistrictName || 'Commission District ' + f.properties.District}</strong>`)
      }).addTo(mapRef.current);
    }
    mapRef.current.fitBounds(layerRef.current.getBounds(), { padding: [20, 20] });
  }, [tracts, column, effectiveMode, layer.rawDirection, stats.min, stats.max, appMode, metricAKey, conditionA, metricBKey, conditionB, intersection.thresholdA, intersection.thresholdB, showDistricts, commissionDistricts]);

  const sorted = [...rows].sort((a, b) => prioritySort(layer, effectiveMode) === 'lowest' ? a.value - b.value : b.value - a.value).slice(0, 12);
  const topIntersection = intersection.matches.slice(0, 12);

  return <div className="app">
    <aside className="sidebar">
      <h1>Bernalillo County Opportunity Index</h1>
      <p className="subtitle">Static map version. Scores run 0-100; higher scores mean stronger access or lower measured hardship.</p>
      <p className="subtitle credit">Thanks to Luke Hudgins of UT Austin for the hospital distance data!</p>
      <div className="control"><label>View</label><div className="segmented"><button className={appMode === 'single' ? 'active' : ''} onClick={() => setAppMode('single')}>Layer</button><button className={appMode === 'intersection' ? 'active' : ''} onClick={() => setAppMode('intersection')}>Intersection</button></div></div>
      <label className="check-row"><input type="checkbox" checked={showDistricts} onChange={e => setShowDistricts(e.target.checked)} /> County Commission districts</label>

      {appMode === 'single' && <>
        <div className="control"><label>Layer</label><select value={layerKey} onChange={e => { setLayerKey(e.target.value); if (e.target.value === 'overall') setMode('score'); }}>{layers.map(l => <option key={l.key} value={l.key}>{l.label}</option>)}</select></div>
        {layer.key !== 'overall' && <div className="control"><label>Values</label><div className="segmented"><button className={mode === 'score' ? 'active' : ''} onClick={() => setMode('score')}>Score</button><button className={mode === 'raw' ? 'active' : ''} onClick={() => setMode('raw')}>Original</button></div></div>}
        <div className="note"><strong>{effectiveMode === 'score' ? layer.scoreMeaning : layer.rawLabel}</strong><br />{layer.why}</div>
        <div className="metrics"><div className="metric"><span>County average</span><strong>{fmt(stats.avg, unit)}</strong></div><div className="metric"><span>Lowest</span><strong>{fmt(stats.min, unit)}</strong></div><div className="metric"><span>Highest</span><strong>{fmt(stats.max, unit)}</strong></div></div>
      </>}

      {appMode === 'intersection' && <>
        <div className="control"><label>First indicator</label><select value={metricAKey} onChange={e => setMetricAKey(e.target.value)}>{INTERSECTION_METRICS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}</select></div>
        <div className="control compact"><select value={conditionA} onChange={e => setConditionA(e.target.value)}><option value="bottom">Bottom quartile</option><option value="top">Top quartile</option></select></div>
        <div className="control"><label>Second indicator</label><select value={metricBKey} onChange={e => setMetricBKey(e.target.value)}>{INTERSECTION_METRICS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}</select></div>
        <div className="control compact"><select value={conditionB} onChange={e => setConditionB(e.target.value)}><option value="bottom">Bottom quartile</option><option value="top">Top quartile</option></select></div>
        <div className="note"><strong>Intersection View</strong><br />{conditionText(metricA, conditionA, intersection.thresholdA)}<br />{conditionText(metricB, conditionB, intersection.thresholdB)}</div>
        <div className="metrics"><div className="metric"><span>Matched tracts</span><strong>{topIntersection.length ? intersection.matches.length : 0}</strong></div><div className="metric"><span>Share of valid tracts</span><strong>{intersection.validCount ? (intersection.matches.length / intersection.validCount * 100).toFixed(1) + '%' : '0%'}</strong></div></div>
      </>}
    </aside>
    <main className="content">
      <div className="topbar"><strong>{appMode === 'intersection' ? 'Intersection View' : layer.label}</strong><span className="legend">{appMode === 'intersection' ? 'Tracts meeting both selected conditions are red' : title}</span></div>
      <div className="map-wrap"><div id="map"></div><section className="table-panel">
        {appMode === 'single' && <>
          <h2>Priority tracts</h2>
          <table><thead><tr><th>Area</th><th>Tract</th><th>{title}</th></tr></thead><tbody>{sorted.map(({ feature, value }) => <tr key={feature.properties.GEOID}><td>{feature.properties.area_label}</td><td>{feature.properties.NAME}</td><td>{fmt(value, unit)}</td></tr>)}</tbody></table>
        </>}
        {appMode === 'intersection' && <>
          <h2>Tracts meeting both</h2>
          <table><thead><tr><th>Area</th><th>Tract</th><th>{metricA.label}</th><th>{metricB.label}</th></tr></thead><tbody>{topIntersection.map(({ feature, a, b }) => <tr key={feature.properties.GEOID}><td>{feature.properties.area_label}</td><td>{feature.properties.NAME}</td><td>{fmt(a, metricA.unit)}</td><td>{fmt(b, metricB.unit)}</td></tr>)}</tbody></table>
        </>}
      </section></div>
    </main>
  </div>;
}

window.BernAppMain = Main;
