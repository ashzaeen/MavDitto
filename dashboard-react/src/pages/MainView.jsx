import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import Header from '../components/Header.jsx';
import RiskBadge, { TIER_ICONS } from '../components/RiskBadge.jsx';
import VerdictLedger from '../components/VerdictLedger.jsx';
import MigrationSubNav from '../components/MigrationSubNav.jsx';
import EmptyState from '../components/EmptyState.jsx';
import { ClockIcon, SearchIcon, DownloadIcon, AlertDotIcon, InboxIcon } from '../components/Icons.jsx';
import { TIER_META, tierColor } from '../data/tierMeta.js';
import { useData, usePages, useTotals, useDiscovery, useLastRun } from '../data/useData.jsx';
import { useTheme } from '../ThemeContext.jsx';

// Real pipeline URLs already carry their scheme; the mock data used bare
// hostnames. Prefixing unconditionally produced https://https://… links.
function href(url) {
  return /^https?:\/\//i.test(url) ? url : `https://${url}`;
}

// Long URLs make every row the same illegible width, so the display drops the
// scheme and keeps the part that identifies the page. The link still goes to
// the full URL, and the title attribute shows it in full on hover.
function shortUrl(url) {
  return String(url ?? '').replace(/^https?:\/\//i, '').replace(/\/$/, '');
}

const SEVERITY = { missing: 5, error: 4, major: 3, minor: 2, clean: 1 };

// Coverage and Similarity read as a pair, never alone -- a page can look
// faithfully reworded (high similarity) while most of its content quietly
// has no counterpart (low coverage). Showing them as one meter instead of
// two competing columns keeps that always in view.
function EvidenceMeter({ coverage, similarity, tierCol }) {
  if (coverage == null && similarity == null) return <span className="muted-dash">—</span>;
  return (
    <div className="evidence-meter">
      <div className="evidence-meter-row">
        <span className="evidence-meter-label">Cov</span>
        <span className="evidence-meter-track">
          <span
            className="evidence-meter-fill"
            style={{
              width: `${coverage ?? 0}%`,
              background: coverage < 90 ? 'var(--status-danger-text)' : 'var(--status-success-text)',
            }}
          />
        </span>
        <span className="evidence-meter-value">{coverage ?? '—'}%</span>
      </div>
      <div className="evidence-meter-row">
        <span className="evidence-meter-label">Sim</span>
        <span className="evidence-meter-track">
          <span
            className="evidence-meter-fill"
            style={{ width: `${similarity ?? 0}%`, background: tierCol }}
          />
        </span>
        <span className="evidence-meter-value">{similarity ?? '—'}%</span>
      </div>
    </div>
  );
}

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

// The build plan's "fix it checklist". Pages that never arrived lead it: a page
// that does not exist outranks any page that merely changed, and it appears in
// no row of the table below.
function checklistCsv(pages, discovery) {
  const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const head = ['done', 'tier', 'coverage', 'similarity', 'confidence', 'page', 'what to check', 'old url', 'new url'];
  const rows = [];

  for (const p of discovery?.notMigrated ?? []) {
    rows.push(['', 'Not Migrated', '', '', 'high', p.title || p.path,
      'no counterpart on the new site - redirect it, rebuild it, or accept the loss',
      p.url, '']);
  }
  for (const p of pages) {
    if (p.tier === 'clean') continue;
    const d = p.detail;
    const what = d
      ? [d.explanation, ...(d.reasons ?? [])].filter(Boolean).slice(0, 3).join('; ')
      : p.problems.join('; ');
    rows.push(['', TIER_META[p.tier]?.label ?? p.tier,
      p.coverage == null ? '' : `${p.coverage}%`,
      p.similarity == null ? '' : `${p.similarity}%`,
      p.confidence ?? '', p.label || p.newUrl, what || 'no findings recorded',
      p.oldUrl, p.newUrl]);
  }
  return [head, ...rows].map((r) => r.map(escape).join(',')).join('\n');
}

const SORT_OPTIONS = [
  { key: 'risk', label: 'Risk' },
  { key: 'similarity', label: 'Similarity' },
  { key: 'coverage', label: 'Coverage' },
  { key: 'date', label: 'Last Checked' },
];

const FILTER_OPTIONS = [
  { key: null, label: 'All' },
  { key: 'clean', label: 'Clean' },
  { key: 'minor', label: 'Minor Rewording' },
  { key: 'major', label: 'Major Rewording' },
  { key: 'missing', label: 'Missing Content' },
  { key: 'error', label: "Couldn't Check" },
];

export default function MainView() {
  const { theme } = useTheme();
  const { status } = useData();
  const PAGES = usePages();
  const TOTALS = useTotals();
  const discovery = useDiscovery();
  const lastRun = useLastRun();
  const { data } = useData();
  const notCompared = data?.notCompared ?? 0;
  const [filterTier, setFilterTier] = useState(null);
  const [query, setQuery] = useState('');
  const [sortBy, setSortBy] = useState('risk');

  // The fetch decides the screen. 'empty' means the export ran before any
  // pipeline run, which is a different thing from a failed load.
  const viewState = status === 'loaded' ? 'loaded' : status;

  const totalCore = TOTALS.clean + TOTALS.minor + TOTALS.major + TOTALS.missing;
  const totalAll = totalCore + TOTALS.error;

  const statTiles = ['clean', 'minor', 'major', 'missing'].map((k) => ({
    key: k,
    label: TIER_META[k].label,
    count: TOTALS[k],
    color: tierColor(k, theme),
    pct: Math.round((TOTALS[k] / totalCore) * 1000) / 10,
  }));

  const visibleRows = useMemo(() => {
    const q = query.trim().toLowerCase();
    let rows = PAGES.filter((r) => {
      if (filterTier && r.tier !== filterTier) return false;
      if (
        q &&
        !r.oldUrl.toLowerCase().includes(q) &&
        !r.newUrl.toLowerCase().includes(q) &&
        !(r.label ?? '').toLowerCase().includes(q)
      )
        return false;
      return true;
    });
    rows = [...rows].sort((a, b) => {
      if (sortBy === 'similarity') {
        const av = a.similarity === null ? -1 : a.similarity;
        const bv = b.similarity === null ? -1 : b.similarity;
        return av - bv;
      }
      if (sortBy === 'date') return (b.checked ?? '').localeCompare(a.checked ?? '');
      if (sortBy === 'coverage') {
        const av = a.coverage === null ? -1 : a.coverage;
        const bv = b.coverage === null ? -1 : b.coverage;
        return av - bv;
      }
      return SEVERITY[b.tier] - SEVERITY[a.tier];
    });
    return rows;
  }, [PAGES, filterTier, query, sortBy]);

  const chipCount = (key) => (key === null ? totalAll : TOTALS[key]);

  return (
    <div className="app migration-scope">
      <Header active="migration" crumbs={['Migration Validator', 'Migrated Pages']} />
      <div className="page-body">
        <MigrationSubNav />
        {viewState === 'loaded' && (
          <div className="stack-32">
            <div className="summary-row">
              <div className="stack-12">
                <div>
                  <h1 className="h1">Migration Summary</h1>
                  <div className="meta-line">
                    <ClockIcon /> {lastRun ? `Last run ${lastRun} · ` : ''}
                    {totalAll} page{totalAll === 1 ? '' : 's'} compared
                  </div>
                </div>
                {TOTALS.error > 0 && (
                  <div className="meta-line muted">
                    <AlertDotIcon /> {TOTALS.error} page couldn't be checked and needs another look
                  </div>
                )}
                {notCompared > 0 && (
                  <div className="meta-line muted">
                    <AlertDotIcon /> {notCompared} matched page
                    {notCompared === 1 ? '' : 's'} not compared — the pair cap was
                    reached. They are in the <Link to="/migration/redirects">Redirect Map</Link>;
                    raise "Pairs to compare" to diff their content.
                  </div>
                )}
              </div>
              <button
                type="button"
                className="btn btn-icon"
                onClick={() => download('mavditto-checklist.csv', checklistCsv(PAGES, discovery))}
              >
                <DownloadIcon /> Export Flagged Pages
              </button>
            </div>

            <VerdictLedger
              lead={{ value: totalAll, label: `page${totalAll === 1 ? '' : 's'} compared` }}
              segments={statTiles.map((t) => ({ ...t, Icon: TIER_ICONS[t.key] }))}
            />

            {discovery && discovery.notMigrated.length > 0 && (
              <Link to="/migration/missing" className="card notice notice-bad notice-link">
                <AlertDotIcon />
                <span>
                  <strong>
                    {discovery.notMigrated.length} old page
                    {discovery.notMigrated.length === 1 ? '' : 's'} never made it across.
                  </strong>{' '}
                  They have no counterpart on the new site, so they appear nowhere in
                  the table below — there is nothing to compare them against. Review them →
                </span>
              </Link>
            )}

            <div className="controls-row">
              <div className="chip-row">
                {FILTER_OPTIONS.map((c) => (
                  <button
                    key={c.label}
                    type="button"
                    className={`chip ${filterTier === c.key ? 'active' : ''}`}
                    onClick={() => setFilterTier(c.key)}
                  >
                    <span className="dot" style={{ background: c.key ? tierColor(c.key, theme) : 'var(--ink)' }} />
                    {c.label} ({chipCount(c.key)})
                  </button>
                ))}
              </div>
              <div className="controls-right">
                <label className="card search-box">
                  <span className="sr-only">Search by URL</span>
                  <SearchIcon style={{ color: 'var(--ink-3)', flex: 'none' }} />
                  <input
                    type="search"
                    placeholder="Search by URL"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
                <div className="sort-row">
                  <span className="sort-label">Sort</span>
                  {SORT_OPTIONS.map((s) => (
                    <button
                      key={s.key}
                      type="button"
                      className={`sortbtn ${sortBy === s.key ? 'active' : ''}`}
                      onClick={() => setSortBy(s.key)}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="card table-card">
              <div className="row-grid row-grid--migrated table-head">
                <span>Risk</span>
                <span>Old URL</span>
                <span>New URL</span>
                <span>Evidence</span>
                <span>Last Checked</span>
                <span className="text-right">Action</span>
              </div>
              {visibleRows.map((r) => (
                <div
                  className="row-grid row-grid--migrated rowline"
                  key={r.id}
                  style={{ '--row-tier-color': tierColor(r.tier, theme) }}
                >
                  <RiskBadge tier={r.tier} />
                  <a href={href(r.oldUrl)} target="_blank" rel="noopener noreferrer" className="urltext" title={r.oldUrl}>
                    {shortUrl(r.oldUrl)}
                  </a>
                  <a href={href(r.newUrl)} target="_blank" rel="noopener noreferrer" className="urltext" title={r.newUrl}>
                    {shortUrl(r.newUrl)}
                  </a>
                  <EvidenceMeter
                    coverage={r.coverage ?? null}
                    similarity={r.similarity}
                    tierCol={tierColor(r.tier, theme)}
                  />
                  <span className="checked-cell">{r.checked}</span>
                  <div className="text-right">
                    {r.tier !== 'error' ? (
                      <Link to={`/migration/pages/${r.id}`} className="review-link">
                        Review →
                      </Link>
                    ) : (
                      <span className="muted-dash">—</span>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div className="footnote">
              Showing {visibleRows.length} of {totalAll} checked pages
            </div>
          </div>
        )}

        {viewState === 'loading' && (
          <div className="stack-24">
            <div>
              <h1 className="h1">Migration Summary</h1>
              <div className="meta-line muted">Loading results…</div>
            </div>
            <div className="stat-grid">
              {[0, 1, 2, 3].map((i) => (
                <div className="skel" style={{ height: 78 }} key={i} />
              ))}
            </div>
            <div className="card" style={{ padding: 'var(--space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
              {[90, 96, 80, 92, 70, 88].map((w, i) => (
                <div className="skel" style={{ height: 16, width: `${w}%` }} key={i} />
              ))}
            </div>
          </div>
        )}

        {viewState === 'error' && (
          <EmptyState icon={AlertDotIcon} title="Couldn't Load Results">
            <p className="empty-copy">
              <code>public/data.json</code> is missing or unreadable. Generate it from a
              results folder:
            </p>
            <code className="code-block">python -m src.export_web --results data/run</code>
          </EmptyState>
        )}

        {viewState === 'empty' && (
          <EmptyState icon={InboxIcon} title="No Migration Run Yet">
            <p className="empty-copy">
              Start one from the Migration Validator's setup screen — paste
              the two site roots and MavDitto crawls, pairs, and compares them
              for you.
            </p>
            <Link to="/migration" className="btn btn-primary">
              Go to Migration Validator
            </Link>
            <p className="empty-copy empty-copy--alt">
              Working from a results folder someone already filled from a
              terminal instead? Export it here:
            </p>
            <code className="code-block">python -m src.export_web --results data/run</code>
          </EmptyState>
        )}
      </div>
    </div>
  );
}
