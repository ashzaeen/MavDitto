import { useCallback, useEffect, useRef, useState } from 'react';
import { useData } from '../data/useData.jsx';
import MascotLoader from './MascotLoader.jsx';
import { AlertCircleIcon, AlertDotIcon, ChevronRightIcon, CompareIcon, SettingsIcon } from './Icons.jsx';

// Paste two URLs and go.
//
// The dashboard was a read-only viewer of a folder someone had already filled
// from a terminal, which makes it unusable by the reviewer it was written for.
// The run happens on the server's own thread; this polls it so the page keeps
// drawing, and reloads the data when it finishes.

const POLL_MS = 1200;

const DEFAULTS = {
  old: '',
  new: '',
  maxPages: 200,
  maxPairs: 50,
  checkLive: true,
  matchTitles: true,
  semantic: true,
  // robots.txt is not consulted unless asked for: staging and preview hosts
  // serve Disallow: / to stay out of search results, not to refuse their owner.
  respectRobots: false,
  judge: false,
  judgeBudget: 1.0,
  deepCrawl: false,
};

export default function RunForm({ startOpen = false, forceOpen = false, onFinished }) {
  const { live, refresh } = useData();
  const [form, setForm] = useState(DEFAULTS);
  const [open, setOpen] = useState(startOpen || forceOpen);
  const [showOptions, setShowOptions] = useState(false);
  const [run, setRun] = useState({ state: 'idle' });
  const [error, setError] = useState('');
  const timer = useRef(null);
  // Guards onFinished so it only fires for a run *this form* just started --
  // starts true (armed against firing) because the very first poll on mount
  // can find an already-finished run left over from before this page ever
  // loaded, and that is not a completion to react to. start() is what makes
  // it eligible, and once it fires it will not fire again on later poll
  // ticks for the same run -- polling keeps going long after completion,
  // until something unmounts this component.
  const firedRef = useRef(true);

  const set = (key) => (event) => {
    const target = event.target;
    setForm((f) => ({
      ...f,
      [key]: target.type === 'checkbox' ? target.checked : target.value,
    }));
  };

  const poll = useCallback(async () => {
    try {
      const response = await fetch('/api/run', { cache: 'no-store' });
      if (!response.ok) return;
      const status = await response.json();
      setRun(status);
      if (status.state === 'finished') {
        // The results folder changed underneath us, so reload rather than
        // leaving the page showing the previous run.
        await refresh();
        if (!firedRef.current && !status.progress?.failed) {
          firedRef.current = true;
          onFinished?.();
        }
      }
    } catch {
      /* server went away; the next poll will find out */
    }
  }, [refresh, onFinished]);

  useEffect(() => {
    if (!live) return undefined;
    poll();
    timer.current = setInterval(poll, POLL_MS);
    return () => clearInterval(timer.current);
  }, [live, poll]);

  const busy = run.state === 'running';

  async function start(event) {
    event.preventDefault();
    setError('');
    if (!form.old.trim() || !form.new.trim()) {
      setError('Both site roots are required.');
      return;
    }
    const normalize = (u) => u.trim().toLowerCase().replace(/\/+$/, '');
    if (normalize(form.old) === normalize(form.new)) {
      setError("Old and new site roots are the same page — there's nothing to compare (it would just report 100% similarity).");
      return;
    }
    firedRef.current = false;
    try {
      const response = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, old: form.old.trim(), new: form.new.trim() }),
      });
      const body = await response.json();
      if (!response.ok) {
        setError(body.error ?? `HTTP ${response.status}`);
        return;
      }
      setRun({ state: 'running' });
      poll();
    } catch (e) {
      setError(String(e));
    }
  }

  async function stop() {
    await fetch('/api/run/cancel', { method: 'POST' });
    poll();
  }

  if (!live) {
    return (
      <div className="card notice notice-muted">
        <AlertDotIcon />
        <span>
          Viewing a static export. To compare two sites from here, serve the
          dashboard with its backend:{' '}
          <code className="code-inline">python -m src.server</code>
        </span>
      </div>
    );
  }

  const progress = run.progress;
  const result = run.result;

  return (
    <div className={`card run-card ${forceOpen ? 'run-card--standalone' : ''}`}>
      {!forceOpen && (
        <button
          type="button"
          className="run-toggle"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          <span className={`run-chevron ${open ? 'open' : ''}`}>
            <ChevronRightIcon size={12} />
          </span>
          Compare Two Sites
          {!open && !busy && <span className="run-hint">paste two root URLs</span>}
        </button>
      )}

      {(open || forceOpen) && (
        <form className="run-form" onSubmit={start}>
          <div className="run-row">
            <label className="run-field">
              <span className="run-label">Old Site Root</span>
              <input
                type="url"
                placeholder="https://old.example.edu"
                value={form.old}
                onChange={set('old')}
                disabled={busy}
              />
            </label>
            <label className="run-field">
              <span className="run-label">New Site Root</span>
              <input
                type="url"
                placeholder="https://example.edu"
                value={form.new}
                onChange={set('new')}
                disabled={busy}
              />
            </label>
          </div>

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
                <span className="run-label">Pages per site</span>
                <input
                  type="number"
                  min="1"
                  max="2000"
                  step="1"
                  value={form.maxPages}
                  onChange={set('maxPages')}
                  disabled={busy}
                />
                <span className="run-help">
                  An unbounded crawl of someone's site is a denial of service with
                  good intentions.
                </span>
              </label>
              <label className="run-field run-field--narrow">
                <span className="run-label">Pairs to compare</span>
                <input
                  type="number"
                  min="1"
                  max="500"
                  step="1"
                  value={form.maxPairs}
                  onChange={set('maxPairs')}
                  disabled={busy}
                />
                <span className="run-help">
                  Comparing content is the slow half. Discovery still covers every
                  page either way.
                </span>
              </label>
              <div className="run-checks">
                <label>
                  <input
                    type="checkbox"
                    checked={form.deepCrawl}
                    onChange={(event) => {
                      const checked = event.target.checked;
                      setForm((f) => ({
                        ...f,
                        deepCrawl: checked,
                        // A depth cap is not exposed as its own field, so
                        // ticking this is also the only way to ask for more
                        // than the quick-run page cap -- bump it, unless the
                        // person already typed something bigger themselves.
                        maxPages: checked
                          ? Math.max(Number(f.maxPages) || 0, 1000)
                          : f.maxPages,
                      }));
                    }}
                    disabled={busy}
                  />
                  Deep, exhaustive crawl
                  <span className="run-inline-help">
                    merges the sitemap with an actual crawl instead of trusting
                    whichever answers first, follows pagination and embedded
                    links, retries pages that failed once, and renders JS for
                    pages that look like empty shells. Slower.
                  </span>
                </label>
                <label>
                  <input type="checkbox" checked={form.checkLive} onChange={set('checkLive')} disabled={busy} />
                  Check every listed page responds
                </label>
                <label>
                  <input type="checkbox" checked={form.matchTitles} onChange={set('matchTitles')} disabled={busy} />
                  Match leftovers by page name
                </label>
                <label>
                  <input type="checkbox" checked={form.semantic} onChange={set('semantic')} disabled={busy} />
                  Compare meaning, not just structure
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={form.judge}
                    onChange={set('judge')}
                    disabled={busy}
                  />
                  Read flagged pages with Claude
                  <span className="run-inline-help">
                    costs money and needs ANTHROPIC_API_KEY on the server. Only
                    flagged pages are read, and only the passages an embedding
                    cannot settle. You can also run it per page from a review.
                  </span>
                </label>
                {form.judge && (
                  <label className="run-field run-field--narrow">
                    <span className="run-label">Spend cap (USD)</span>
                    <input
                      type="number"
                      min="0.05"
                      max="100"
                      step="0.05"
                      value={form.judgeBudget}
                      onChange={set('judgeBudget')}
                      disabled={busy}
                    />
                    <span className="run-help">
                      Checked before every call, so it cannot overrun.
                    </span>
                  </label>
                )}
                <label>
                  <input
                    type="checkbox"
                    checked={form.respectRobots}
                    onChange={set('respectRobots')}
                    disabled={busy}
                  />
                  Respect robots.txt
                  <span className="run-inline-help">
                    off by default — preview and staging hosts disallow crawlers to
                    stay out of search results, not to refuse their owner
                  </span>
                </label>
              </div>
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
              {busy ? 'Running…' : 'Run Comparison'}
            </button>
            {busy && (
              <button type="button" className="btn" onClick={stop}>
                Stop
              </button>
            )}
          </div>
        </form>
      )}

      {progress && (busy || progress.failed) && (
        <div className="run-progress">
          {busy && (
            <MascotLoader
              toolIcon={CompareIcon}
              stage={progress.stage}
              message={progress.message}
              counts={{
                old_pages: progress.old_pages,
                new_pages: progress.new_pages,
                matched: progress.matched,
                not_migrated: progress.not_migrated,
                compared: progress.compared,
              }}
            />
          )}
        </div>
      )}

      {progress?.failed && (
        <div className="run-error">
          <AlertCircleIcon size={14} style={{ color: 'var(--status-danger-text)', flex: 'none' }} />
          <span>{progress.error}</span>
        </div>
      )}

      {run.state === 'finished' && result && !progress?.failed && (
        <div className="run-done">
          Finished — {result.old_pages} old page(s), {result.matched} matched,{' '}
          <strong>{result.not_migrated} with no counterpart</strong>, {result.compared}{' '}
          compared.
          {(result.notes ?? []).map((note, i) => (
            <div className="run-note" key={i}>
              {note}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
