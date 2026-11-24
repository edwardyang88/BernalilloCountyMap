// Layer definitions and pure helpers for the Bernalillo County Opportunity Index.
// No DOM in here.

window.BERN_LAYERS = [
  { key: 'overall', label: 'Opportunity score', shortLabel: 'Opportunity score', scoreCol: 'uoi_score', rawCol: 'uoi_score', rawLabel: 'Opportunity score', rawUnit: 'score', rawDirection: 'higher_better', single: true,
    why: 'An equal-weight average of 11 measures of access, income, stability and hardship. Each measure is rescaled 0–100 across the county before averaging.',
    scoreMeaning: 'Higher means more access and fewer measured barriers than other tracts in the county.' },
  { key: 'filings', label: 'Eviction filings (measured)', shortLabel: 'Eviction filings', scoreCol: 'eviction_filing_rate', rawCol: 'eviction_filing_rate', rawLabel: 'Eviction filings per 100 renter households, last 12 months', rawUnit: 'per100', rawDirection: 'higher_worse', single: true,
    why: 'Court filings recorded by the Eviction Lab, counted for the most recent 52 complete weeks and divided by renter households. This is an outcome, not an estimate, and it is not part of the score.',
    scoreMeaning: 'Higher means more eviction cases were filed relative to the number of renters. Tracts with fewer than 50 renter households are left blank.' },
  { key: 'clusters', label: 'Clusters of high and low scores', shortLabel: 'Clusters', scoreCol: 'uoi_score', rawCol: 'uoi_score', rawUnit: 'score', rawDirection: 'higher_better', single: true, categorical: true,
    why: 'Local Moran’s I tests whether a tract and its neighbors score unusually alike. It separates real geographic concentrations from a single tract that happens to score low.',
    scoreMeaning: 'Shaded tracts are statistically significant at p < 0.05 after 999 random reshuffles of the map.' },
  { key: 'internet', label: 'Internet access', shortLabel: 'Internet', scoreCol: 'norm_broadband', rawCol: 'pct_broadband', rawLabel: 'Households with home internet', rawUnit: 'percent', rawDirection: 'higher_better', why: 'Home internet affects job search, benefits access, school work, telehealth and legal self-help.', scoreMeaning: 'Higher scores mean more households have home internet.' },
  { key: 'housing', label: 'Housing cost burden', shortLabel: 'Housing cost', scoreCol: 'norm_rent_burdened', rawCol: 'pct_rent_burdened', rawLabel: 'Households paying 30%+ of income on housing', rawUnit: 'percent', rawDirection: 'higher_worse', why: 'High housing costs leave less money for food, transportation, utilities and emergencies.', scoreMeaning: 'Higher scores mean fewer households are cost burdened.' },
  { key: 'health', label: 'Health insurance', shortLabel: 'Insurance', scoreCol: 'norm_uninsured', rawCol: 'pct_uninsured', rawLabel: 'People without health insurance', rawUnit: 'percent', rawDirection: 'higher_worse', why: 'Uninsured residents are more exposed to medical debt and delayed care.', scoreMeaning: 'Higher scores mean fewer people are uninsured.' },
  { key: 'hospital', label: 'Distance to a hospital', shortLabel: 'Hospital', scoreCol: 'norm_hospital_access', rawCol: 'hospital_distance_mi', rawLabel: 'Miles to the nearest hospital', rawUnit: 'miles', rawDirection: 'higher_worse', why: 'Longer distance to a hospital makes emergency and follow-up care harder to reach.', scoreMeaning: 'Higher scores mean the tract is closer to a hospital.' },
  { key: 'poverty', label: 'Poverty', shortLabel: 'Poverty', scoreCol: 'norm_poverty', rawCol: 'pct_poverty', rawLabel: 'People below the poverty line', rawUnit: 'percent', rawDirection: 'higher_worse', why: 'Poverty is a direct signal of economic stress and need for support services.', scoreMeaning: 'Higher scores mean lower poverty rates.' },
  { key: 'income', label: 'Household income', shortLabel: 'Income', scoreCol: 'norm_income', rawCol: 'median_hh_income', rawLabel: 'Median household income', rawUnit: 'currency', rawDirection: 'higher_better', why: 'Income shows how much room households have to absorb a financial shock.', scoreMeaning: 'Higher scores mean higher median household income.' },
  { key: 'disability', label: 'Disability', shortLabel: 'Disability', scoreCol: 'norm_disability', rawCol: 'pct_disability', rawLabel: 'People living with a disability', rawUnit: 'percent', rawDirection: 'higher_worse', why: 'Disability can raise the need for accessible services, transportation and benefits help.', scoreMeaning: 'Higher scores mean a lower disability rate.' },
  { key: 'education', label: 'Education', shortLabel: 'Education', scoreCol: 'norm_hs_or_higher', rawCol: 'pct_hs_or_higher', rawLabel: 'Adults with a high school diploma or more', rawUnit: 'percent', rawDirection: 'higher_better', why: 'Educational attainment is tied to job options, income and dealing with institutions.', scoreMeaning: 'Higher scores mean more adults have at least a high school credential.' },
  { key: 'snap', label: 'SNAP use', shortLabel: 'SNAP', scoreCol: 'norm_snap', rawCol: 'pct_snap', rawLabel: 'Households receiving SNAP', rawUnit: 'percent', rawDirection: 'higher_worse', why: 'SNAP use points to food insecurity and income stress.', scoreMeaning: 'Higher scores mean fewer households rely on SNAP.' },
  { key: 'unemployment', label: 'Unemployment', shortLabel: 'Unemployment', scoreCol: 'norm_unemployment', rawCol: 'unemployment_rate', rawLabel: 'Unemployment rate', rawUnit: 'percent', rawDirection: 'higher_worse', why: 'Unemployment is a strong signal of near-term financial instability.', scoreMeaning: 'Higher scores mean lower unemployment.' },
  { key: 'vehicle', label: 'Vehicle access', shortLabel: 'Vehicle', scoreCol: 'norm_vehicle_access', rawCol: 'pct_no_vehicle', rawLabel: 'Households without a vehicle', rawUnit: 'percent', rawDirection: 'higher_worse', why: 'Bernalillo County is car-dependent. Households without a car face extra barriers to jobs, care and groceries.', scoreMeaning: 'Higher scores mean fewer households are without a vehicle.' },
  { key: 'language', label: 'Language access', shortLabel: 'Language', scoreCol: 'norm_language_access', rawCol: 'pct_lep', rawLabel: 'Households with limited English', rawUnit: 'percent', rawDirection: 'higher_worse', notInScore: true, why: 'Households with limited English face barriers to services, benefits, courts and healthcare. Shown for reference; not part of the score.', scoreMeaning: 'Higher scores mean fewer households face language barriers.' },
  { key: 'eviction', label: 'Eviction risk (estimated)', shortLabel: 'Eviction risk', scoreCol: 'eviction_resilience_score', rawCol: 'eviction_risk_score', rawLabel: 'Estimated eviction risk', rawUnit: 'score', rawDirection: 'higher_worse', notInScore: true, why: 'An estimate built from rent burden, poverty, SNAP and unemployment. Compare it with the measured filings layer to see where the estimate misses.', scoreMeaning: 'Higher scores mean lower estimated risk.' }
];

// Indicators shown in the tract profile, in the order they feed the score.
window.BERN_PROFILE_KEYS = ['income', 'poverty', 'housing', 'snap', 'unemployment', 'education', 'health', 'internet', 'vehicle', 'disability', 'hospital', 'language'];

window.BERN_CLUSTERS = {
  low_low:   { label: 'Low-scoring cluster', color: '#c8405a', sentence: 'Part of a cluster of low-scoring tracts.' },
  high_high: { label: 'High-scoring cluster', color: '#3b3180', sentence: 'Part of a cluster of high-scoring tracts.' },
  low_high:  { label: 'Low tract among high', color: '#ec9aa8', sentence: 'Scores low while its neighbors score high.' },
  high_low:  { label: 'High tract among low', color: '#9d93cf', sentence: 'Scores high while its neighbors score low.' },
  none:      { label: 'No significant pattern', color: '#e7e5ec', sentence: 'Not part of a statistically significant cluster.' }
};

window.BERN_INTERSECTION_METRICS = [
  { key: 'filings', label: 'Eviction filing rate', column: 'eviction_filing_rate', unit: 'per100' },
  { key: 'income', label: 'Household income', column: 'median_hh_income', unit: 'currency' },
  { key: 'poverty', label: 'Poverty', column: 'pct_poverty', unit: 'percent' },
  { key: 'housing', label: 'Housing cost burden', column: 'pct_rent_burdened', unit: 'percent' },
  { key: 'uninsured', label: 'Uninsured rate', column: 'pct_uninsured', unit: 'percent' },
  { key: 'internet', label: 'Home internet', column: 'pct_broadband', unit: 'percent' },
  { key: 'hospital', label: 'Miles to hospital', column: 'hospital_distance_mi', unit: 'miles' },
  { key: 'disability', label: 'Disability', column: 'pct_disability', unit: 'percent' },
  { key: 'education', label: 'High school or more', column: 'pct_hs_or_higher', unit: 'percent' },
  { key: 'snap', label: 'SNAP use', column: 'pct_snap', unit: 'percent' },
  { key: 'unemployment', label: 'Unemployment', column: 'unemployment_rate', unit: 'percent' },
  { key: 'vehicle', label: 'No-vehicle households', column: 'pct_no_vehicle', unit: 'percent' },
  { key: 'language', label: 'Limited-English households', column: 'pct_lep', unit: 'percent' },
  { key: 'overall', label: 'Opportunity score', column: 'uoi_score', unit: 'score', scale: 100 }
];

window.BernHelpers = (function () {
  function asNumber(v) { if (v === null || v === undefined || v === '') return null; const n = Number(v); return Number.isFinite(n) ? n : null; }
  function isScoreColumn(col) { return col && (col.startsWith('norm_') || col === 'uoi_score' || col === 'eviction_risk_score' || col === 'eviction_resilience_score'); }
  function displayValue(feature, col) { const raw = asNumber(feature.properties[col]); if (raw === null) return null; return isScoreColumn(col) ? raw * 100 : raw; }
  function fmt(v, unit) {
    if (v === null || v === undefined || Number.isNaN(v)) return '–';
    if (unit === 'currency') return '$' + Math.round(v).toLocaleString();
    if (unit === 'percent') return v.toFixed(1) + '%';
    if (unit === 'miles') return v.toFixed(1) + ' mi';
    if (unit === 'per100') return v.toFixed(1);
    return v.toFixed(1);
  }
  function fmtLong(v, unit) {
    if (unit === 'per100') return v === null || v === undefined ? 'no estimate' : v.toFixed(1) + ' per 100 renters';
    return fmt(v, unit);
  }
  function ordinal(n) { const s = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }
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

  // Sequential ramp from N stops. t in [0, 1]; higher t = darker.
  function makeRamp(stops) {
    function hexToRgb(h) { const n = parseInt(h.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
    const rgb = stops.map(hexToRgb);
    return function (t, missing = '#d1d5db') {
      if (t === null || !Number.isFinite(t)) return missing;
      t = Math.max(0, Math.min(1, t));
      const idx = t * (rgb.length - 1);
      const i = Math.floor(idx);
      const f = idx - i;
      const a = rgb[i];
      const b = rgb[Math.min(i + 1, rgb.length - 1)];
      return `rgb(${Math.round(a[0] + (b[0] - a[0]) * f)}, ${Math.round(a[1] + (b[1] - a[1]) * f)}, ${Math.round(a[2] + (b[2] - a[2]) * f)})`;
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
      // How extreme each value is in the chosen direction, 0–100
      const scoreA = a === null ? 0 : valuesA.filter(v => conditionA === 'bottom' ? v >= a : v <= a).length / valuesA.length * 100;
      const scoreB = b === null ? 0 : valuesB.filter(v => conditionB === 'bottom' ? v >= b : v <= b).length / valuesB.length * 100;
      return { feature, a, b, matchA, matchB, extremeA: scoreA, extremeB: scoreB, priority: (scoreA + scoreB) / 2 };
    });
    const validCount = tracts.features.filter(f => metricValue(f, metricA) !== null && metricValue(f, metricB) !== null).length;
    return { thresholdA, thresholdB, validCount, matches: ranked.filter(r => r.matchA && r.matchB).sort((a, b) => b.priority - a.priority), ranked };
  }

  // order: 'desc' = highest value first, 'asc' = lowest value first
  function rankedSingleLayer(tracts, column, order = 'desc') {
    const rows = tracts.features.map(f => ({ feature: f, value: displayValue(f, column) })).filter(r => r.value !== null);
    return [...rows].sort((a, b) => order === 'asc' ? a.value - b.value : b.value - a.value);
  }

  function singleLayerStats(rows) {
    const vals = rows.map(r => r.value).sort((a, b) => a - b);
    if (!vals.length) return { min: 0, max: 0, avg: 0, median: 0, sorted: [] };
    return { min: vals[0], max: vals[vals.length - 1], avg: vals.reduce((s, v) => s + v, 0) / vals.length, median: quantile(vals, 0.5), sorted: vals };
  }

  // Where a value sits in the distribution, 0 (lowest tract) to 1 (highest tract).
  // Ties share the midpoint of their ranks. Used for color so one outlier can't wash out the map.
  function percentileRank(sorted, value) {
    if (value === null || !Number.isFinite(value) || !sorted.length) return null;
    if (sorted.length === 1) return 0.5;
    let lo = 0, hi = sorted.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (sorted[m] < value) lo = m + 1; else hi = m; }
    const first = lo;
    hi = sorted.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (sorted[m] <= value) lo = m + 1; else hi = m; }
    const last = lo - 1;
    return ((first + last) / 2) / (sorted.length - 1);
  }

  return { asNumber, isScoreColumn, displayValue, fmt, fmtLong, ordinal, metricByKey, metricValue, quantile, conditionMatches, makeRamp, intersectionAnalysis, rankedSingleLayer, singleLayerStats, percentileRank };
})();
