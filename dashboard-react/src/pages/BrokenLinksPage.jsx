import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Header from '../components/Header.jsx';
import { useData } from '../data/useData.jsx';
import { useLinkScan } from '../data/useLinkScan.jsx';
import LinkStatusBadge from '../components/LinkStatusBadge.jsx';
import MascotLoader from '../components/MascotLoader.jsx';
import {
  AlertCircleIcon, AlertDotIcon, ChevronDownIcon, DownloadIcon, SearchIcon,
  SettingsIcon, LinkIcon,
} from '../components/Icons.jsx';
import {
  CATEGORY_LABELS, CATEGORY_ORDER, REGION_LABELS, STATUS_SEVERITY,
  LINK_STATUS_META, REVIEW_STATES, REVIEW_BY_KEY,
} from '../data/linkStatusMeta.js';
import { useTheme } from '../ThemeContext.jsx';

// The Broken Link Inspector: a link-health audit for one page (Page Scan) or
// a whole subsite (Site Scan), independent of the migration-comparison
// pipeline. Both modes end in the same shape -- {rootUrl, pagesCrawled,
// links, summary} -- so one ResultsView renders whichever one just finished.

const POLL_MS = 1200;

function toCsv(links, reviewOf) {
  const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const head = ['url', 'status', 'http code', 'review', 'redirects to', 'category', 'region',
    'link text', 'found on pages'];
  const body = links.map((l) => [
    l.url, l.status, l.httpCode ?? '',
    l.status === 'ok' ? '' : REVIEW_BY_KEY[reviewOf(l.url).state].label,
    l.status === 'redirected' ? l.finalUrl : '',
    CATEGORY_LABELS[l.category] ?? l.category,
    REGION_LABELS[l.region] ?? l.region, l.text, l.foundOn.join(' | '),
  ].map(escape).join(','));
  return [head.map(escape).join(','), ...body].join('\n');
}

// Review decisions live in this browser only, keyed by link URL so they
// survive a rescan -- scans themselves are never persisted server-side.
const REVIEW_STORAGE_KEY = 'mavditto.linkReview.v1';
const UNREVIEWED = { state: 'not_reviewed', at: 0 };

function readReviews() {
  try {
    const parsed = JSON.parse(localStorage.getItem(REVIEW_STORAGE_KEY) || '{}');
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function useLinkReview() {
  const [reviews, setReviews] = useState(readReviews);

  const reviewOf = useCallback((url) => {
    const r = reviews[url];
    return r && REVIEW_BY_KEY[r.state] ? r : UNREVIEWED;
  }, [reviews]);

  const setReview = useCallback((url, state) => {
    setReviews((prev) => {
      const next = { ...prev };
      if (state === 'not_reviewed') delete next[url];
      else next[url] = { state, at: Date.now() };
      try {
        localStorage.setItem(REVIEW_STORAGE_KEY, JSON.stringify(next));
      } catch {
        /* storage blocked or full; the choice still holds for this session */
      }
      return next;
    });
  }, []);

  return { reviewOf, setReview };
}

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function RegionCheckboxes({ includeHeader, setIncludeHeader, includeNav, setIncludeNav,
                           includeFooter, setIncludeFooter, disabled }) {
  return (
    <div className="run-checks">
      <label>
        <input type="checkbox" checked={includeHeader} disabled={disabled}
              onChange={(e) => setIncludeHeader(e.target.checked)} />
        Header
        <span className="run-inline-help">Links inside the site masthead.</span>
      </label>
      <label>
        <input type="checkbox" checked={includeNav} disabled={disabled}
              onChange={(e) => setIncludeNav(e.target.checked)} />
        Navbar
        <span className="run-inline-help">Links inside the main site navigation.</span>
      </label>
      <label>
        <input type="checkbox" checked={includeFooter} disabled={disabled}
              onChange={(e) => setIncludeFooter(e.target.checked)} />
        Footer
        <span className="run-inline-help">
          Footer links, including prefooter call-to-action blocks.
        </span>
      </label>
    </div>
  );
}

// --- Page Scan -------------------------------------------------------------

function PageScanPanel({ onResult }) {
  const [url, setUrl] = useState('');
  const [showOptions, setShowOptions] = useState(false);
  const [includeHeader, setIncludeHeader] = useState(false);
  const [includeNav, setIncludeNav] = useState(false);
  const [includeFooter, setIncludeFooter] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function run(event) {
    event.preventDefault();
    if (!url.trim()) {
      setError('A page URL is required.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      onResult(null);
      const response = await fetch('/api/link-check/page', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: url.trim(), includeHeader, includeNav, includeFooter,
        }),
      });
      const body = await response.json();
      if (!response.ok) {
        setError(body.error ?? `HTTP ${response.status}`);
        return;
      }
      onResult(body);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack-16">
      <form className="run-form" style={{ borderTop: 0, padding: 0 }} onSubmit={run}>
        <label className="run-field">
          <span className="run-label">Page URL</span>
          <input
            type="url"
            placeholder="https://www.uta.edu/admissions/apply"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={busy}
          />
        </label>

        <button
          type="button"
          className="btn btn-icon btn-small run-options-toggle"
          onClick={() => setShowOptions((v) => !v)}
        >
          <SettingsIcon size={12} />
          {showOptions ? 'Hide Options' : 'Options'}
        </button>

        {showOptions && (
          <div className="run-options">
            <RegionCheckboxes
              includeHeader={includeHeader} setIncludeHeader={setIncludeHeader}
              includeNav={includeNav} setIncludeNav={setIncludeNav}
              includeFooter={includeFooter} setIncludeFooter={setIncludeFooter}
              disabled={busy}
            />
          </div>
        )}

        {error && (
          <div className="run-error">
            <AlertCircleIcon size={14} style={{ color: 'var(--status-danger-text)', flex: 'none' }} />
            <span>{error}</span>
          </div>
        )}

        <div className="run-actions">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? 'Scanning…' : 'Scan Page'}
          </button>
        </div>
      </form>

      {busy && (
        <MascotLoader
          toolIcon={LinkIcon}
          indeterminateMessages={[
            'Extracting every link on the page…',
            'Checking where each link leads…',
            'Almost done…',
          ]}
        />
      )}
    </div>
  );
}

// --- Site Scan ---------------------------------------------------------------

function SiteScanPanel({ onResult }) {
  const [url, setUrl] = useState('');
  const [showOptions, setShowOptions] = useState(false);
  const [maxPages, setMaxPages] = useState(500);
  const [includeHeader, setIncludeHeader] = useState(false);
  const [includeNav, setIncludeNav] = useState(false);
  const [includeFooter, setIncludeFooter] = useState(false);
  const [error, setError] = useState('');
  const [job, setJob] = useState({ state: 'idle' });
  const timer = useRef(null);
  const firedRef = useRef(true);

  const poll = useCallback(async () => {
    try {
      const response = await fetch('/api/link-check/site', { cache: 'no-store' });
      if (!response.ok) return;
      const status = await response.json();
      setJob(status);
      if (status.state === 'finished' && !firedRef.current) {
        firedRef.current = true;
        if (!status.progress?.failed) onResult(status.result);
      }
    } catch {
      /* server went away; the next poll will find out */
    }
  }, [onResult]);

  useEffect(() => {
    timer.current = setInterval(poll, POLL_MS);
    poll();
    return () => clearInterval(timer.current);
  }, [poll]);

  const busy = job.state === 'running';

  async function start(event) {
    event.preventDefault();
    setError('');
    if (!url.trim()) {
      setError('A starting URL is required.');
      return;
    }
    firedRef.current = false;
    onResult(null);
    try {
      const response = await fetch('/api/link-check/site', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: url.trim(), maxPages, includeHeader, includeNav, includeFooter,
        }),
      });
      const body = await response.json();
      if (!response.ok) {
        setError(body.error ?? `HTTP ${response.status}`);
        return;
      }
      setJob({ state: 'running' });
      poll();
    } catch (e) {
      setError(String(e));
    }
  }

  async function stop() {
    await fetch('/api/link-check/site/cancel', { method: 'POST' });
    poll();
  }

  const progress = job.progress;

  return (
    <div className="stack-16">
      <form className="run-form" style={{ borderTop: 0, padding: 0 }} onSubmit={start}>
        <label className="run-field">
          <span className="run-label">Starting URL</span>
          <input
            type="url"
            placeholder="https://www.uta.edu/admissions/"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={busy}
          />
          <span className="run-help">
            Crawls every page nested under this URL's path, then checks every
            link found anywhere along the way — including ones pointing
            outside this section entirely.
          </span>
        </label>

        <button
          type="button"
          className="btn btn-icon btn-small run-options-toggle"
          onClick={() => setShowOptions((v) => !v)}
        >
          <SettingsIcon size={12} />
          {showOptions ? 'Hide Options' : 'Options'}
        </button>

        {showOptions && (
          <div className="run-options">
            <label className="run-field run-field--narrow">
              <span className="run-label">Page Cap</span>
              <input
                type="number" min="1" max="5000" step="1"
                value={maxPages}
                onChange={(e) => setMaxPages(Number(e.target.value))}
                disabled={busy}
              />
              <span className="run-help">
                Maximum number of nested pages to crawl.
              </span>
            </label>
            <RegionCheckboxes
              includeHeader={includeHeader} setIncludeHeader={setIncludeHeader}
              includeNav={includeNav} setIncludeNav={setIncludeNav}
              includeFooter={includeFooter} setIncludeFooter={setIncludeFooter}
              disabled={busy}
            />
          </div>
        )}

        {error && (
          <div className="run-error">
            <AlertCircleIcon size={14} style={{ color: 'var(--status-danger-text)', flex: 'none' }} />
            <span>{error}</span>
          </div>
        )}

        <div className="run-actions">
          {busy ? (
            <button type="button" className="btn" onClick={stop}>Stop</button>
          ) : (
            <button type="submit" className="btn btn-primary">Scan Site</button>
          )}
        </div>
      </form>

      {busy && progress && (
        <MascotLoader
          toolIcon={LinkIcon}
          stage={progress.stage}
          message={progress.message}
          badges={progress.total > 0
            ? [{ key: 'progress', value: `${progress.done}/${progress.total}`, label: 'Checked' }]
            : []}
        />
      )}

      {job.state === 'finished' && job.progress?.failed && (
        <div className="run-error">
          <AlertCircleIcon size={14} style={{ color: 'var(--status-danger-text)', flex: 'none' }} />
          <span>{job.progress.error || 'The scan stopped before finishing.'}</span>
        </div>
      )}
    </div>
  );
}

// --- results -----------------------------------------------------------------

const hostOf = (u) => {
  try {
    return new URL(u).host.replace(/^www\./, '');
  } catch {
    return '';
  }
};

// A found-on page as the shortest label that still identifies it: its path
// when it's on the same site as the scan root, the host + path otherwise.
function pageLabel(pageUrl, rootHost) {
  try {
    const u = new URL(pageUrl);
    let path = u.pathname + u.search;
    try {
      path = decodeURI(path);
    } catch {
      /* keep the encoded form */
    }
    return u.host.replace(/^www\./, '') === rootHost ? path : `${u.host}${path}`;
  } catch {
    return pageUrl;
  }
}

function ReviewSelect({ link, review, onChange, stale }) {
  const meta = REVIEW_BY_KEY[review.state];
  return (
    <div className="review-cell">
      <label className={`review-pill review-pill--${meta.tone}`}>
        <span className="review-pill-dot" aria-hidden="true" />
        <select
          value={review.state}
          onChange={(e) => onChange(link.url, e.target.value)}
          aria-label={`Review status for ${link.url}`}
        >
          {REVIEW_STATES.map((s) => (
            <option key={s.key} value={s.key}>{s.label}</option>
          ))}
        </select>
        <ChevronDownIcon size={12} className="review-pill-chevron" />
      </label>
      {stale && <span className="review-stale">Still Failing on Latest Scan</span>}
    </div>
  );
}

function LinkRow({ link, isSite, rootHost, review, onReview, scannedAt }) {
  const [pagesOpen, setPagesOpen] = useState(false);
  const reviewMeta = REVIEW_BY_KEY[review.state];
  const needsReview = link.status !== 'ok';
  const stale = needsReview && (review.state === 'fixed' || review.state === 'removed')
    && review.at < scannedAt;
  const hops = link.redirectChain?.length ?? 0;
  const pages = link.foundOn ?? [];
  const regionLabel = link.region ? REGION_LABELS[link.region] ?? link.region : '';

  return (
    <div
      className={`row-grid row-grid--links ${isSite ? 'row-grid--links-site' : ''} rowline ${
        needsReview && reviewMeta.resolved ? 'rowline--resolved' : ''}`}
    >
      <div className="link-cell">
        <a href={link.url} target="_blank" rel="noopener noreferrer" className="link-url">
          {link.url}
        </a>
        {(link.text || regionLabel) && (
          <div className="link-meta">
            {regionLabel && <span className="region-tag">{regionLabel}</span>}
            {link.text && <span className="link-text" title={link.text}>{link.text}</span>}
          </div>
        )}
        {link.status === 'redirected' && link.finalUrl && (
          <div className="link-redirect">
            Redirects to{' '}
            <a href={link.finalUrl} target="_blank" rel="noopener noreferrer">{link.finalUrl}</a>
            {hops > 1 && <span className="muted"> via {hops} hops</span>}
          </div>
        )}
        {link.error && <div className="link-error">{link.error}</div>}
      </div>

      <div className="link-status-cell">
        <LinkStatusBadge status={link.status} />
        {link.httpCode != null && link.httpCode !== 200 && (
          <span className="status-code">HTTP {link.httpCode}</span>
        )}
      </div>

      {isSite && (
        <div className="found-on-cell">
          {pages.length === 1 ? (
            <a href={pages[0]} target="_blank" rel="noopener noreferrer" title={pages[0]}
               className="found-on-single">
              {pageLabel(pages[0], rootHost)}
            </a>
          ) : (
            <button
              type="button"
              className="found-on-toggle"
              aria-expanded={pagesOpen}
              onClick={() => setPagesOpen((v) => !v)}
            >
              {pages.length} Pages
              <ChevronDownIcon size={12} />
            </button>
          )}
        </div>
      )}

      <div className="review-col">
        {needsReview && (
          <ReviewSelect link={link} review={review} onChange={onReview} stale={stale} />
        )}
      </div>

      {isSite && pagesOpen && pages.length > 1 && (
        <div className="found-on-panel">
          <span className="found-on-panel-title">Found on {pages.length} pages</span>
          <ul>
            {pages.map((p) => (
              <li key={p}>
                <a href={p} target="_blank" rel="noopener noreferrer" title={p}>
                  {pageLabel(p, rootHost)}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

const byWorstFirst = (a, b) =>
  (STATUS_SEVERITY[a.status] ?? 99) - (STATUS_SEVERITY[b.status] ?? 99)
  || a.url.localeCompare(b.url);

function ResultsView({ scanResult }) {
  const { theme } = useTheme();
  const { reviewOf, setReview } = useLinkReview();
  const links = useMemo(() => scanResult?.links ?? [], [scanResult]);
  const isSite = scanResult.mode === 'site';
  const rootHost = hostOf(scanResult.rootUrl);
  const problems = useMemo(() => links.filter((l) => l.status !== 'ok'), [links]);

  const [statusFilter, setStatusFilter] = useState(problems.length ? 'attention' : 'all');
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [regionFilter, setRegionFilter] = useState('all');
  const [reviewFilter, setReviewFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [scannedAt] = useState(() => Date.now());
  const rootRef = useRef(null);

  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    rootRef.current?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
  }, []);

  const filtered = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return links.filter((l) => {
      if (statusFilter === 'attention' && l.status === 'ok') return false;
      if (statusFilter !== 'all' && statusFilter !== 'attention' && l.status !== statusFilter) {
        return false;
      }
      if (categoryFilter !== 'all' && l.category !== categoryFilter) return false;
      if (regionFilter !== 'all' && (l.region || '') !== regionFilter) return false;
      if (reviewFilter !== 'all') {
        if (l.status === 'ok') return false;
        const state = reviewOf(l.url).state;
        if (reviewFilter === 'open') {
          if (state !== 'not_reviewed' && state !== 'needs_fix') return false;
        } else if (state !== reviewFilter) {
          return false;
        }
      }
      if (q) {
        const matchesUrl = l.url?.toLowerCase().includes(q);
        const matchesText = l.text?.toLowerCase().includes(q);
        if (!matchesUrl && !matchesText) return false;
      }
      return true;
    });
  }, [links, statusFilter, categoryFilter, regionFilter, reviewFilter, searchQuery, reviewOf]);

  // Categories holding a problem first, then the rest, each in the standard order.
  const groups = useMemo(() => {
    const out = CATEGORY_ORDER
      .map((c) => ({ category: c, rows: filtered.filter((l) => l.category === c).sort(byWorstFirst) }))
      .filter((g) => g.rows.length);
    const hasProblem = (g) => g.rows.some((l) => l.status !== 'ok');
    return [...out.filter(hasProblem), ...out.filter((g) => !hasProblem(g))];
  }, [filtered]);

  const statusCounts = useMemo(() => {
    const counts = {};
    for (const l of links) counts[l.status] = (counts[l.status] ?? 0) + 1;
    return counts;
  }, [links]);

  const statusesPresent = Object.keys(statusCounts).sort(
    (a, b) => (STATUS_SEVERITY[a] ?? 99) - (STATUS_SEVERITY[b] ?? 99)
  );

  const reviewedCount = problems.filter((l) => reviewOf(l.url).state !== 'not_reviewed').length;
  const breakdown = statusesPresent
    .filter((s) => s !== 'ok')
    .map((s) => `${statusCounts[s]} ${(LINK_STATUS_META[s]?.label ?? s).toLowerCase()}`)
    .join(', ');
  const pagesCrawled = scanResult.pagesCrawled?.length ?? 0;

  return (
    <div className="stack-16 links-results" ref={rootRef}>
      <h2 className="section-title">Checked Links</h2>

      <div className="links-summary" aria-live="polite">
        <p className="links-summary-line">
          {links.length} link{links.length === 1 ? '' : 's'}
          {isSite
            ? ` on ${pagesCrawled} page${pagesCrawled === 1 ? '' : 's'}. `
            : <> on <a href={scanResult.rootUrl} target="_blank" rel="noopener noreferrer">{scanResult.rootUrl}</a>. </>}
          {problems.length
            ? <strong>{problems.length} need{problems.length === 1 ? 's' : ''} attention: {breakdown}.</strong>
            : 'Every link checked out.'}
        </p>
        {problems.length > 0 && (
          <div className="review-progress">
            <div
              className="review-progress-track"
              role="progressbar"
              aria-label="Links reviewed"
              aria-valuemin={0}
              aria-valuemax={problems.length}
              aria-valuenow={reviewedCount}
            >
              <span style={{ width: `${(reviewedCount / problems.length) * 100}%` }} />
            </div>
            <span className="muted small">{reviewedCount} of {problems.length} reviewed</span>
          </div>
        )}
        {scanResult.truncated && (
          <div className="links-notice">
            <AlertCircleIcon size={14} style={{ flex: 'none' }} />
            <span>The page cap was reached, so the crawl stopped early. Raise the Page Cap under Options to cover the rest.</span>
          </div>
        )}
      </div>

      {links.length === 0 ? (
        <div className="card empty-card">
          <p className="muted">No links were found on this page. Check that the URL points at a page with content.</p>
        </div>
      ) : (
        <>
          <div className="chip-row">
            {problems.length > 0 && (
              <button
                type="button"
                className={`chip ${statusFilter === 'attention' ? 'active' : ''}`}
                onClick={() => setStatusFilter('attention')}
              >
                Needs Attention ({problems.length})
              </button>
            )}
            <button
              type="button"
              className={`chip ${statusFilter === 'all' ? 'active' : ''}`}
              onClick={() => setStatusFilter('all')}
            >
              All ({links.length})
            </button>
            {statusesPresent.map((s) => {
              const meta = LINK_STATUS_META[s];
              const dotColor = meta ? meta[theme === 'dark' ? 'dark' : 'light'].text : 'var(--ink)';
              return (
                <button
                  key={s}
                  type="button"
                  className={`chip ${statusFilter === s ? 'active' : ''}`}
                  onClick={() => setStatusFilter(s)}
                >
                  <span className="dot" style={{ background: dotColor }} />
                  {meta ? meta.label : s} ({statusCounts[s]})
                </button>
              );
            })}
          </div>

          <div className="links-toolbar">
            <label className="card search-box">
              <span className="sr-only">Search Links</span>
              <SearchIcon size={13} style={{ color: 'var(--ink-3)', flex: 'none' }} />
              <input
                type="search"
                placeholder="Search by URL or text…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </label>

            <select
              className="select-filter"
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              aria-label="Filter by category"
            >
              <option value="all">All Categories</option>
              {CATEGORY_ORDER.map((c) => {
                const cnt = links.filter((l) => l.category === c).length;
                if (cnt === 0) return null;
                return <option key={c} value={c}>{CATEGORY_LABELS[c]} ({cnt})</option>;
              })}
            </select>

            <select
              className="select-filter"
              value={regionFilter}
              onChange={(e) => setRegionFilter(e.target.value)}
              aria-label="Filter by region"
            >
              <option value="all">All Regions</option>
              {Object.entries(REGION_LABELS).map(([value, label]) => {
                const cnt = links.filter((l) => (l.region || '') === value).length;
                if (cnt === 0) return null;
                return <option key={value || 'main'} value={value}>{label} ({cnt})</option>;
              })}
            </select>

            {problems.length > 0 && (
              <select
                className="select-filter"
                value={reviewFilter}
                onChange={(e) => setReviewFilter(e.target.value)}
                aria-label="Filter by review status"
              >
                <option value="all">All Reviews</option>
                <option value="open">Still to Review</option>
                {REVIEW_STATES.map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
            )}

            <button
              type="button"
              className="btn btn-icon links-export"
              disabled={filtered.length === 0}
              onClick={() => download('mavditto-broken-links.csv', toCsv(filtered, reviewOf))}
            >
              <DownloadIcon /> Export CSV
            </button>
          </div>

          {filtered.length === 0 ? (
            <div className="card empty-card">
              <p className="muted">No links match these filters. Clear the search or pick All to see everything.</p>
            </div>
          ) : (
            <div className="stack-16">
              {groups.map(({ category, rows }) => (
                <details key={category} className="card table-card link-category" open>
                  <summary className="link-category-summary">
                    <span>{CATEGORY_LABELS[category]}</span>
                    <span className="count-pill">{rows.length}</span>
                  </summary>
                  <div
                    className={`row-grid row-grid--links ${isSite ? 'row-grid--links-site' : ''} table-head`}
                  >
                    <span>Link</span>
                    <span>Status</span>
                    {isSite && <span>Found On</span>}
                    <span>Review</span>
                  </div>
                  {rows.map((l) => (
                    <LinkRow
                      key={l.url}
                      link={l}
                      isSite={isSite}
                      rootHost={rootHost}
                      review={reviewOf(l.url)}
                      onReview={setReview}
                      scannedAt={scannedAt}
                    />
                  ))}
                </details>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// --- the page ----------------------------------------------------------------

const MODES = [
  { key: 'page', label: 'Page Scan' },
  { key: 'site', label: 'Site Scan' },
];

export default function BrokenLinksPage() {
  const { live } = useData();
  const { scan: result, setScan: setResult } = useLinkScan();
  const [mode, setMode] = useState('page');

  return (
    <div className="app">
      <Header active="broken-links" crumbs={['Broken Link Inspector']} />
      <div className="page-body">
        <div>
          <h1 className="h1">Broken Link Inspector</h1>
          <div className="meta-line muted">
            Scan a page or a whole subsite for broken, redirected, or restricted
            links, including anchors, documents, and media.
          </div>
        </div>

        {!live ? (
          <div className="card notice notice-muted">
            <AlertDotIcon />
            <span>
              Viewing a static export. To run live link checks, serve the
              dashboard with its backend:{' '}
              <code className="code-inline">python -m src.server</code>
            </span>
          </div>
        ) : (
          <div className="stack-32">
            <div className="card run-card">
              <div className="run-form run-form--top-level">
                <div className="chip-row">
                  {MODES.map((m) => (
                    <button
                      key={m.key}
                      type="button"
                      className={`chip ${mode === m.key ? 'active' : ''}`}
                      onClick={() => setMode(m.key)}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>
                {mode === 'page' ? (
                  <PageScanPanel onResult={setResult} />
                ) : (
                  <SiteScanPanel onResult={setResult} />
                )}
              </div>
            </div>

            {result && <ResultsView scanResult={result} />}
          </div>
        )}
      </div>
    </div>
  );
}
