import { useMemo, useState } from 'react';
import Header from '../components/Header.jsx';
import MigrationSubNav from '../components/MigrationSubNav.jsx';
import VerdictLedger from '../components/VerdictLedger.jsx';
import EmptyState from '../components/EmptyState.jsx';
import {
  SearchIcon,
  DownloadIcon,
  XCircleIcon,
  HelpCircleIcon,
  InboxIcon,
  CopyIcon,
  CheckIcon,
  ExternalLinkIcon,
} from '../components/Icons.jsx';
import { useData, useDiscovery } from '../data/useData.jsx';

function download(name, text, type = 'text/csv') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function toCsv(rows) {
  const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const head = ['done', 'path', 'url', 'title', 'decision needed'];
  const body = rows.map((r) =>
    [
      '',
      r.path,
      r.url,
      r.title,
      'no counterpart on the new site — redirect it, rebuild it, or accept the loss',
    ]
      .map(escape)
      .join(',')
  );
  return [head.map(escape).join(','), ...body].join('\n');
}

export default function NotMigrated() {
  const { status } = useData();
  const discovery = useDiscovery();
  const [query, setQuery] = useState('');
  const [copiedUrl, setCopiedUrl] = useState(null);

  const missing = discovery?.notMigrated ?? [];
  const netNew = discovery?.netNew ?? [];
  const unreachable = discovery?.unreachable ?? [];

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return missing;
    return missing.filter(
      (r) =>
        (r.path ?? '').toLowerCase().includes(q) ||
        (r.url ?? '').toLowerCase().includes(q) ||
        (r.title ?? '').toLowerCase().includes(q)
    );
  }, [missing, query]);

  const share = discovery ? Math.round((discovery.migratedShare ?? 0) * 100) : 0;

  function handleCopy(url) {
    if (!url) return;
    navigator.clipboard?.writeText(url);
    setCopiedUrl(url);
    setTimeout(() => setCopiedUrl(null), 1500);
  }

  return (
    <div className="app migration-scope">
      <Header active="migration" crumbs={['Migration Validator', 'Not Migrated']} />
      <div className="page-body">
        <MigrationSubNav />

        {status === 'loading' && <div className="card empty-card">Loading…</div>}

        {status !== 'loading' && !discovery && (
          <EmptyState icon={InboxIcon} title="No Site Crawl Yet">
            <p className="empty-copy">
              This screen needs the discovery step, which enumerates both sites and
              works out which old page became which new one. Run it first:
            </p>
            <code className="code-block">
              python -m src.discover_cli --old OLD_URL --new NEW_URL --out data/run
            </code>
          </EmptyState>
        )}

        {discovery && (
          <div className="stack-32">
            <div className="summary-row">
              <div className="stack-12">
                <div>
                  <h1 className="h1">Not Migrated Pages</h1>
                  <div className="meta-line muted">
                    {discovery.oldRoot} → {discovery.newRoot}
                  </div>
                </div>
              </div>
              {missing.length > 0 && (
                <button
                  type="button"
                  className="btn btn-icon"
                  onClick={() => download('mavditto-not-migrated.csv', toCsv(missing))}
                >
                  <DownloadIcon /> Export List
                </button>
              )}
            </div>

            <VerdictLedger
              lead={{ value: discovery.oldTotal, label: 'old pages found' }}
              segments={[
                {
                  key: 'matched',
                  label: 'Matched to New Site',
                  count: discovery.matched,
                  pct: share,
                  color: 'var(--status-success-text)',
                  Icon: CheckIcon,
                },
                {
                  key: 'missing',
                  label: 'No Counterpart',
                  count: missing.length,
                  pct: 100 - share,
                  color: 'var(--status-danger-text)',
                  Icon: XCircleIcon,
                },
              ]}
            />
            <div className="footnote">
              {share}% of old pages accounted for · {netNew.length} net new page
              {netNew.length === 1 ? '' : 's'} on the new site (not counted above — nothing
              on the old site to compare them to)
            </div>

            {missing.length === 0 ? (
              <div className="card notice notice-good">
                Every old page has a counterpart on the new site.
              </div>
            ) : (
              <>
                <div className="card notice notice-bad">
                  <XCircleIcon size={15} style={{ color: 'var(--status-danger-text)', flex: 'none' }} />
                  <span>
                    <strong>
                      {missing.length} old page{missing.length === 1 ? '' : 's'} have no
                      counterpart on the new site.
                    </strong>{' '}
                    Each needs a decision before launch. These pages cannot appear in the page
                    comparison because there is nothing to compare them against.
                  </span>
                </div>

                {/* Decision Guidance Grid */}
                <div className="guidance-grid">
                  <div className="guidance-card">
                    <span className="guidance-title">
                      <span className="dot" style={{ background: 'var(--accent)' }} /> 301 Redirect
                    </span>
                    <p className="guidance-desc">
                      If content was merged or relocated to an existing new page, add a redirect rule.
                    </p>
                  </div>
                  <div className="guidance-card">
                    <span className="guidance-title">
                      <span className="dot" style={{ background: 'var(--status-warning-text)' }} /> Rebuild in CMS
                    </span>
                    <p className="guidance-desc">
                      If the page was overlooked and is still needed, author it in the new CMS.
                    </p>
                  </div>
                  <div className="guidance-card">
                    <span className="guidance-title">
                      <span className="dot" style={{ background: 'var(--ink-3)' }} /> Retire or Archive
                    </span>
                    <p className="guidance-desc">
                      If the page is outdated, obsolete, or deliberately deprecated, accept the omission.
                    </p>
                  </div>
                </div>

                <div className="controls-row">
                  <div className="stat-tile-label">
                    {visible.length} of {missing.length} unmigrated pages
                  </div>
                  <div className="controls-right">
                    <label className="card search-box">
                      <span className="sr-only">Search by Path, Title, or URL</span>
                      <SearchIcon style={{ color: 'var(--ink-3)', flex: 'none' }} />
                      <input
                        type="search"
                        placeholder="Search by Path, Title, or URL"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                      />
                    </label>
                  </div>
                </div>

                <div className="card table-card">
                  <div className="row-grid row-grid--missing table-head">
                    <span>Path</span>
                    <span>Title</span>
                    <span>Old URL</span>
                    <span className="text-right">Action</span>
                  </div>
                  {visible.map((r) => {
                    const isCopied = copiedUrl === r.url;
                    return (
                      <div className="row-grid row-grid--missing rowline" key={r.url || r.path}>
                        <span className="pathtext" title={r.path}>{r.path}</span>
                        <span className="urltext" title={r.title}>{r.title || '—'}</span>
                        <a
                          href={r.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="urltext urltext--link"
                          title={r.url}
                        >
                          <span>{r.url}</span>
                          <ExternalLinkIcon size={12} className="urltext-icon" />
                        </a>
                        <div className="text-right">
                          <button
                            type="button"
                            className={`btn-action-copy ${isCopied ? 'btn-action-copy--copied' : ''}`}
                            onClick={() => handleCopy(r.url)}
                            title="Copy Old URL"
                          >
                            {isCopied ? (
                              <>
                                <CheckIcon size={12} /> Copied
                              </>
                            ) : (
                              <>
                                <CopyIcon size={12} /> Copy URL
                              </>
                            )}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}

            {unreachable.length > 0 && (
              <div className="card panel">
                <div className="panel-head panel-header-row">
                  <span className="run-title-row">
                    <HelpCircleIcon size={14} style={{ color: 'var(--ink-3)' }} />
                    Listed in Sitemap but Did Not Load ({unreachable.length})
                  </span>
                </div>
                <p className="muted small">
                  A sitemap is a claim, not a guarantee. These were kept out of the content
                  comparison, which would otherwise score an unfetchable page as total loss.
                </p>
                <ul className="plain-list">
                  {unreachable.map((r) => (
                    <li key={`${r.side}-${r.url || r.path}`} className="unreachable-item">
                      <span className="badge-muted">{r.side}</span>{' '}
                      <a href={r.url} target="_blank" rel="noopener noreferrer" className="urltext urltext--link">
                        <span>{r.path || r.url}</span>
                        <ExternalLinkIcon size={11} className="urltext-icon" />
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {netNew.length > 0 && (
              <div className="card panel">
                <div className="panel-head panel-header-row">
                  <span>Net New Pages on New Site ({netNew.length})</span>
                </div>
                <p className="muted small">
                  New pages with nothing on the old site that corresponds. This is expected for newly created site sections.
                </p>
                <div className="net-new-tag-cloud">
                  {netNew.slice(0, 100).map((r) => (
                    <span key={r.url || r.path} className="net-new-tag" title={r.url || r.path}>
                      {r.path || r.url}
                    </span>
                  ))}
                  {netNew.length > 100 && (
                    <span className="net-new-tag" style={{ background: 'transparent', fontStyle: 'italic' }}>
                      +{netNew.length - 100} more
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
