import { TIER_META, hexToRgba } from '../data/tierMeta.js';
import { CheckIcon, PencilIcon, TriangleAlertIcon, XCircleIcon, HelpCircleIcon } from './Icons.jsx';
import { useTheme } from '../ThemeContext.jsx';

export const TIER_ICONS = {
  clean: CheckIcon,
  minor: PencilIcon,
  major: TriangleAlertIcon,
  missing: XCircleIcon,
  error: HelpCircleIcon,
};
const ICONS = TIER_ICONS;

// Risk-tier pill: DESIGN.md gives each tier its own text+background pair per
// theme directly (see tierMeta.js), so the badge reads those rather than
// computing a tint from one theme-invariant hex the way it used to.
export default function RiskBadge({ tier }) {
  const { theme } = useTheme();
  const meta = TIER_META[tier];
  const Icon = ICONS[tier];
  const { text, bg } = meta[theme === 'dark' ? 'dark' : 'light'];

  return (
    <span className="risk-badge" style={{ background: bg, borderColor: hexToRgba(text, 0.25) }}>
      <span className="risk-badge-icon" style={{ color: text }}>
        <Icon size={13} />
      </span>
      <span className="risk-badge-label">{meta.label}</span>
    </span>
  );
}
