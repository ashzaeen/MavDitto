import { useEffect, useState } from 'react';
import { useTheme } from '../ThemeContext.jsx';

/**
 * Mav the Maverick Mascot Loader
 * A small pixel-art UTA Maverick pony with animated ears, blinking eyes,
 * trotting bounce, and glowing radar pulse while a tool works.
 *
 * Two modes:
 * - Live: `stage`/`message`/`counts` (or the more general `badges`) come from
 *   a real polled backend job (Migration Validator, Broken Links' Site Scan).
 * - Indeterminate: `indeterminateMessages` cycles a few honest, tool-flavored
 *   lines for tools that only make one blocking request with no real
 *   progress data to report (Alt Text, Content Writer, Web Builder, Broken
 *   Links' Page Scan) -- no counts are shown here, since there's nothing
 *   real to count.
 *
 * `toolIcon` is a small badge on the radar stage tying the card back to
 * whichever tool is running, reusing the same icon as its rail entry.
 */
export default function MascotLoader({
  stage, message, counts = {}, badges = [],
  toolIcon: ToolIcon, indeterminateMessages, indeterminateLabel = 'Working',
}) {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  const [msgIndex, setMsgIndex] = useState(0);
  useEffect(() => {
    if (!indeterminateMessages?.length) return undefined;
    const timer = setInterval(() => {
      setMsgIndex((i) => (i + 1) % indeterminateMessages.length);
    }, 2600);
    return () => clearInterval(timer);
  }, [indeterminateMessages]);

  const displayStage = indeterminateMessages ? indeterminateLabel : (stage || 'Crawling site');
  const displayMessage = indeterminateMessages
    ? indeterminateMessages[msgIndex % indeterminateMessages.length]
    : (message || 'Scanning pages and detecting migration changes…');

  const countBadges = [
    ...(counts.old_pages > 0 ? [{ key: 'old', value: counts.old_pages, label: 'Old Pages' }] : []),
    ...(counts.new_pages > 0 ? [{ key: 'new', value: counts.new_pages, label: 'New Pages' }] : []),
    ...(counts.matched > 0 ? [{ key: 'matched', value: counts.matched, label: 'Paired', variant: 'success' }] : []),
    ...(counts.not_migrated > 0
      ? [{ key: 'unmig', value: counts.not_migrated, label: 'Unmigrated', variant: 'warning' }] : []),
    ...(counts.compared > 0 ? [{ key: 'compared', value: counts.compared, label: 'Diffed', variant: 'info' }] : []),
    ...badges,
  ];

  return (
    <div className="mascot-loader-container">
      {/* Background Radar Scanning Pulse Rings */}
      <div className="mascot-radar-stage">
        <div className="mascot-radar-ring ring-1" />
        <div className="mascot-radar-ring ring-2" />
        <div className="mascot-radar-ring ring-3" />
        <div className="mascot-sparkle sparkle-1">✦</div>
        <div className="mascot-sparkle sparkle-2">★</div>
        <div className="mascot-sparkle sparkle-3">✦</div>

        {/* Mascot SVG */}
        <div className="mascot-character-wrap">
          <svg
            className="mav-mascot-svg"
            viewBox="0 0 160 160"
            width="96"
            height="96"
            fill="none"
            shapeRendering="crispEdges"
            xmlns="http://www.w3.org/2000/svg"
            aria-label="Mav the Maverick investigating pages"
          >
            {/* Ground Shadow */}
            <rect className="mav-shadow" x="40" y="142" width="64" height="8" fill={isDark ? 'rgba(0,0,0,0.45)' : 'rgba(0,56,101,0.12)'} />

            {/* Trotting & Bobbing Group */}
            <g className="mav-body-group">
              {/* Back mane stripe, running from the top of the head down through the neck */}
              <rect x="44" y="28" width="8" height="100" fill={isDark ? '#2dd4bf' : '#f58025'} />

              {/* Neck block */}
              <rect x="52" y="72" width="28" height="56" fill={isDark ? '#3b82f6' : '#0064b1'} />

              {/* Maverick star, pinned on the collar */}
              <rect x="59" y="103" width="10" height="10" fill="#ffffff" transform="rotate(45 64 108)" />

              {/* Head block */}
              <rect x="56" y="28" width="40" height="44" fill={isDark ? '#3b82f6' : '#0064b1'} />

              {/* Ear (Animated Twitch) */}
              <g className="mav-ear-group">
                <rect x="62" y="14" width="12" height="16" fill={isDark ? '#3b82f6' : '#0064b1'} />
                <rect x="65" y="18" width="6" height="8" fill={isDark ? '#93c5fd' : '#bdd6e6'} />
              </g>

              {/* Muzzle, tapering to a point (a pixel-art staircase, not one flat block) */}
              <rect x="88" y="44" width="24" height="16" fill={isDark ? '#3b82f6' : '#0064b1'} />
              <rect x="108" y="52" width="20" height="10" fill={isDark ? '#3b82f6' : '#0064b1'} />
              <rect x="124" y="54" width="6" height="6" fill={isDark ? '#60a5fa' : '#3388cc'} />
              <rect x="120" y="58" width="4" height="3" fill={isDark ? '#0f172a' : '#002544'} />

              {/* Eye (Animated Blink) */}
              <g className="mav-eye-group">
                <rect x="76" y="38" width="14" height="14" fill="#ffffff" />
                <rect x="82" y="40" width="8" height="10" fill={isDark ? '#0f172a' : '#002544'} />
              </g>
            </g>
          </svg>
        </div>

        {ToolIcon && (
          <span className="mascot-tool-badge">
            <ToolIcon size={13} />
          </span>
        )}
      </div>

      {/* Status and Message */}
      <div className="mascot-status-block">
        <div className="mascot-stage-badge">
          <span className="mascot-pulsing-dot" />
          <span className="mascot-stage-name">{displayStage}</span>
        </div>
        <p className="mascot-status-message" key={displayMessage}>
          {displayMessage}
        </p>
      </div>

      {/* Real-time counters -- only shown when there's real data to report */}
      {countBadges.length > 0 && (
        <div className="mascot-counts-row">
          {countBadges.map((b) => (
            <span
              key={b.key}
              className={`mascot-count-pill ${b.variant ? `mascot-count-pill--${b.variant}` : ''}`}
            >
              <strong>{b.value}</strong> {b.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
