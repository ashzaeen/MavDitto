import { Link } from 'react-router-dom';
import { ChevronRightIcon } from './Icons.jsx';

// One capability, one card: icon + name + one-line description + a Start
// button that jumps straight into that tool's setup screen. Shared by Home's
// curated "Start something new" row and All Tools' exhaustive grid -- same
// card, just more of them there -- see the rehaul doc's All Tools hub section.
export default function ToolCard({ icon: Icon, name, description, to }) {
  return (
    <Link to={to} className="card tool-card">
      <div className="tool-card-icon">
        <Icon size={22} />
      </div>
      <div className="tool-card-body">
        <div className="tool-card-name">{name}</div>
        <div className="tool-card-desc">{description}</div>
      </div>
      <span className="tool-card-start">
        Start <ChevronRightIcon size={11} />
      </span>
    </Link>
  );
}
