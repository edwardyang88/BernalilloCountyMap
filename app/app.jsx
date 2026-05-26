const { useEffect, useMemo, useRef, useState } = React;
const H = window.BernHelpers;
const LAYERS = window.BERN_LAYERS;
const META = window.BERN_INTERSECTION_METRICS;

const atlasRampStops = ['#eef4fa', '#d1e1ef', '#a8c4de', '#7aa2c7', '#4e7eab', '#2c5d8c', '#143f6a'];
const atlasRamp = H.makeRamp(atlasRampStops);
const atlasIntersect = { both: '#143f6a', a: '#7aa2c7', b: '#c79b5a', neither: '#e6ecf2' };

function Atlas({ tracts, commissionDistricts }) {
  const districts = commissionDistricts;
  const mapRef = useRef(null);
  const layerRef = useRef(null);
  const districtRef = useRef(null);

  const [appMode, setAppMode] = useState('intersection');
  const [layerKey, setLayerKey] = useState('overall');
  const [mode, setMode] = useState('score');
  const [showDistricts, setShowDistricts] = useState(true);
  const [metricAKey, setMetricAKey] = useState('housing');
  const [conditionA, setConditionA] = useState('top');
  const [metricBKey, setMetricBKey] = useState('uninsured');
  const [conditionB, setConditionB] = useState('top');

  const layer = LAYERS.find(l => l.key === layerKey) || LAYERS[0];
  const effectiveMode = layer.key === 'overall' ? 'score' : mode;
  const column = effectiveMode === 'score' ? layer.scoreCol : layer.rawCol;
  const unit = effectiveMode === 'score' ? 'score' : layer.rawUnit;
  const title = effectiveMode === 'score' ? `${layer.shortLabel} score` : layer.rawLabel;
  const metricA = H.metricByKey(metricAKey);
  const metricB = H.metricByKey(metricBKey);

  const rows = useMemo(() => tracts.features.map(f => ({ feature: f, value: H.displayValue(f, column) })).filter(r => r.value !== null), [tracts, column]);
  const stats = useMemo(() => H.singleLayerStats(rows), [rows]);
  const intersection = useMemo(() => H.intersectionAnalysis(tracts, metricA, conditionA, metricB, conditionB), [tracts, metricAKey, conditionA, metricBKey, conditionB]);

  const topList = useMemo(() => {
    if (appMode === 'intersection') return intersection.matches.slice(0, 14);
    return H.rankedSingleLayer(tracts, column, layer.rawDirection, effectiveMode).slice(0, 14);
  }, [appMode, intersection, tracts, column, layer.rawDirection, effectiveMode]);

  useEffect(() => {
    if (!mapRef.current) {
      mapRef.current = L.map('map', { scrollWheelZoom: true, zoomControl: true, attributionControl: true });
      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png', {
        maxZoom: 19, attribution: '© CARTO · OpenStreetMap', subdomains: 'abcd'
      }).addTo(mapRef.current);
    }
    if (layerRef.current) layerRef.current.remove();
    if (districtRef.current) { districtRef.current.remove(); districtRef.current = null; }

    if (appMode === 'intersection') {
      layerRef.current = L.geoJSON(tracts, {
        style: (f) => {
          const a = H.metricValue(f, metricA);
          const b = H.metricValue(f, metricB);
          const mA = H.conditionMatches(a, conditionA, intersection.thresholdA);
          const mB = H.conditionMatches(b, conditionB, intersection.thresholdB);
          const group = mA && mB ? 'both' : mA ? 'a' : mB ? 'b' : 'neither';
          return { color: '#1c2a3e', weight: 0.4, fillColor: atlasIntersect[group], fillOpacity: group === 'both' ? 0.9 : group === 'neither' ? 0.5 : 0.7 };
        },
        onEachFeature: (f, lyr) => {
          const p = f.properties;
          const a = H.metricValue(f, metricA);
          const b = H.metricValue(f, metricB);
          lyr.bindTooltip(`<strong>${p.tract_label || 'Tract ' + p.NAME}</strong><br>${metricA.label}: ${H.fmt(a, metricA.unit)}<br>${metricB.label}: ${H.fmt(b, metricB.unit)}`);
        }
      }).addTo(mapRef.current);
    } else {
      const higherWorse = effectiveMode === 'raw' && layer.rawDirection === 'higher_worse';
      layerRef.current = L.geoJSON(tracts, {
        style: (f) => {
          const v = H.displayValue(f, column);
          return { color: '#1c2a3e', weight: 0.3, fillColor: atlasRamp(v, stats.min, stats.max, higherWorse, '#e6ecf2'), fillOpacity: v === null ? 0.35 : 0.86 };
        },
        onEachFeature: (f, lyr) => {
          const p = f.properties;
          const v = H.displayValue(f, column);
          lyr.bindTooltip(`<strong>${p.tract_label || 'Tract ' + p.NAME}</strong><br>${title}: ${H.fmt(v, unit)}`);
        }
      }).addTo(mapRef.current);
    }

    if (showDistricts && districts) {
      districtRef.current = L.geoJSON(districts, {
        style: () => ({ color: '#0e1726', weight: 1.4, dashArray: '4 4', fillOpacity: 0, opacity: 0.6 }),
        onEachFeature: (f, lyr) => lyr.bindTooltip(`<strong>${f.properties.DistrictName || 'District ' + f.properties.District}</strong>`)
      }).addTo(mapRef.current);
    }
    mapRef.current.fitBounds(layerRef.current.getBounds(), { padding: [16, 16] });
    setTimeout(() => mapRef.current && mapRef.current.invalidateSize(), 50);
  }, [tracts, districts, column, effectiveMode, layer.rawDirection, stats.min, stats.max, appMode, metricAKey, conditionA, metricBKey, conditionB, intersection.thresholdA, intersection.thresholdB, showDistricts]);

  const maxPriority = topList.length ? Math.max(...topList.map(r => r.priority || 0)) : 1;

  return <div className="atlas-root">
    <header className="atlas-top">
      <div className="wm">
        <span className="mark"></span>
        <div>
          <h1>BERN · Opportunity Index</h1>
          <div className="sub">v1.0 · 176 tracts · ACS 2018–2022</div>
        </div>
      </div>
      <div className="crumbs">
        <span>Bernalillo County</span><span className="sep">/</span>
        <span>Atlases</span><span className="sep">/</span>
        <span className="cur">Opportunity Index</span>
      </div>
      <div className="spacer"></div>
      <span className="chip"><span className="dot"></span>Data current</span>
      <div className="modes">
        <button className={appMode === 'single' ? 'active' : ''} onClick={() => setAppMode('single')}>Indicator</button>
        <button className={appMode === 'intersection' ? 'active' : ''} onClick={() => setAppMode('intersection')}>Intersection</button>
      </div>
    </header>
    <div className="atlas-body">
      <aside className="atlas-left">
        {appMode === 'single' && <>
          <div className="atlas-panel">
            <div className="ph"><span className="label">Indicator</span><span className="meta">{LAYERS.length} available</span></div>
            <div className="atlas-field">
              <span className="flabel">Layer</span>
              <select value={layerKey} onChange={e => { setLayerKey(e.target.value); if (e.target.value === 'overall') setMode('score'); }}>
                {LAYERS.map(l => <option key={l.key} value={l.key}>{l.label}</option>)}
              </select>
            </div>
            {layer.key !== 'overall' && <div className="atlas-field">
              <span className="flabel">Reading</span>
              <div className="seg">
                <button className={mode === 'score' ? 'active' : ''} onClick={() => setMode('score')}>Score</button>
                <button className={mode === 'raw' ? 'active' : ''} onClick={() => setMode('raw')}>Raw</button>
              </div>
            </div>}
          </div>
          <div className="atlas-panel">
            <div className="ph"><span className="label">About this layer</span></div>
            <p className="atlas-prose">{layer.why}</p>
            <p className="atlas-prose strong">{layer.scoreMeaning}</p>
          </div>
          <div className="atlas-panel atlas-panel-bottom">
            <div className="ph"><span className="label">Distribution</span></div>
            <div className="atlas-stats three">
              <div className="atlas-stat"><div className="skey">Min</div><div className="sval">{H.fmt(stats.min, unit)}</div></div>
              <div className="atlas-stat"><div className="skey">Avg</div><div className="sval">{H.fmt(stats.avg, unit)}</div></div>
              <div className="atlas-stat"><div className="skey">Max</div><div className="sval">{H.fmt(stats.max, unit)}</div></div>
            </div>
          </div>
        </>}
        {appMode === 'intersection' && <>
          <div className="atlas-panel">
            <div className="ph"><span className="label">Indicator A</span><span className="meta">condition</span></div>
            <div className="atlas-field">
              <span className="flabel">Metric</span>
              <select value={metricAKey} onChange={e => setMetricAKey(e.target.value)}>
                {META.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
              </select>
            </div>
            <div className="atlas-field">
              <span className="flabel">Threshold</span>
              <div className="seg">
                <button className={conditionA === 'bottom' ? 'active' : ''} onClick={() => setConditionA('bottom')}>Bottom 25%</button>
                <button className={conditionA === 'top' ? 'active' : ''} onClick={() => setConditionA('top')}>Top 25%</button>
              </div>
            </div>
            <div className="atlas-cutoff">cutoff · <span>{H.fmt(intersection.thresholdA, metricA.unit)}</span></div>
          </div>
          <div className="atlas-panel">
            <div className="ph"><span className="label">Indicator B</span><span className="meta">condition</span></div>
            <div className="atlas-field">
              <span className="flabel">Metric</span>
              <select value={metricBKey} onChange={e => setMetricBKey(e.target.value)}>
                {META.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
              </select>
            </div>
            <div className="atlas-field">
              <span className="flabel">Threshold</span>
              <div className="seg">
                <button className={conditionB === 'bottom' ? 'active' : ''} onClick={() => setConditionB('bottom')}>Bottom 25%</button>
                <button className={conditionB === 'top' ? 'active' : ''} onClick={() => setConditionB('top')}>Top 25%</button>
              </div>
            </div>
            <div className="atlas-cutoff">cutoff · <span>{H.fmt(intersection.thresholdB, metricB.unit)}</span></div>
          </div>
          <div className="atlas-panel atlas-panel-bottom">
            <div className="ph"><span className="label">Result</span></div>
            <div className="atlas-stats">
              <div className="atlas-stat"><div className="skey">Matched</div><div className="sval">{intersection.matches.length}</div></div>
              <div className="atlas-stat"><div className="skey">Share</div><div className="sval">{intersection.validCount ? ((intersection.matches.length / intersection.validCount) * 100).toFixed(1) + '%' : '—'}</div></div>
            </div>
          </div>
        </>}
        <div className="atlas-panel atlas-panel-overlay">
          <div className="ph"><span className="label">Overlays</span></div>
          <label className={`toggle ${showDistricts ? 'on' : ''}`} onClick={() => setShowDistricts(!showDistricts)}>
            <span className="sw"></span>
            <span>Commission districts</span>
          </label>
        </div>
      </aside>

      <div className="atlas-map-wrap">
        <div id="map" className="atlas-map"></div>
        <div className="atlas-mapfooter">
          {appMode === 'single' ? <div className="atlas-legend">
            <div className="lt">{title}</div>
            <div className="strip">{atlasRampStops.map((c, i) => <span key={i} style={{ background: c }}></span>)}</div>
            <div className="ticks"><span>{H.fmt(stats.min, unit)}</span><span>{H.fmt(stats.avg, unit)}</span><span>{H.fmt(stats.max, unit)}</span></div>
          </div> : <div className="atlas-legend">
            <div className="lt">Group</div>
            <div className="keys">
              <span className="k"><span className="sw" style={{ background: atlasIntersect.both }}></span>Both</span>
              <span className="k"><span className="sw" style={{ background: atlasIntersect.a }}></span>A only</span>
              <span className="k"><span className="sw" style={{ background: atlasIntersect.b }}></span>B only</span>
              <span className="k"><span className="sw" style={{ background: atlasIntersect.neither }}></span>Neither</span>
            </div>
          </div>}
          <div className="atlas-readout">
            {appMode === 'intersection' ? <>
              <div className="col"><div className="rk">A</div><div className="rt">{metricA.label} · <span className="rd">{conditionA === 'bottom' ? '≤ ' : '≥ '}{H.fmt(intersection.thresholdA, metricA.unit)}</span></div></div>
              <div className="sep"></div>
              <div className="col"><div className="rk">B</div><div className="rt">{metricB.label} · <span className="rd">{conditionB === 'bottom' ? '≤ ' : '≥ '}{H.fmt(intersection.thresholdB, metricB.unit)}</span></div></div>
              <div className="sep"></div>
              <div className="col"><div className="rk">Match</div><div className="rt"><span className="rd">{intersection.matches.length}</span> of {intersection.validCount} tracts</div></div>
            </> : <>
              <div className="col"><div className="rk">Layer</div><div className="rt">{layer.label}</div></div>
              <div className="sep"></div>
              <div className="col"><div className="rk">Reading</div><div className="rt">{effectiveMode === 'score' ? 'Opportunity score (0–100)' : layer.rawLabel}</div></div>
              <div className="sep"></div>
              <div className="col"><div className="rk">County mean</div><div className="rt"><span className="rd">{H.fmt(stats.avg, unit)}</span></div></div>
            </>}
          </div>
        </div>
      </div>

      <aside className="atlas-right">
        <div className="atlas-rh">
          <div className="rk">{appMode === 'intersection' ? 'Matched tracts · priority order' : 'Ranked tracts'}</div>
          <h2>{appMode === 'intersection' ? `${intersection.matches.length} tracts meet both conditions` : `Tracts ranked by ${layer.shortLabel.toLowerCase()}`}</h2>
          <div className="meta"><b>{topList.length}</b> shown · sorted by {appMode === 'intersection' ? 'combined percentile' : 'value'}</div>
        </div>
        <div className="atlas-rlist">
          {topList.map((row, i) => {
            const f = row.feature;
            if (appMode === 'intersection') {
              const aPct = row.priority || 0;
              return <div className="row" key={f.properties.GEOID}>
                <div className="rank">{String(i + 1).padStart(2, '0')}</div>
                <div>
                  <div className="area">{f.properties.area_label}</div>
                  <div className="tract">tract {f.properties.NAME}</div>
                </div>
                <div className="bars">
                  <div className="barwrap"><div className="bar-bg"><div className="bar-fg" style={{ width: `${Math.min(100, (aPct / (maxPriority || 1)) * 100)}%` }}></div></div><div className="bar-val">{H.fmt(row.a, metricA.unit)}</div></div>
                  <div className="barwrap"><div className="bar-bg"><div className="bar-fg b" style={{ width: `${Math.min(100, (aPct / (maxPriority || 1)) * 100)}%` }}></div></div><div className="bar-val">{H.fmt(row.b, metricB.unit)}</div></div>
                </div>
              </div>;
            }
            const pct = stats.max === stats.min ? 0.5 : (row.value - stats.min) / (stats.max - stats.min);
            return <div className="row" key={f.properties.GEOID}>
              <div className="rank">{String(i + 1).padStart(2, '0')}</div>
              <div>
                <div className="area">{f.properties.area_label}</div>
                <div className="tract">tract {f.properties.NAME}</div>
              </div>
              <div>
                <div className="single-val">{H.fmt(row.value, unit)}</div>
                <div className="single-bar"><i style={{ width: `${Math.max(2, pct * 100)}%` }}></i></div>
              </div>
            </div>;
          })}
        </div>
      </aside>
    </div>
  </div>;
}

window.BernAppMain = Atlas;
