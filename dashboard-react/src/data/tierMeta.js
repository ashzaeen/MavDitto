// Risk-tier colors -- see Project Files/DESIGN.md's Semantic Status Colors
// table. Unlike the old theme-invariant palette, DESIGN.md gives an explicit
// (different) text+background hex pair per theme, so each tier now carries
// both rather than one hex plus a computed tint.
export const TIER_META = {
  clean: {
    label: 'Clean',
    light: { text: '#1a7a4c', bg: '#eaf5ef' },
    dark: { text: '#2fa37a', bg: 'rgba(47, 163, 122, 0.10)' },
  },
  minor: {
    label: 'Minor Rewording',
    light: { text: '#9a5b00', bg: '#fbf1e0' },
    dark: { text: '#d9a24a', bg: 'rgba(217, 162, 74, 0.10)' },
  },
  major: {
    label: 'Major Rewording',
    light: { text: '#ad4b12', bg: '#fbe8dc' },
    dark: { text: '#e08a5c', bg: 'rgba(224, 138, 92, 0.10)' },
  },
  missing: {
    label: 'Missing Content',
    light: { text: '#a3271e', bg: '#fae8e6' },
    dark: { text: '#e2756d', bg: 'rgba(226, 117, 109, 0.10)' },
  },
  error: {
    label: "Couldn't Check",
    light: { text: '#52606d', bg: '#eef0f2' },
    dark: { text: '#8b94a0', bg: 'rgba(255, 255, 255, 0.05)' },
  },
};

export function hexToRgba(hex, alpha = 1) {
  if (!hex || !hex.startsWith('#')) return hex;
  const h = hex.slice(1);
  const num = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
  const r = (num >> 16) & 255;
  const g = (num >> 8) & 255;
  const b = num & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// The tier's single representative color for a decorative dot/bar-fill
// rather than a full badge -- callers that aren't rendering a pill (a stat
// tile's dot, the similarity bar's fill) still need one color, and it should
// still track theme.
export function tierColor(tier, theme) {
  const meta = TIER_META[tier];
  if (!meta) return theme === 'dark' ? '#9aa1a9' : '#746661';
  return meta[theme === 'dark' ? 'dark' : 'light'].text;
}
