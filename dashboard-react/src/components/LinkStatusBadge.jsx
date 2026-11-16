import { LINK_STATUS_META } from '../data/linkStatusMeta.js';
import { hexToRgba } from '../data/tierMeta.js';
import { CheckIcon, TriangleAlertIcon, XCircleIcon } from './Icons.jsx';
import { useTheme } from '../ThemeContext.jsx';

const ICONS = {
  ok: CheckIcon,
  redirected: TriangleAlertIcon,
  restricted: TriangleAlertIcon,
  broken: XCircleIcon,
  broken_anchor: XCircleIcon,
  unreachable: XCircleIcon,
  format_invalid: XCircleIcon,
};

const FALLBACK = {
  light: { text: '#746661', bg: '#f2f0ee' },
  dark: { text: '#9aa1a9', bg: 'rgba(255, 255, 255, 0.06)' },
};

// Same visual language as RiskBadge: each status reads its own text+background
// pair for the active theme directly from linkStatusMeta.js.
export default function LinkStatusBadge({ status }) {
  const { theme } = useTheme();
  const key = theme === 'dark' ? 'dark' : 'light';
  const meta = LINK_STATUS_META[status];
  const Icon = ICONS[status] ?? TriangleAlertIcon;
  const { text, bg } = meta ? meta[key] : FALLBACK[key];

  return (
    <span className="risk-badge" style={{ background: bg, borderColor: hexToRgba(text, 0.25) }}>
      <span className="risk-badge-icon" style={{ color: text }}>
        <Icon size={13} />
      </span>
      <span className="risk-badge-label">{meta ? meta.label : status}</span>
    </span>
  );
}
