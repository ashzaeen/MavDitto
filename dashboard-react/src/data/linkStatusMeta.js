// Status-tier colors for the Broken Link Inspector -- see Project Files/
// DESIGN.md's Semantic Status Colors table. These map cleanly onto its three
// named buckets (the table literally names "Redirected"/"Restricted" under
// Warning and "Broken"/"Unreachable" under Danger), unlike tierMeta.js's
// migration tiers, which needed two extras the table doesn't cover.
const SUCCESS = { text: '#1a8f4c', bg: '#e7f6ec' };
const SUCCESS_DARK = { text: '#34d399', bg: 'rgba(52, 211, 153, 0.12)' };
const WARNING = { text: '#b45309', bg: '#fdf1e3' };
const WARNING_DARK = { text: '#f5a524', bg: 'rgba(245, 165, 36, 0.12)' };
const DANGER = { text: '#c0392b', bg: '#fbeae8' };
const DANGER_DARK = { text: '#f87171', bg: 'rgba(248, 113, 113, 0.12)' };

export const LINK_STATUS_META = {
  ok: { label: 'OK', light: SUCCESS, dark: SUCCESS_DARK },
  redirected: { label: 'Redirected', light: WARNING, dark: WARNING_DARK },
  restricted: { label: 'Restricted', light: WARNING, dark: WARNING_DARK },
  broken: { label: 'Broken', light: DANGER, dark: DANGER_DARK },
  broken_anchor: { label: 'Broken Anchor', light: DANGER, dark: DANGER_DARK },
  unreachable: { label: 'Unreachable', light: DANGER, dark: DANGER_DARK },
  format_invalid: { label: 'Invalid Format', light: DANGER, dark: DANGER_DARK },
};

// Worst-first: Broken/Unreachable/Broken anchor/Format invalid, then
// Redirected/Restricted, then OK -- see the design doc's default sort.
export const STATUS_SEVERITY = {
  broken: 0, unreachable: 0, broken_anchor: 0, format_invalid: 0,
  redirected: 1, restricted: 1,
  ok: 2,
};

// An editor's decision about a problem link, independent of its check status.
// `resolved` states dim the row; `tone` picks the pill's status-token pair.
export const REVIEW_STATES = [
  { key: 'not_reviewed', label: 'Not Reviewed', tone: 'neutral', resolved: false },
  { key: 'needs_fix', label: 'Needs Fix', tone: 'danger', resolved: false },
  { key: 'escalated', label: 'Escalated', tone: 'warning', resolved: false },
  { key: 'fixed', label: 'Fixed', tone: 'success', resolved: true },
  { key: 'removed', label: 'Removed', tone: 'success', resolved: true },
  { key: 'not_an_issue', label: 'Not an Issue', tone: 'muted', resolved: true },
];

export const REVIEW_BY_KEY = Object.fromEntries(REVIEW_STATES.map((s) => [s.key, s]));

export const CATEGORY_LABELS = {
  internal_in_scope: 'Internal — In Scope',
  internal_other: 'Internal — Other Section',
  external: 'External',
  document: 'Document',
  image: 'Image',
  media: 'Media',
  anchor: 'Anchor / Fragment',
  email: 'Email',
  phone: 'Phone',
};

export const CATEGORY_ORDER = Object.keys(CATEGORY_LABELS);

export const REGION_LABELS = {
  '': 'Main Content',
  header: 'Header',
  nav: 'Navbar',
  footer: 'Footer',
};
