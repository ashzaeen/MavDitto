import { useState } from 'react';
import { useData } from '../data/useData.jsx';
import { CommentIcon, CheckIcon, AlertCircleIcon } from './Icons.jsx';

// What the LLM judge is for, and how to run it — from here, not a terminal.
//
// The judge exists because of a measured limit, not as decoration. Embeddings
// score a faithful rewrite and a rewrite that quietly dropped a fact almost
// identically, so passages in that band cannot be settled by any threshold.
// The panel says that plainly, because a "What changed" box that is simply
// empty looks like a feature nobody finished.

const SEVERITY = {
  major: { color: 'var(--status-danger-text)', label: 'Information Is Missing' },
  minor: { color: 'var(--status-warning-text)', label: 'Wording Changed' },
  none: { color: 'var(--status-success-text)', label: 'Nothing Meaningful Changed' },
};

export default function JudgePanel({ page, detail }) {
  const { live, refresh } = useData();
  const [state, setState] = useState({ status: 'idle', error: '' });

  const judged = Boolean(detail.explanation);
  const reworded = (detail.oldDocument ?? [])
    .filter((b) => b.type !== 'heading' && b.verdict === 'reworded');

  async function runJudge() {
    setState({ status: 'running', error: '' });
    try {
      const response = await fetch('/api/judge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: page.id }),
      });
      const body = await response.json();
      if (!response.ok) {
        setState({ status: 'idle', error: body.error ?? `HTTP ${response.status}` });
        return;
      }
      await refresh();
      setState({ status: 'idle', error: '' });
    } catch (e) {
      setState({ status: 'idle', error: String(e) });
    }
  }

  if (judged) {
    const meta = SEVERITY[detail.judgeSeverity] ?? SEVERITY.none;
    return (
      <div className="reviewer-note" style={{ '--reviewer-note-color': meta.color }}>
        <div className="reviewer-note-head">
          <span className="reviewer-note-verdict">{meta.label}</span>
          <span className="judge-by">read by {detail.judgeModel}</span>
        </div>
        <p className="reviewer-note-text">{detail.explanation}</p>

        {detail.factsLost.length > 0 && (
          <ul className="loss-list">
            {detail.factsLost.map((f, i) => (
              <li key={i}>
                <strong>{f.section || 'passage'}</strong> — {f.detail}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <div className="card section-card judge-offer">
      <div className="section-head">
        <h2 className="section-title">
          <CommentIcon size={15} style={{ color: 'var(--ink-3)' }} /> What changed
        </h2>
      </div>

      {reworded.length > 0 ? (
        <p className="judge-text">
          <strong>
            {reworded.length} passage{reworded.length === 1 ? '' : 's'} on this page
            {reworded.length === 1 ? ' was' : ' were'} rewritten.
          </strong>{' '}
          Nothing here can tell you whether those rewrites kept their facts. A
          faithful paraphrase and one that quietly dropped a requirement score
          almost the same to an embedding — that overlap is measured, not
          assumed. Reading them is what the judge is for.
        </p>
      ) : (
        <p className="judge-text">
          No passage on this page was rewritten in a way that needs reading — the
          text either survived or it did not, and both are already shown below.
          The judge is still useful for a summary you can paste into a ticket.
        </p>
      )}

      {live ? (
        <>
          <button
            type="button"
            className="btn btn-primary"
            onClick={runJudge}
            disabled={state.status === 'running'}
          >
            {state.status === 'running' ? 'Reading the page…' : 'Read this page with Claude'}
          </button>
          <p className="judge-cost">
            One API call for this page. Costs money and needs
            <code className="code-inline">ANTHROPIC_API_KEY</code> on the server.
          </p>
        </>
      ) : (
        <p className="judge-cost">
          Serve the dashboard with <code className="code-inline">python -m src.server</code>{' '}
          to run the judge from here.
        </p>
      )}

      {state.error && (
        <div className="run-error">
          <AlertCircleIcon size={13} style={{ color: 'var(--status-danger-text)', flex: 'none' }} />{' '}
          {state.error}
        </div>
      )}
    </div>
  );
}
