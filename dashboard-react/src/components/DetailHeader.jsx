import { Link } from 'react-router-dom';
import { ChevronLeftIcon, ChevronRightIcon } from './Icons.jsx';

// Row detail as a dedicated page, standardized -- see the rehaul doc's "Row
// detail: dedicated pages". PageDetail.jsx already had almost exactly this
// shape (a back-link plus Prev/Page N of M/Next); this generalizes it with a
// breadcrumb on top, so any tool's detail page gets identical chrome for
// free. `meta` is the one page-specific slot (a risk badge and two URLs on
// Migrated Pages).
export default function DetailHeader({ crumbs, backTo, backLabel, meta, index, total, onPrev, onNext }) {
  return (
    <div className="detail-top">
      {crumbs && crumbs.length > 0 && (
        <div className="topbar-crumb" style={{ marginBottom: 8 }}>
          {crumbs.map((c, i) => (
            <span className="crumb-seg" key={i}>
              {i > 0 && <span className="crumb-sep">/</span>}
              {c}
            </span>
          ))}
        </div>
      )}

      <Link to={backTo} className="back-link">
        <ChevronLeftIcon size={12} /> {backLabel}
      </Link>

      <div className="detail-header-row">
        <div className="detail-meta">{meta}</div>
        {total != null && (
          <div className="detail-nav">
            <button type="button" className="btn btn-icon" disabled={index === 0} onClick={onPrev}>
              <ChevronLeftIcon size={12} /> Prev
            </button>
            <span className="page-count">
              {index + 1} of {total}
            </span>
            <button
              type="button"
              className="btn btn-icon"
              disabled={index === total - 1}
              onClick={onNext}
            >
              Next <ChevronRightIcon size={12} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
