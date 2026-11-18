import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  MoonIcon,
  SunIcon,
  HomeIcon,
  CompareIcon,
  ImageIcon,
  LinkIcon,
  GridIcon,
  SearchIcon,
  PencilIcon,
  BuilderIcon,
  SparklesIcon,
  SettingsIcon,
} from './Icons.jsx';
import LlmConfigModal from './LlmConfigModal.jsx';
import { useTheme } from '../ThemeContext.jsx';

// The app shell: a persistent left icon rail (one icon per whole tool, never
// per view -- see docs/design/ux-rehaul.md)
// plus a slim top bar (breadcrumb, search, theme toggle, a contextual primary
// action slot). Both barely change shape no matter which tool is open, so
// switching tools never feels like landing in a different app.
//
// `active` is rail-icon-level: 'home' | 'migration' | 'alt-text' |
// 'broken-links' | 'content-writer' | 'web-builder' | 'all-tools' | null
// (null on a sub-view that sets its own crumbs without highlighting a rail
// icon, e.g. a row detail page).

const RAIL_ITEMS = [
  { key: 'home', to: '/', icon: HomeIcon, label: 'Home' },
  { key: 'migration', to: '/migration', icon: CompareIcon, label: 'Migration Validator' },
  { key: 'alt-text', to: '/alt-text', icon: ImageIcon, label: 'Alt Text Generator' },
  { key: 'broken-links', to: '/broken-links', icon: LinkIcon, label: 'Broken Link Inspector' },
  { key: 'content-writer', to: '/content-writer', icon: PencilIcon, label: 'Content Writer' },
  { key: 'web-builder', to: '/web-builder', icon: BuilderIcon, label: 'Web Builder' },
  { key: 'all-tools', to: '/all-tools', icon: GridIcon, label: 'All Tools' },
];

const RAIL_LABEL = Object.fromEntries(RAIL_ITEMS.map((i) => [i.key, i.label]));

// A small static command-palette, not a search over live results (the doc's
// own example is tool discovery -- "typing 'broken' jumps to the right
// tool"). Searching migration results themselves is a much bigger feature
// left for later.
const SEARCH_INDEX = [
  { label: 'Home', to: '/', keywords: 'home start' },
  { label: 'Migration Validator', to: '/migration', keywords: 'migration compare validator run' },
  { label: 'Migrated Pages', to: '/migration/results', keywords: 'migration results pages risk' },
  { label: 'Not Migrated', to: '/migration/missing', keywords: 'migration missing not migrated' },
  { label: 'Redirect Map', to: '/migration/redirects', keywords: 'migration redirect map' },
  { label: 'Alt Text Generator', to: '/alt-text', keywords: 'alt text image accessibility' },
  { label: 'Broken Link Inspector', to: '/broken-links', keywords: 'broken links inspector scan' },
  { label: 'Content Writer', to: '/content-writer', keywords: 'content writer rewrite brand voice' },
  { label: 'Web Builder', to: '/web-builder', keywords: 'web builder sitecore components layout' },
  { label: 'All Tools', to: '/all-tools', keywords: 'all tools grid browse' },
];

function CommandSearch() {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const boxRef = useRef(null);

  useEffect(() => {
    function onClickAway(e) {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', onClickAway);
    return () => document.removeEventListener('mousedown', onClickAway);
  }, []);

  const q = query.trim().toLowerCase();
  const results = q
    ? SEARCH_INDEX.filter((r) => r.keywords.includes(q) || r.label.toLowerCase().includes(q))
    : [];

  function go(to) {
    navigate(to);
    setQuery('');
    setOpen(false);
  }

  return (
    <div className="topbar-search" ref={boxRef}>
      <label className="topbar-search-box">
        <SearchIcon size={13} style={{ color: 'var(--ink-3)', flex: 'none' }} />
        <input
          type="search"
          placeholder="Search tools…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
        />
      </label>
      {open && q && (
        <div className="topbar-search-results">
          {results.length === 0 ? (
            <div className="topbar-search-empty">No matching tool.</div>
          ) : (
            results.map((r) => (
              <button
                type="button"
                key={r.to}
                className="topbar-search-result"
                onClick={() => go(r.to)}
              >
                {r.label}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export default function Header({ active = null, crumbs = null, primaryAction = null }) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';
  const segments = crumbs && crumbs.length ? crumbs : [RAIL_LABEL[active] ?? 'MavDitto'];

  const [llmModalOpen, setLlmModalOpen] = useState(false);
  const [llmStatus, setLlmStatus] = useState(null);

  useEffect(() => {
    fetch('/api/config/llm')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) setLlmStatus(data);
      })
      .catch(() => {});
  }, []);

  const hasConfiguredKey = Boolean(
    llmStatus?.claude?.configured ||
    llmStatus?.openai?.configured ||
    llmStatus?.gemini?.configured
  );

  return (
    <>
      <nav className="rail" aria-label="Tools">
        <Link to="/" className="rail-brand" title="MavDitto — Home">
          <div className="brand-mark">M</div>
        </Link>
        <div className="rail-icons">
          {RAIL_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.key}
                to={item.to}
                className={`rail-item ${active === item.key ? 'rail-item-active' : ''}`}
                title={item.label}
              >
                <Icon size={20} />
                <span className="rail-item-label">{item.label}</span>
              </Link>
            );
          })}
        </div>
        <Link
          to="/settings"
          className={`rail-item ${active === 'settings' ? 'rail-item-active' : ''}`}
          title="Settings"
          style={{ marginTop: 'auto' }}
        >
          <SettingsIcon size={20} />
          <span className="rail-item-label">Settings</span>
        </Link>
      </nav>

      <div className="topbar">
        <div className="topbar-crumb">
          {segments.map((seg, i) => (
            <span className="crumb-seg" key={i}>
              {i > 0 && <span className="crumb-sep">/</span>}
              {seg}
            </span>
          ))}
        </div>

        <CommandSearch />

        <div className="topbar-actions">
          {primaryAction}

          {/* LLM API Key Configuration Button */}
          <button
            type="button"
            className="topbar-llm-btn"
            onClick={() => setLlmModalOpen(true)}
            aria-label="Configure LLM API Keys"
            title="Configure LLM API Keys (OpenAI, Gemini, Claude)"
          >
            <SparklesIcon size={14} className="topbar-llm-icon" />
            <span className="topbar-llm-text">LLM</span>
            <span
              className={`topbar-llm-dot ${hasConfiguredKey ? 'topbar-llm-dot--active' : ''}`}
            />
          </button>

          <button
            type="button"
            className="icon-btn"
            onClick={toggleTheme}
            aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {isDark ? <SunIcon /> : <MoonIcon />}
          </button>
        </div>
      </div>

      <LlmConfigModal
        isOpen={llmModalOpen}
        onClose={() => setLlmModalOpen(false)}
        onConfigSaved={(updated) => setLlmStatus(updated)}
      />
    </>
  );
}
