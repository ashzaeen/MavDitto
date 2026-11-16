// The "nothing here yet" treatment every table view needs before its first
// run -- an icon, one line explaining what belongs here, a button to go
// start the relevant scan. Consolidates what MainView.jsx and NotMigrated.jsx
// already did ad hoc, in slightly different shapes, into one component --
// see the rehaul doc's "Consistent affordances and empty states".
export default function EmptyState({ icon: Icon, title, children }) {
  return (
    <div className="empty-state">
      {Icon && <Icon style={{ color: 'var(--ink-3)' }} />}
      <h1 className="h1" style={{ fontSize: 18 }}>{title}</h1>
      {children}
    </div>
  );
}
