import { AlertCircleIcon, CheckCircleIcon, TriangleAlertIcon } from '../Icons.jsx';

const SCORE_LABELS = {
  voice_match: 'Voice',
  tone_fit: 'Tone fit',
  clarity: 'Clarity',
  fact_fidelity: 'Fact fidelity',
};

function Score({ label, value }) {
  return (
    <div className="cw-score">
      <span className="cw-score-label">{label}</span>
      <span className="cw-score-bar" role="meter" aria-valuemin={1} aria-valuemax={5} aria-valuenow={value}
            aria-label={`${label}: ${value} of 5`}>
        {[1, 2, 3, 4, 5].map((n) => (
          <span key={n} className={`cw-score-seg ${n <= value ? `is-on is-${value >= 4 ? 'good' : value === 3 ? 'mid' : 'bad'}` : ''}`} />
        ))}
      </span>
      <span className="cw-score-num">{value}</span>
    </div>
  );
}

// The review of the draft on screen: scores, rule metrics, what's flagged
// (critical first, click to jump), open brand questions, and the model's
// own notes on which guidelines it applied.
export default function QualityPanel({ review, brandNotes, attempts, unitLabel = 'Section',
  onJump, stale, onRecheck, rechecking }) {
  if (!review) return null;
  const issues = [...review.issues].sort((a, b) => (a.severity === b.severity ? 0 : a.severity === 'critical' ? -1 : 1));
  const m = review.metrics || {};
  const critical = issues.filter((i) => i.severity === 'critical').length;

  return (
    <aside className="card cw-quality" aria-label="Quality review">
      <div className="cw-quality-head">
        {review.passes ? (
          <span className="cw-verdict is-pass"><CheckCircleIcon size={15} /> Meets the brand standard</span>
        ) : (
          <span className="cw-verdict is-fail"><AlertCircleIcon size={15} /> {critical} issue{critical === 1 ? '' : 's'} to fix</span>
        )}
        {stale ? (
          <button type="button" className="btn btn-small" onClick={onRecheck} disabled={rechecking}>
            {rechecking ? 'Checking…' : 'Re-check edits'}
          </button>
        ) : attempts > 1 ? (
          <span className="run-help">Redrafted {attempts - 1}× to clear issues</span>
        ) : null}
      </div>
      {stale && <p className="run-help">You've edited this draft since it was reviewed.</p>}

      {Object.keys(review.scores || {}).length > 0 && (
        <div className="cw-scores">
          {Object.entries(SCORE_LABELS).map(([k, label]) => (
            review.scores[k] != null && <Score key={k} label={label} value={review.scores[k]} />
          ))}
        </div>
      )}

      {m.words > 0 && (
        <dl className="cw-metrics">
          <div><dt>Words</dt><dd>{m.words}</dd></div>
          {m.fk_grade > 0 && (
            <div>
              <dt>Reading grade</dt>
              <dd className={m.target_grade && m.fk_grade > m.target_grade + 2 ? 'is-warn' : ''}>
                {m.fk_grade}{m.target_grade ? ` (target ${m.target_grade})` : ''}
              </dd>
            </div>
          )}
          {m.avg_sentence_words > 0 && <div><dt>Avg sentence</dt><dd>{m.avg_sentence_words} words</dd></div>}
          {m.source_details > 0 && (
            <div>
              <dt>Source details kept</dt>
              <dd className={m.source_details_kept < m.source_details ? 'is-warn' : ''}>
                {m.source_details_kept} of {m.source_details}
              </dd>
            </div>
          )}
          {m.total_blocks > 0 && (
            <div>
              <dt>Placeholders</dt>
              <dd className={m.placeholder_blocks > 0 ? 'is-warn' : ''}>
                {m.placeholder_blocks} of {m.total_blocks} blocks
              </dd>
            </div>
          )}
        </dl>
      )}

      {issues.length > 0 && (
        <div className="stack-8">
          <div className="cw-quality-sub">Flagged</div>
          <ul className="cw-issues">
            {issues.map((i, n) => (
              <li key={n} className={`cw-issue is-${i.severity}`}>
                {i.severity === 'critical'
                  ? <AlertCircleIcon size={13} style={{ color: 'var(--status-danger-text)' }} />
                  : <TriangleAlertIcon size={13} style={{ color: 'var(--status-warning-text)' }} />}
                <div>
                  <div>
                    {i.section != null && (
                      <button type="button" className="cw-link" onClick={() => onJump?.(i.section)}>
                        {unitLabel} {i.section + 1}
                      </button>
                    )}
                    {i.section != null && ': '}
                    {i.message}
                    {i.quote && <q className="cw-quote">{i.quote}</q>}
                  </div>
                  {i.fix && <div className="run-help">{i.fix}</div>}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {review.openQuestions?.length > 0 && (
        <div className="stack-8">
          <div className="cw-quality-sub">Open brand questions</div>
          <ul className="cw-notes">
            {review.openQuestions.map((q, n) => (
              <li key={n}>{q.question} <span className="run-help">Recommendation: {q.recommendation}</span></li>
            ))}
          </ul>
        </div>
      )}

      {brandNotes?.length > 0 && (
        <div className="stack-8">
          <div className="cw-quality-sub">Why it's written this way</div>
          <ul className="cw-notes">
            {brandNotes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </div>
      )}
    </aside>
  );
}
