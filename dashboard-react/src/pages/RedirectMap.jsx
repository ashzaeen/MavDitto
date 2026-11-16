import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import Header from '../components/Header.jsx';
import MigrationSubNav from '../components/MigrationSubNav.jsx';
import VerdictLedger from '../components/VerdictLedger.jsx';
import EmptyState from '../components/EmptyState.jsx';
import {
  DownloadIcon,
  CheckIcon,
  HelpCircleIcon,
  InboxIcon,
  SearchIcon,
  CopyIcon,
  ExternalLinkIcon,
} from '../components/Icons.jsx';
import { useRedirects } from '../data/useData.jsx';

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function toCsv(rows) {
  const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const head = ['old_url', 'new_url', 'type', 'status'];
  const body = rows.map((r) => [r.oldUrl, r.newUrl, r.type, r.status].map(escape).join(','));
  return [head.map(escape).join(','), ...body].join('\n');
}

export default function RedirectMap() {
  const REDIRECT_ROWS = useRedirects();
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [copiedKey, setCopiedKey] = useState(null);

  const matchedCount = useMemo(
    () => REDIRECT_ROWS.filter((r) => r.status === 'matched').length,
    [REDIRECT_ROWS]
  );
  const needsReviewCount = useMemo(
    () => REDIRECT_ROWS.filter((r) => r.status !== 'matched').length,
    [REDIRECT_ROWS]
  );

  const visibleRows = useMemo(() => {
    let rows = REDIRECT_ROWS;
    if (statusFilter === 'matched') {
      rows = rows.filter((r) => r.status === 'matched');
    } else if (statusFilter === 'review') {
      rows = rows.filter((r) => r.status !== 'matched');
    }

    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        (r.oldUrl ?? '').toLowerCase().includes(q) ||
        (r.newUrl ?? '').toLowerCase().includes(q) ||
        (r.type ?? '').toLowerCase().includes(q)
    );
  }, [REDIRECT_ROWS, statusFilter, query]);

  function handleCopyRule(row) {
    const key = `${row.oldUrl}|${row.newUrl}`;
    const oldPath = (() => {
      try {
        return new URL(row.oldUrl).pathname;
      } catch {
        return row.oldUrl;
      }
    })();
    const target = row.newUrl || '/';
    const rule = `Redirect 301 ${oldPath} ${target}`;
    navigator.clipboard?.writeText(rule);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 1500);
  }

  return (
    <div className="app migration-scope">
      <Header active="migration" crumbs={['Migration Validator', 'Redirect Map']} />
      <div className="page-body">
        <MigrationSubNav />

        <div className="summary-row">
          <div>
            <h1 className="h1">Redirect Map</h1>
            <div className="meta-line muted">
              Auto-discovered source-to-destination URL pairings for 301 redirect rules.
            </div>
          </div>
          {REDIRECT_ROWS.length > 0 && (
            <button
              type="button"
              className="btn btn-icon"
              onClick={() => download('mavditto-redirects.csv', toCsv(REDIRECT_ROWS))}
            >
              <DownloadIcon /> Export Redirect Map
            </button>
          )}
        </div>

        {REDIRECT_ROWS.length === 0 ? (
          <EmptyState icon={InboxIcon} title="No Redirects Discovered Yet">
            <p className="empty-copy">
              This screen fills in once a Migration Validator run has crawled
              both sites — run one first:
            </p>
            <Link to="/migration" className="btn btn-primary">
              Go to Migration Validator
            </Link>
          </EmptyState>
        ) : (
          <div className="stack-32">
            <VerdictLedger
              lead={{ value: REDIRECT_ROWS.length, label: 'redirect rules' }}
              segments={[
                {
                  key: 'matched',
                  label: 'Auto-Matched',
                  count: matchedCount,
                  pct: Math.round((matchedCount / REDIRECT_ROWS.length) * 100),
                  color: 'var(--status-success-text)',
                  Icon: CheckIcon,
                },
                {
                  key: 'review',
                  label: 'Needs Review',
                  count: needsReviewCount,
                  pct: Math.round((needsReviewCount / REDIRECT_ROWS.length) * 100),
                  color: 'var(--status-warning-text)',
                  Icon: HelpCircleIcon,
                },
              ]}
            />

            {/* Controls: Filter chips + Search */}
            <div className="controls-row">
              <div className="chip-row">
                <button
                  type="button"
                  className={`chip ${statusFilter === 'all' ? 'active' : ''}`}
                  onClick={() => setStatusFilter('all')}
                >
                  All ({REDIRECT_ROWS.length})
                </button>
                <button
                  type="button"
                  className={`chip ${statusFilter === 'matched' ? 'active' : ''}`}
                  onClick={() => setStatusFilter('matched')}
                >
                  <span className="dot" style={{ background: 'var(--status-success-text)' }} />
                  Auto-Matched ({matchedCount})
                </button>
                <button
                  type="button"
                  className={`chip ${statusFilter === 'review' ? 'active' : ''}`}
                  onClick={() => setStatusFilter('review')}
                >
                  <span className="dot" style={{ background: 'var(--status-warning-text)' }} />
                  Needs Review ({needsReviewCount})
                </button>
              </div>
              <div className="controls-right">
                <label className="card search-box">
                  <span className="sr-only">Search by Old or New URL</span>
                  <SearchIcon style={{ color: 'var(--ink-3)', flex: 'none' }} />
                  <input
                    type="search"
                    placeholder="Search by Old or New URL"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
              </div>
            </div>

            {/* Redirect Table */}
            <div className="card table-card">
              <div className="row-grid row-grid--redirect table-head">
                <span>Old URL (Source)</span>
                <span>New URL (Destination)</span>
                <span>Type</span>
                <span>Status</span>
                <span className="text-right">Action</span>
              </div>
              {visibleRows.map((r) => {
                const key = `${r.oldUrl}|${r.newUrl}`;
                const isCopied = copiedKey === key;
                return (
                  <div className="row-grid row-grid--redirect rowline" key={key}>
                    <div className="redirect-url-cell">
                      <a
                        href={r.oldUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="urltext urltext--link"
                        title={r.oldUrl}
                      >
                        <span>{r.oldUrl}</span>
                        <ExternalLinkIcon size={11} className="urltext-icon" />
                      </a>
                    </div>

                    <div className="redirect-url-cell">
                      <span className="redirect-arrow">➔</span>
                      {r.newUrl ? (
                        <a
                          href={r.newUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="urltext urltext--link"
                          title={r.newUrl}
                        >
                          <span>{r.newUrl}</span>
                          <ExternalLinkIcon size={11} className="urltext-icon" />
                        </a>
                      ) : (
                        <span className="urltext muted" style={{ fontStyle: 'italic' }}>
                          No destination found
                        </span>
                      )}
                    </div>

                    <span className="type-cell">
                      <span className="badge-muted">{r.type || 'direct'}</span>
                    </span>

                    <div>
                      {r.status === 'matched' ? (
                        <span className="badge badge-good" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          <CheckIcon size={11} /> Auto-Matched
                        </span>
                      ) : (
                        <span className="badge badge-warn" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          <HelpCircleIcon size={11} /> Needs Review
                        </span>
                      )}
                    </div>

                    <div className="text-right">
                      <button
                        type="button"
                        className={`btn-action-copy ${isCopied ? 'btn-action-copy--copied' : ''}`}
                        onClick={() => handleCopyRule(r)}
                        title="Copy Apache/Nginx 301 redirect rule"
                      >
                        {isCopied ? (
                          <>
                            <CheckIcon size={11} /> Copied
                          </>
                        ) : (
                          <>
                            <CopyIcon size={11} /> Copy 301 Rule
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="footnote">
              Showing {visibleRows.length} of {REDIRECT_ROWS.length} redirect rules
              {needsReviewCount > 0 && ` · ${needsReviewCount} require manual decision`}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
