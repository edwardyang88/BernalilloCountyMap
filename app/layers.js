// Shared logic for all three Bernalillo Opportunity Index variations.
// Pure data, helpers, and metric definitions — no DOM.

window.BERN_LAYERS = [
  { key: 'overall', label: 'Overall opportunity', shortLabel: 'Overall', scoreCol: 'uoi_score', rawCol: 'uoi_score', rawLabel: 'Overall opportunity score', rawUnit: 'score', rawDirection: 'higher_better', why: 'A combined view of access, stability, income, education, and hardship signals.', scoreMeaning: 'Higher scores mean stronger overall access and fewer measured barriers.' },
  { key: 'internet', label: 'Internet access', shortLabel: 'Internet', scoreCol: 'norm_broadband', rawCol: 'pct_broadband', rawLabel: 'Households with home internet', rawUnit: 'percent', rawDirection: 'higher_better', why: 'Home internet affects job search, benefits access, school work, telehealth, and legal self-help.', scoreMeaning: 'Higher scores mean more households have home internet.' },
  { key: 'housing', label: 'Housing cost pressure', shortLabel: 'Housing', scoreCol: 'norm_rent_burdened', rawCol: 'pct_rent_burdened', rawLabel: 'Households with high housing costs', rawUnit: 'percent', rawDirection: 'higher_worse', why: 'High housing costs leave less money for food, transportation, utilities, and emergency expenses.', scoreMeaning: 'Higher scores mean fewer households are cost burdened.' },
  { key: 'health', label: 'Health insurance coverage', shortLabel: 'Insurance', scoreCol: 'norm_uninsured', rawCol: 'pct_uninsured', rawLabel: 'People without health insurance', rawUnit: 'percent', rawDirection: 'higher_worse', why: 'Uninsured residents are more exposed to medical debt and delayed care.', scoreMeaning: 'Higher scores mean fewer people are uninsured.' },
  { key: 'hospital', label: 'Hospital access', shortLabel: 'Hospital', scoreCol: 'norm_hospital_access', rawCol: 'hospital_distance_mi', rawLabel: 'Miles to nearest hospital', rawUnit: 'miles', rawDirection: 'higher_worse', why: 'Longer distance to a hospital can make emergency care and follow-up care harder to reach.', scoreMeaning: 'Higher scores mean the tract is closer to a hospital.' },
  { key: 'poverty', label: 'Poverty', shortLabel: 'Poverty', scoreCol: 'norm_poverty', rawCol: 'pct_poverty', rawLabel: 'People below the poverty line', rawUnit: 'percent', rawDirection: 'higher_worse', why: 'Poverty is a direct signal of economic stress and eligibility pressure for support services.', scoreMeaning: 'Higher scores mean lower poverty rates.' },
  { key: 'income', label: 'Household income', shortLabel: 'Income', scoreCol: 'norm_income', rawCol: 'median_hh_income', rawLabel: 'Median household income', rawUnit: 'currency', rawDirection: 'higher_better', why: 'Income helps identify where households have more or less room to absorb financial shocks.', scoreMeaning: 'Higher scores mean higher median household incomes.' },
  { key: 'disability', label: 'Disability-related barriers', shortLabel: 'Disability', scoreCol: 'norm_disability', rawCol: 'pct_disability', rawLabel: 'People living with a disability', rawUnit: 'percent', rawDirection: 'higher_worse', why: 'Disability can increase the need for accessible services, transportation support, and benefits navigation.', scoreMeaning: 'Higher scores mean a lower measured disability-related barrier rate.' },
  { key: 'education', label: 'Education', shortLabel: 'Education', scoreCol: 'norm_hs_or_higher', rawCol: 'pct_hs_or_higher', rawLabel: 'Adults with high school or higher', rawUnit: 'percent', rawDirection: 'higher_better', why: 'Educational attainment is connected to employment options, income, and navigation of institutions.', scoreMeaning: 'Higher scores mean more adults have at least a high school credential.' },
  { key: 'snap', label: 'SNAP reliance', shortLabel: 'SNAP', scoreCol: 'norm_snap', rawCol: 'pct_snap', rawLabel: 'Households receiving SNAP', rawUnit: 'percent', rawDirection: 'higher_worse', why: 'SNAP use can point to food insecurity and household income stress.', scoreMeaning: 'Higher scores mean lower SNAP reliance.' },
  { key: 'unemployment', label: 'Unemployment', shortLabel: 'Jobs', scoreCol: 'norm_unemployment', rawCol: 'unemployment_rate', rawLabel: 'Unemployment rate', rawUnit: 'percent', rawDirection: 'higher_worse', why: 'Unemployment is a strong signal of near-term financial instability.', scoreMeaning: 'Higher scores mean lower unemployment.' },
  { key: 'eviction', label: 'Eviction pressure', shortLabel: 'Eviction', scoreCol: 'eviction_resilience_score', rawCol: 'eviction_risk_score', rawLabel: 'Eviction pressure score', rawUnit: 'score', rawDirection: 'higher_worse', why: 'This proxy combines rent burden, poverty, SNAP reliance, and unemployment to flag instability.', scoreMeaning: 'Higher scores mean stronger resilience against eviction pressure.' },
  { key: 'vehicle', label: 'Vehicle access', shortLabel: 'Vehicle', scoreCol: 'norm_vehicle_access', rawCol: 'pct_no_vehicle', rawLabel: 'Households without a vehicle', rawUnit: 'percent', rawDirection: 'higher_worse', why: 'Bernalillo County is car-dependent. Households without a vehicle face compounded barriers to jobs, healthcare, and groceries.', scoreMeaning: 'Higher scores mean fewer households are without a vehicle.' },
  { key: 'language', label: 'Language access', shortLabel: 'Language', scoreCol: 'norm_language_access', rawCol: 'pct_lep', rawLabel: 'Limited English speaking households', rawUnit: 'percent', rawDirection: 'higher_worse', why: 'Households with limited English proficiency face barriers to navigating services, benefits, legal processes, and healthcare.', scoreMeaning: 'Higher scores mean fewer households face language-based service barriers.' }
];

window.BERN_INTERSECTION_METRICS = [
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
  { key: 'vehicle', label: 'No-vehicle households', column: 'pct_no_vehicle', unit: 'percent' },
  { key: 'language', label: 'Limited English households', column: 'pct_lep', unit: 'percent' },
  { key: 'overall', label: 'Overall opportunity score', column: 'uoi_score', unit: 'score', scale: 100 }
];

window.BernHelpers = (function () {
  function asNumber(v) { if (v === null || v === undefined || v === '') return null; const n = Number(v); return Number.isFinite(n) ? n : null; }
  function isScoreColumn(col) { return col && (col.startsWith('norm_') || col.endsWith('_score')); }
  function displayValue(feature, col) { const raw = asNumber(feature.properties[col]); if (raw === null) return null; return isScoreColumn(col) ? raw * 100 : raw; }
  function fmt(v, unit) {
    if (v === null || v === undefined || Number.isNaN(v)) return '—';
    if (unit === 'currency') return '$' + Math.round(v).toLocaleString();
    if (unit === 'percent') return v.toFixed(1) + '%';
    if (unit === 'miles') return v.toFixed(1) + ' mi';
    return v.toFixed(1);
  }
  function metricByKey(key) { return window.BERN_INTERSECTION_METRICS.find(m => m.key === key) || window.BERN_INTERSECTION_METRICS[0]; }
  function metricValue(feature, metric) { const v = asNumber(feature.properties[metric.column]); if (v === null) return null; return metric.scale ? v * metric.scale : v; }
  function quantile(values, q) {
    const clean = values.filter(v => Number.isFinite(v)).sort((a, b) => a - b);
    if (!clean.length) return null;
    const pos = (clean.length - 1) * q;
    const base = Math.floor(pos);
    const rest = pos - base;
    if (clean[base + 1] !== undefined) return clean[base] + rest * (clean[base + 1] - clean[base]);
    return clean[base];
  }
  function conditionMatches(value, condition, threshold) { if (value === null || threshold === null) return false; return condition === 'bottom' ? value <= threshold : value >= threshold; }
  function conditionText(metric, condition, threshold) {
    const side = condition === 'bottom' ? 'bottom quartile' : 'top quartile';
    const op = condition === 'bottom' ? '≤' : '≥';
    return `${metric.label}: ${side} (${op} ${fmt(threshold, metric.unit)})`;
  }

  // Build a sequential color ramp from N anchor stops.
  // stops: array of hex strings, sorted low→high intensity.
  // higherWorse: when true, high values use the saturated end; otherwise inverted.
  function makeRamp(stops) {
    function hexToRgb(h) { const n = parseInt(h.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
    const rgb = stops.map(hexToRgb);
    return function (value, min, max, higherWorse, missing = '#d1d5db') {
      if (value === null || !Number.isFinite(value)) return missing;
      let t = max === min ? 0.5 : Math.max(0, Math.min(1, (value - min) / (max - min)));
      if (!higherWorse) t = 1 - t;
      const idx = t * (rgb.length - 1);
      const i = Math.floor(idx);
      const f = idx - i;
      const a = rgb[i];
      const b = rgb[Math.min(i + 1, rgb.length - 1)];
      const r = Math.round(a[0] + (b[0] - a[0]) * f);
      const g = Math.round(a[1] + (b[1] - a[1]) * f);
      const bl = Math.round(a[2] + (b[2] - a[2]) * f);
      return `rgb(${r}, ${g}, ${bl})`;
    };
  }

  function intersectionAnalysis(tracts, metricA, conditionA, metricB, conditionB) {
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
    const validCount = tracts.features.filter(f => metricValue(f, metricA) !== null && metricValue(f, metricB) !== null).length;
    return { thresholdA, thresholdB, validCount, matches: ranked.filter(r => r.matchA && r.matchB).sort((a, b) => b.priority - a.priority), ranked };
  }

  function rankedSingleLayer(tracts, column, direction, mode) {
    const rows = tracts.features.map(f => ({ feature: f, value: displayValue(f, column) })).filter(r => r.value !== null);
    const lowestFirst = mode === 'score' ? true : direction !== 'higher_worse';
    return [...rows].sort((a, b) => lowestFirst ? a.value - b.value : b.value - a.value);
  }

  function singleLayerStats(rows) {
    const vals = rows.map(r => r.value).sort((a, b) => a - b);
    if (!vals.length) return { min: 0, max: 0, avg: 0 };
    return { min: vals[0], max: vals[vals.length - 1], avg: vals.reduce((s, v) => s + v, 0) / vals.length };
  }

  return { asNumber, isScoreColumn, displayValue, fmt, metricByKey, metricValue, quantile, conditionMatches, conditionText, makeRamp, intersectionAnalysis, rankedSingleLayer, singleLayerStats };
})();
