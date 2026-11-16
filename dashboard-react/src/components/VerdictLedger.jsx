// Replaces the old stat-tile-grid + composition-bar pair (two components
// that showed the exact same counts twice) with one report-summary line:
// a lead number, inline icon+dot+label+count chips, and a single stacked
// proportion bar. Color is never the only cue here -- every segment pairs
// its color with an icon and a text label, per the colorblind-safety
// convention used throughout the rest of the dashboard.
export default function VerdictLedger({ lead, segments }) {
  return (
    <div className="verdict-ledger">
      {lead && (
        <div className="verdict-ledger-lead">
          <span className="verdict-ledger-lead-value">{lead.value}</span>
          <span className="verdict-ledger-lead-label">{lead.label}</span>
        </div>
      )}
      <div className="verdict-ledger-labels">
        {segments.map((s) => {
          const Icon = s.Icon;
          return (
            <span className="verdict-ledger-label" key={s.key}>
              {Icon && <Icon size={12} style={{ color: s.color }} />}
              <span className="dot" style={{ background: s.color }} />
              {s.label} <strong>{s.count}</strong>
            </span>
          );
        })}
      </div>
      <div className="verdict-ledger-bar">
        {segments
          .filter((s) => s.pct > 0)
          .map((s) => (
            <div
              key={s.key}
              title={`${s.label}: ${s.count}`}
              style={{ width: `${s.pct}%`, background: s.color }}
            />
          ))}
      </div>
    </div>
  );
}
