const { useEffect, useMemo, useRef, useState, useCallback } = React;
const H = window.BernHelpers;
const LAYERS = window.BERN_LAYERS;
const META = window.BERN_INTERSECTION_METRICS;
const CLUSTERS = window.BERN_CLUSTERS;
const PROFILE_KEYS = window.BERN_PROFILE_KEYS;

const REPO_URL = 'https://github.com/edwardyang88/BernalilloCountyMap';
const CSV_URL = 'data/bernalillo_opportunity_index.csv';
// CARTO basemap key (client-side by design; restrict it to this domain in the CARTO dashboard).
const CARTO_KEY = 'cb1_5f3d_1_13c8f8b90363ab05c3448a43';

// Dusk over the Sandias: chalk to deep indigo. Rose marks the selected tract.
const RAMP = ['#f4f2f7', '#ddd8ea', '#bfb5da', '#9a8dc4', '#7465aa', '#52458f', '#322872'];
const ramp = H.makeRamp(RAMP);
const ROSE = '#d6455f';
const OVERLAP = { both: '#322872', a: '#9a8dc4', b: '#e29a6b', neither: '#eceaf0' };
const MISSING = '#c9c7cf';
const fmtDate = iso => new Date(iso + 'T12:00').toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });

// ---------- URL state (shareable links) ----------
function readHash() {
  const out = {};
  window.location.hash.replace(/^#/, '').split('&').filter(Boolean).forEach(kv => {
    const [k, v] = kv.split('=');
    out[decodeURIComponent(k)] = decodeURIComponent(v || '');
  });
  return out;
}
function writeHash(obj) {
  const s = Object.entries(obj).filter(([, v]) => v !== null && v !== undefined && v !== '').map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
  const url = window.location.pathname + window.location.search + (s ? '#' + s : '');
  window.history.replaceState(null, '', url);
}

// ---------- Small pieces ----------
function Segmented({ value, options, onChange, label }) {
  return <div className="seg" role="group" aria-label={label}>
    {options.map(o => <button key={o.value} type="button" aria-pressed={value === o.value} className={value === o.value ? 'on' : ''} onClick={() => onChange(o.value)}>{o.label}</button>)}
  </div>;
}

// Each tick is one tract. The selected tract is the rose dot. Right is always better.
function StripPlot({ values, value, median, higherWorse }) {
  const w = 100, h = 16;
  if (!values.length) return null;
  const min = values[0], max = values[values.length - 1];
  const x = v => {
    const t = max === min ? 0.5 : (v - min) / (max - min);
    return (higherWorse ? 1 - t : t) * w;
  };
  return <div className="strip-wrap" aria-hidden="true">
    <svg className="strip" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <line x1="0" x2={w} y1={h / 2} y2={h / 2} className="strip-axis" />
      {values.map((v, i) => <line key={i} x1={x(v)} x2={x(v)} y1="4" y2={h - 4} className="strip-tick" />)}
      {median !== null && <line x1={x(median)} x2={x(median)} y1="1" y2={h - 1} className="strip-median" />}
    </svg>
    {value !== null && <span className="strip-dot" style={{ left: `${x(value)}%` }}></span>}
  </div>;
}

function TractProfile({ feature, tracts, summary, onClose }) {
  const p = feature.properties;
  const score = H.displayValue(feature, 'uoi_score');
  const cluster = CLUSTERS[p.lisa_cluster] || null;
  const ev = summary && summary.eviction;

  const rows = useMemo(() => PROFILE_KEYS.map(key => {
    const layer = LAYERS.find(l => l.key === key);
    const values = tracts.features.map(f => H.displayValue(f, layer.rawCol)).filter(v => v !== null).sort((a, b) => a - b);
    const value = H.displayValue(feature, layer.rawCol);
    const higherWorse = layer.rawDirection === 'higher_worse';
    const pr = H.percentileRank(values, value);
    const standing = pr === null ? null : (higherWorse ? 1 - pr : pr);
    return { layer, values, value, median: H.quantile(values, 0.5), higherWorse, standing };
  }).sort((a, b) => (a.standing ?? 2) - (b.standing ?? 2)), [feature, tracts]);

  const gaps = rows.filter(r => r.standing !== null && r.standing <= 0.25).map(r => /^[A-Z]+$/.test(r.layer.shortLabel) ? r.layer.shortLabel : r.layer.shortLabel.toLowerCase());

  return <section className="profile" aria-label={`Profile of ${p.area_label}`}>
    <button className="back" type="button" onClick={onClose}>Back to overview</button>
    <h2>{p.area_label}</h2>
    <p className="profile-sub">Census tract {p.NAME}{p.commission_district ? `, County Commission District ${p.commission_district}` : ''}</p>

    <div className="profile-score">
      <div className="big">{H.fmt(score, 'score')}</div>
      <div>
        <div className="big-label">Opportunity score</div>
        <div className="big-rank">{p.uoi_rank ? `${H.ordinal(p.uoi_rank)} of ${tracts.features.length} tracts` : ''}</div>
      </div>
    </div>

    <div className="profile-facts">
      {cluster && <p><span className="swatch" style={{ background: cluster.color }}></span>{cluster.sentence}{p.lisa_p !== null && p.lisa_cluster !== 'none' ? ` (p = ${p.lisa_p.toFixed(3)})` : ''}</p>}
      <p>
        {p.eviction_filing_rate !== null
          ? <><strong>{p.eviction_filings_12mo}</strong> eviction filings in the 12 months to {ev ? new Date(ev.end + 'T12:00').toLocaleDateString('en-US', { month: 'long', year: 'numeric' }) : 'the latest data'}, or <strong>{p.eviction_filing_rate.toFixed(1)}</strong> per 100 renter households{ev ? ` (county: ${ev.county_rate_per_100_renters.toFixed(1)})` : ''}.{p.eviction_vs_baseline ? (p.eviction_vs_baseline >= 1 ? ` Filings are running at ${p.eviction_vs_baseline.toFixed(1)}× the tract’s pre-pandemic level.` : ` Filings are running at ${Math.round(p.eviction_vs_baseline * 100)}% of the tract’s pre-pandemic level.`) : ''}</>
          : <>Too few renter households ({p.renter_households ?? 0}) for a reliable eviction filing rate.</>}
      </p>
      {gaps.length > 0 && <p>In the bottom quarter of the county for {gaps.length === 1 ? gaps[0] : gaps.slice(0, -1).join(', ') + ' and ' + gaps[gaps.length - 1]}.</p>}
    </div>

    <h3>Where it stands on each measure</h3>
    <p className="strip-legend"><span>Each tick is one tract. The dot is this tract, the taller line is the county median.</span><span className="strip-dir"><span>worse</span><span>better</span></span></p>
    <ul className="strips">
      {rows.map(r => <li key={r.layer.key}>
        <div className="strip-head">
          <span className="strip-label">{r.layer.rawLabel}{r.layer.notInScore ? <em> (not in score)</em> : null}</span>
          <span className="strip-val">{H.fmt(r.value, r.layer.rawUnit)}</span>
        </div>
        <StripPlot values={r.values} value={r.value} median={r.median} higherWorse={r.higherWorse} />
      </li>)}
    </ul>
  </section>;
}

function Findings({ summary, onShowLayer, onShowDistrict }) {
  if (!summary) return null;
  const v = summary.validation, c = summary.clusters, ev = summary.eviction;
  const worstDistrict = [...summary.districts].sort((a, b) => b.bottom_quartile_tracts - a.bottom_quartile_tracts)[0];
  const totalBottom = summary.districts.reduce((s, d) => s + d.bottom_quartile_tracts, 0);
  const shareFilings = Math.round(worstDistrict.filings_12mo / ev.county_filings_12mo * 100);
  const areas = c.low_low_top_areas.slice(0, 3);
  return <section className="findings">
    <h2>What the data shows</h2>
    <article>
      <h3>The score lines up with evictions, which it never saw</h3>
      <p>Tracts in the bottom quarter of the index averaged <strong>{v.bottom_quartile_rate.toFixed(1)}</strong> eviction filings per 100 renter households in the past year, <strong>{v.bottom_vs_top_ratio.toFixed(1)}×</strong> the rate in the top quarter. They account for {Math.round(v.bottom_quartile_share_of_filings * 100)}% of the county’s {ev.county_filings_12mo.toLocaleString()} filings.</p>
      <button type="button" className="link" onClick={() => onShowLayer('filings')}>Map eviction filings</button>
    </article>
    <article>
      <h3>Low opportunity is concentrated, not scattered</h3>
      <p>Neighboring tracts score alike far more than chance would produce (Moran’s I = {c.morans_i.toFixed(2)}, p = {c.morans_p.toFixed(3)}). {c.counts.low_low} tracts form significant low-scoring clusters, centered on {areas.slice(0, -1).join(', ')} and {areas[areas.length - 1]}.</p>
      <button type="button" className="link" onClick={() => onShowLayer('clusters')}>Map the clusters</button>
    </article>
    <article>
      <h3>District {worstDistrict.district} carries the heaviest load</h3>
      <p>It holds {worstDistrict.bottom_quartile_tracts} of the county’s {totalBottom} bottom-quarter tracts and {shareFilings}% of all eviction filings, at {worstDistrict.filing_rate.toFixed(1)} per 100 renters against a county rate of {ev.county_rate_per_100_renters.toFixed(1)}.</p>
      <button type="button" className="link" onClick={() => onShowDistrict(worstDistrict.district)}>Outline District {worstDistrict.district}</button>
    </article>
    <p className="hint">Click any tract on the map or in the list to see its full profile.</p>
  </section>;
}

function Methods({ summary, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    ref.current && ref.current.focus();
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  const s = summary;
  const scoreInputs = LAYERS.filter(l => !l.single && !l.notInScore);
  return <div className="drawer-backdrop" onClick={onClose}>
    <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="methods-title" tabIndex="-1" ref={ref} onClick={e => e.stopPropagation()}>
      <button className="drawer-close" type="button" onClick={onClose} aria-label="Close">Close</button>
      <h2 id="methods-title">How this is built</h2>

      <h3>What the score measures</h3>
      <p>The opportunity score averages {scoreInputs.length} measures for each of the county’s {s ? s.tract_count : 176} census tracts, all from the {s ? s.acs_vintage : '2018–2022 ACS 5-year'} estimates except hospital distance:</p>
      <ul className="cols">{scoreInputs.map(l => <li key={l.key}>{l.rawLabel}</li>)}</ul>
      <p>Each measure is rescaled from 0 (worst tract in the county) to 100 (best), flipped where a higher number is worse, then averaged with equal weights. Limited-English households and the estimated eviction risk are mapped for reference but left out of the score.</p>

      <h3>Clusters</h3>
      <p>Tracts that share a border or a corner count as neighbors. Local Moran’s I compares each tract’s score with its neighbors’ average and tests the result against 999 random reshuffles of the map, so a cluster is only shown when it is unlikely to be chance (p &lt; 0.05).{s ? ` Across the whole county, Moran’s I is ${s.clusters.morans_i.toFixed(2)}.` : ''}</p>

      <h3>Eviction filings</h3>
      <p>Weekly filing counts by tract come from the Eviction Lab’s Eviction Tracking System for Albuquerque. The map sums the most recent 52 complete weeks{s ? ` (${fmtDate(s.eviction.start)} to ${fmtDate(s.eviction.end)})` : ''} and divides by renter households from the 2022 ACS. Tracts with fewer than {s ? s.eviction.min_renters_for_rate : 50} renter households are left blank because a handful of cases would swing the rate. {s ? `${s.eviction.sealed_or_unlocated_filings_in_full_series.toLocaleString()} filings in the full series were sealed or could not be placed in a tract.` : ''}</p>

      {s && <>
        <h3>Checking the score</h3>
        <p>Filings are not an input, so they are a fair test. Across tracts, the rank correlation between the score and the filing rate is {s.validation.spearman_index_vs_filing_rate.toFixed(2)}: a moderate link in the expected direction. The narrower eviction-risk estimate, built from four of the same inputs, does about as well ({s.validation.spearman_acs_proxy_vs_filing_rate.toFixed(2)}), which suggests the score’s extra measures describe opportunity broadly rather than eviction risk specifically.</p>
      </>}

      <h3>Limits</h3>
      <ul>
        <li>ACS tract estimates carry wide margins of error, especially for small populations. Treat small differences between tracts as noise.</li>
        <li>Equal weights are a choice, not a finding. Rescaling to the county’s best and worst tract means one extreme tract can compress everyone else’s scores; the map colors by rank to compensate.</li>
        <li>Filings are not completed evictions, and informal evictions never reach court.</li>
        <li>Hospital distances are from 2017 and measure straight-line access, not travel time.</li>
      </ul>

      <h3>Sources</h3>
      <ul>
        <li>U.S. Census Bureau, American Community Survey 5-year estimates, 2018–2022 (tables B28002, S2503, S2701, S1701, S1901, S1810, S1501, S2201, S2301, B08201, C16002), via the Census API.</li>
        <li>U.S. Census Bureau, TIGER/Line tract boundaries, 2022.</li>
        <li>Peter Hepburn, Renee Louis and Matthew Desmond. Eviction Tracking System: Version 2.0. Princeton University, 2020. <a href="https://evictionlab.org" target="_blank" rel="noopener">evictionlab.org</a></li>
        <li>Bernalillo County, County Commission district boundaries.</li>
      </ul>
      <p>Code, pipeline and data: <a href={REPO_URL} target="_blank" rel="noopener">github.com/edwardyang88/BernalilloCountyMap</a>. Built by Edward Yang.</p>
    </aside>
  </div>;
}

// ---------- Main ----------
function Atlas({ tracts, commissionDistricts, summary }) {
  const initial = useMemo(readHash, []);
  const mapRef = useRef(null);
  const layerRef = useRef(null);
  const districtRef = useRef(null);
  const selectedLayerRef = useRef(null);
  const styleRef = useRef(() => ({}));

  const [appMode, setAppMode] = useState(initial.mode === 'overlap' ? 'overlap' : 'single');
  const [layerKey, setLayerKey] = useState(LAYERS.some(l => l.key === initial.layer) ? initial.layer : 'overall');
  const [mode, setMode] = useState(initial.reading === 'raw' ? 'raw' : 'score');
  const [selectedGeoid, setSelectedGeoid] = useState(initial.tract || null);
  const [showDistricts, setShowDistricts] = useState(true);
  const [highlightDistrict, setHighlightDistrict] = useState(null);
  const [sortOrder, setSortOrder] = useState('desc');
  const [query, setQuery] = useState('');
  const [methodsOpen, setMethodsOpen] = useState(false);
  const [metricAKey, setMetricAKey] = useState('filings');
  const [conditionA, setConditionA] = useState('top');
  const [metricBKey, setMetricBKey] = useState('uninsured');
  const [conditionB, setConditionB] = useState('top');

  const layer = LAYERS.find(l => l.key === layerKey) || LAYERS[0];
  const effectiveMode = layer.single ? (layer.key === 'filings' ? 'raw' : 'score') : mode;
  const column = effectiveMode === 'score' ? layer.scoreCol : layer.rawCol;
  const unit = effectiveMode === 'score' ? 'score' : layer.rawUnit;
  const title = layer.single ? (layer.key === 'filings' ? 'Eviction filings per 100 renters' : layer.label) : effectiveMode === 'score' ? `${layer.shortLabel} score` : layer.rawLabel;
  const higherWorse = effectiveMode === 'raw' && layer.rawDirection === 'higher_worse';
  const metricA = H.metricByKey(metricAKey);
  const metricB = H.metricByKey(metricBKey);

  const byGeoid = useMemo(() => Object.fromEntries(tracts.features.map(f => [f.properties.GEOID, f])), [tracts]);
  const selectedFeature = selectedGeoid ? byGeoid[selectedGeoid] : null;

  const rows = useMemo(() => tracts.features.map(f => ({ feature: f, value: H.displayValue(f, column) })).filter(r => r.value !== null), [tracts, column]);
  const stats = useMemo(() => H.singleLayerStats(rows), [rows]);
  const intersection = useMemo(() => H.intersectionAnalysis(tracts, metricA, conditionA, metricB, conditionB), [tracts, metricAKey, conditionA, metricBKey, conditionB]);

  const ranked = useMemo(() => {
    if (appMode === 'overlap') return intersection.matches.map((r, i) => ({ ...r, rank: i + 1 }));
    if (layer.categorical) {
      const order = ['low_low', 'low_high', 'high_low', 'high_high', 'none'];
      return tracts.features
        .filter(f => f.properties.lisa_cluster && f.properties.lisa_cluster !== 'none' && f.properties.lisa_cluster !== 'insufficient')
        .map(f => ({ feature: f, value: H.displayValue(f, 'uoi_score') }))
        .sort((a, b) => order.indexOf(a.feature.properties.lisa_cluster) - order.indexOf(b.feature.properties.lisa_cluster) || a.value - b.value)
        .map((r, i) => ({ ...r, rank: i + 1 }));
    }
    return H.rankedSingleLayer(tracts, column, sortOrder).map((r, i) => ({ ...r, rank: i + 1 }));
  }, [appMode, intersection, tracts, column, sortOrder, layer.categorical]);

  const listRows = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return ranked;
    return ranked.filter(r => (r.feature.properties.area_label || '').toLowerCase().includes(q) || String(r.feature.properties.NAME).includes(q));
  }, [ranked, query]);

  // Keep the URL in sync so any view can be shared as a link.
  useEffect(() => {
    writeHash({ mode: appMode === 'overlap' ? 'overlap' : null, layer: appMode === 'single' && layerKey !== 'overall' ? layerKey : null, reading: appMode === 'single' && !layer.single && mode === 'raw' ? 'raw' : null, tract: selectedGeoid });
  }, [appMode, layerKey, mode, selectedGeoid, layer.single]);

  // ---- style for each tract, kept in a ref so resetStyle uses the latest ----
  styleRef.current = (f) => {
    const base = { color: '#ffffff', weight: 0.5, opacity: 0.9 };
    if (appMode === 'overlap') {
      const a = H.metricValue(f, metricA), b = H.metricValue(f, metricB);
      const mA = H.conditionMatches(a, conditionA, intersection.thresholdA);
      const mB = H.conditionMatches(b, conditionB, intersection.thresholdB);
      const group = mA && mB ? 'both' : mA ? 'a' : mB ? 'b' : 'neither';
      return { ...base, fillColor: OVERLAP[group], fillOpacity: group === 'neither' ? 0.6 : 0.88 };
    }
    if (layer.categorical) {
      const c = CLUSTERS[f.properties.lisa_cluster] || CLUSTERS.none;
      return { ...base, fillColor: c.color, fillOpacity: 0.85 };
    }
    const v = H.displayValue(f, column);
    return { ...base, fillColor: ramp(H.percentileRank(stats.sorted, v), MISSING), fillOpacity: v === null ? 0.45 : 0.88 };
  };

  const tooltipFor = useCallback((f) => {
    const p = f.properties;
    const name = `<strong>${p.area_label || 'Tract ' + p.NAME}</strong><span class="tt-sub">Tract ${p.NAME}</span>`;
    if (appMode === 'overlap') return `${name}${metricA.label}: ${H.fmt(H.metricValue(f, metricA), metricA.unit)}<br>${metricB.label}: ${H.fmt(H.metricValue(f, metricB), metricB.unit)}`;
    if (layer.categorical) return `${name}${(CLUSTERS[p.lisa_cluster] || CLUSTERS.none).label}<br>Score ${H.fmt(H.displayValue(f, 'uoi_score'), 'score')}`;
    const v = H.displayValue(f, column);
    return `${name}${title}: ${v === null ? 'no estimate' : H.fmt(v, unit)}`;
  }, [appMode, metricA, metricB, layer.categorical, column, title, unit]);

  const applySelection = useCallback((fly) => {
    if (!layerRef.current) return;
    if (selectedLayerRef.current) { layerRef.current.resetStyle(selectedLayerRef.current); selectedLayerRef.current = null; }
    if (!selectedGeoid) return;
    layerRef.current.eachLayer(lyr => {
      if (lyr.feature && lyr.feature.properties.GEOID === selectedGeoid) {
        selectedLayerRef.current = lyr;
        lyr.setStyle({ color: ROSE, weight: 3, opacity: 1 });
        lyr.bringToFront();
        if (fly) mapRef.current.flyToBounds(lyr.getBounds(), { padding: [140, 140], maxZoom: 13, duration: 0.6 });
      }
    });
  }, [selectedGeoid]);

  // ---- build map once ----
  useEffect(() => {
    if (mapRef.current) return;
    mapRef.current = L.map('map', { scrollWheelZoom: true, zoomControl: false, attributionControl: true, zoomSnap: 0.25, zoomDelta: 0.5 });
    L.control.zoom({ position: 'topright' }).addTo(mapRef.current);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png?key=' + CARTO_KEY, { maxZoom: 19, attribution: '© CARTO, © OpenStreetMap contributors', subdomains: 'abcd' }).addTo(mapRef.current);
    // Street and place labels sit above the shaded tracts so the map stays readable.
    const labels = mapRef.current.createPane('labels');
    labels.style.zIndex = 450;
    labels.style.pointerEvents = 'none';
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png?key=' + CARTO_KEY, { maxZoom: 19, subdomains: 'abcd', pane: 'labels' }).addTo(mapRef.current);
  }, []);

  // ---- tract layer ----
  useEffect(() => {
    const map = mapRef.current;
    const first = !layerRef.current;
    if (layerRef.current) layerRef.current.remove();
    selectedLayerRef.current = null;
    layerRef.current = L.geoJSON(tracts, {
      style: f => styleRef.current(f),
      onEachFeature: (f, lyr) => {
        lyr.bindTooltip(() => tooltipFor(f), { sticky: true, className: 'tt', direction: 'top', offset: [0, -8] });
        lyr.on('click', () => setSelectedGeoid(g => g === f.properties.GEOID ? null : f.properties.GEOID));
        lyr.on('mouseover', () => { if (lyr !== selectedLayerRef.current) lyr.setStyle({ weight: 2, color: '#23212b' }); });
        lyr.on('mouseout', () => { if (lyr !== selectedLayerRef.current) layerRef.current.resetStyle(lyr); });
      }
    }).addTo(map);
    if (districtRef.current) districtRef.current.bringToFront();
    if (first) {
      // Always give the map a starting view, then zoom to a tract if the link named one.
      map.fitBounds(layerRef.current.getBounds(), { padding: [16, 16] });
      setTimeout(() => {
        map.invalidateSize();
        if (selectedLayerRef.current) map.fitBounds(selectedLayerRef.current.getBounds(), { padding: [140, 140], maxZoom: 13 });
        else map.fitBounds(layerRef.current.getBounds(), { padding: [16, 16] });
      }, 80);
    }
    applySelection(false);
  }, [tracts, column, stats, appMode, layer.categorical, metricAKey, conditionA, metricBKey, conditionB, intersection.thresholdA, intersection.thresholdB, tooltipFor]);

  useEffect(() => { applySelection(true); }, [selectedGeoid]);

  // ---- districts ----
  useEffect(() => {
    const map = mapRef.current;
    if (districtRef.current) { districtRef.current.remove(); districtRef.current = null; }
    if (!showDistricts || !commissionDistricts) return;
    districtRef.current = L.geoJSON(commissionDistricts, {
      interactive: false,
      style: f => f.properties.District === highlightDistrict
        ? { color: '#23212b', weight: 3, dashArray: null, fillOpacity: 0, opacity: 1 }
        : { color: '#23212b', weight: 1.2, dashArray: '4 4', fillOpacity: 0, opacity: 0.55 }
    }).addTo(map);
    districtRef.current.eachLayer(lyr => {
      const d = lyr.feature.properties.District;
      lyr.bindTooltip(`District ${d}`, { permanent: true, direction: 'center', className: 'district-label' + (d === highlightDistrict ? ' on' : '') });
    });
    if (highlightDistrict) {
      districtRef.current.eachLayer(lyr => { if (lyr.feature.properties.District === highlightDistrict) map.flyToBounds(lyr.getBounds(), { padding: [30, 30], duration: 0.6 }); });
    }
  }, [showDistricts, commissionDistricts, highlightDistrict]);

  const showLayer = (key) => { setAppMode('single'); setLayerKey(key); setHighlightDistrict(null); };
  const showDistrict = (d) => { setShowDistricts(true); setHighlightDistrict(d); };
  const pickLayer = (key) => { setLayerKey(key); const l = LAYERS.find(x => x.key === key); if (l && l.single) setMode('score'); };

  const listTitle = appMode === 'overlap'
    ? `${intersection.matches.length} tracts meet both conditions`
    : layer.categorical ? 'Tracts in a significant cluster' : `Tracts by ${title.charAt(0).toLowerCase() + title.slice(1)}`;

  return <div className="app">
    <header className="masthead">
      <div className="title">
        <h1>Bernalillo County Opportunity Index</h1>
        <p className="dek">How the county’s {tracts.features.length} census tracts compare on income, housing, health, access and eviction pressure. Census data from 2018–2022; eviction filings through {summary ? new Date(summary.eviction.end + 'T12:00').toLocaleDateString('en-US', { month: 'long', year: 'numeric' }) : '2026'}.</p>
      </div>
      <nav className="actions">
        <button type="button" className="btn-quiet" onClick={() => setMethodsOpen(true)}>How this is built</button>
        <a className="btn-quiet" href={REPO_URL} target="_blank" rel="noopener">Code on GitHub</a>
        <a className="btn-primary" href={CSV_URL} download="bernalillo_opportunity_index.csv">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2.5v7.2M4.8 6.8 8 10l3.2-3.2M3 12.5h10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          Download data
        </a>
      </nav>
    </header>

    <div className="body">
      <aside className="left">
        <div className="controls">
          <Segmented label="Map type" value={appMode} onChange={m => { setAppMode(m); setHighlightDistrict(null); }} options={[{ value: 'single', label: 'Map one measure' }, { value: 'overlap', label: 'Find overlaps' }]} />

          {appMode === 'single' && <>
            <label className="field">
              <span>Measure</span>
              <select value={layerKey} onChange={e => pickLayer(e.target.value)}>
                <optgroup label="Headline">
                  {LAYERS.filter(l => l.single).map(l => <option key={l.key} value={l.key}>{l.label}</option>)}
                </optgroup>
                <optgroup label="Score inputs">
                  {LAYERS.filter(l => !l.single && !l.notInScore).map(l => <option key={l.key} value={l.key}>{l.label}</option>)}
                </optgroup>
                <optgroup label="For reference">
                  {LAYERS.filter(l => !l.single && l.notInScore).map(l => <option key={l.key} value={l.key}>{l.label}</option>)}
                </optgroup>
              </select>
            </label>
            {!layer.single && <Segmented label="Reading" value={mode} onChange={setMode} options={[{ value: 'score', label: 'Score (0–100)' }, { value: 'raw', label: 'Actual value' }]} />}
            <p className="about">{layer.why} {layer.scoreMeaning}</p>
          </>}

          {appMode === 'overlap' && <>
            <p className="about">Find tracts in the worst or best quarter of the county on two measures at once, for example high eviction filings and high uninsured rates.</p>
            {[['A', metricAKey, setMetricAKey, conditionA, setConditionA, intersection.thresholdA, metricA], ['B', metricBKey, setMetricBKey, conditionB, setConditionB, intersection.thresholdB, metricB]].map(([k, mk, setMk, cond, setCond, thr, m]) =>
              <div className="overlap-pick" key={k}>
                <label className="field">
                  <span>{k === 'A' ? 'First measure' : 'Second measure'}</span>
                  <select value={mk} onChange={e => setMk(e.target.value)}>{META.map(x => <option key={x.key} value={x.key}>{x.label}</option>)}</select>
                </label>
                <Segmented label={`Quarter for measure ${k}`} value={cond} onChange={setCond} options={[{ value: 'top', label: 'Highest quarter' }, { value: 'bottom', label: 'Lowest quarter' }]} />
                <p className="cutoff">{cond === 'bottom' ? 'At or below' : 'At or above'} {H.fmtLong(thr, m.unit)}</p>
              </div>)}
          </>}

          <label className="check">
            <input type="checkbox" checked={showDistricts} onChange={e => { setShowDistricts(e.target.checked); if (!e.target.checked) setHighlightDistrict(null); }} />
            <span>Show County Commission districts</span>
          </label>
        </div>

        {selectedFeature
          ? <TractProfile key={selectedGeoid} feature={selectedFeature} tracts={tracts} summary={summary} onClose={() => setSelectedGeoid(null)} />
          : <Findings summary={summary} onShowLayer={showLayer} onShowDistrict={showDistrict} />}
      </aside>

      <main className="mapwrap">
        <div id="map" className="map" role="region" aria-label="Map of census tracts"></div>
        <div className="legend">
          {appMode === 'overlap' ? <>
            <div className="legend-title">Quarter-of-county overlap</div>
            <ul className="swatches">
              <li><i style={{ background: OVERLAP.both }}></i>Both</li>
              <li><i style={{ background: OVERLAP.a }}></i>{metricA.label} only</li>
              <li><i style={{ background: OVERLAP.b }}></i>{metricB.label} only</li>
              <li><i style={{ background: OVERLAP.neither }}></i>Neither</li>
            </ul>
          </> : layer.categorical ? <>
            <div className="legend-title">Clusters of the opportunity score</div>
            <ul className="swatches">
              {['low_low', 'high_high', 'low_high', 'high_low', 'none'].map(k => <li key={k}><i style={{ background: CLUSTERS[k].color }}></i>{CLUSTERS[k].label}{summary ? <span className="n">{summary.clusters.counts[k] || 0}</span> : null}</li>)}
            </ul>
          </> : <>
            <div className="legend-title">{title}</div>
            <div className="legend-bar" style={{ background: `linear-gradient(to right, ${RAMP.join(', ')})` }}></div>
            <div className="legend-scale">
              <span className="l">{H.fmt(stats.min, unit)}</span>
              <span className="m">{H.fmt(stats.median, unit)}</span>
              <span className="r">{H.fmt(stats.max, unit)}</span>
            </div>
            <div className="legend-caption">
              <span>{higherWorse ? 'Better' : 'Lower'}</span>
              <span>Median tract</span>
              <span>{higherWorse ? 'Worse' : 'Higher'}</span>
            </div>
            <p className="legend-note">Shaded by rank, so each color band holds about the same number of tracts.</p>
            {stats.sorted.length < tracts.features.length && <p className="legend-missing"><i style={{ background: MISSING }}></i>No estimate ({tracts.features.length - stats.sorted.length} tracts)</p>}
          </>}
        </div>
      </main>

      <aside className="right">
        <div className="list-head">
          <h2>{listTitle}</h2>
          {appMode === 'overlap' && <p className="list-note">Each row shows {metricA.label.toLowerCase()} above {metricB.label.toLowerCase()}, sorted by how extreme the pair is.</p>}
          {layer.categorical && appMode === 'single' && <p className="list-note">Low-scoring clusters first, then mixed tracts, then high-scoring clusters.</p>}
          <input className="search" type="search" placeholder="Find a neighborhood or tract number" value={query} onChange={e => setQuery(e.target.value)} aria-label="Find a neighborhood or tract number" />
          {appMode === 'single' && !layer.categorical && <Segmented label="Sort order" value={sortOrder} onChange={setSortOrder} options={[{ value: 'desc', label: 'Highest first' }, { value: 'asc', label: 'Lowest first' }]} />}
        </div>
        <ol className="list">
          {listRows.length === 0 && <li className="empty">No tract matches “{query}”. Try a neighborhood name like Barelas or a tract number like 47.15.</li>}
          {listRows.map(row => {
            const f = row.feature, p = f.properties;
            const isSel = selectedGeoid === p.GEOID;
            const onClick = () => setSelectedGeoid(isSel ? null : p.GEOID);
            let right;
            if (appMode === 'overlap') {
              right = <div className="vals"><span>{H.fmt(row.a, metricA.unit)}</span><span>{H.fmt(row.b, metricB.unit)}</span></div>;
            } else if (layer.categorical) {
              const c = CLUSTERS[p.lisa_cluster];
              right = <div className="vals"><span className="num"><i className="dot" style={{ background: c.color }} title={c.label}></i>{H.fmt(row.value, 'score')}</span></div>;
            } else {
              const pct = stats.max === stats.min ? 0.5 : (row.value - stats.min) / (stats.max - stats.min);
              right = <div className="vals"><span className="num">{H.fmt(row.value, unit)}</span><span className="bar"><i style={{ width: `${Math.max(2, pct * 100)}%` }}></i></span></div>;
            }
            return <li key={p.GEOID}>
              <button type="button" className={isSel ? 'row sel' : 'row'} onClick={onClick} aria-pressed={isSel}>
                <span className="rank">{row.rank}</span>
                <span className="name"><span className="area">{p.area_label}</span><span className="tract">Tract {p.NAME}</span></span>
                {right}
              </button>
            </li>;
          })}
        </ol>
      </aside>
    </div>

    {methodsOpen && <Methods summary={summary} onClose={() => setMethodsOpen(false)} />}
  </div>;
}

window.BernAppMain = Atlas;
