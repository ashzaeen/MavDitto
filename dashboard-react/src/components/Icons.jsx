// Small inline stroke icons, sized via `size` and colored via `style`/currentColor.
// Swap these for your icon library of choice if you have one.

export function CheckIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M3.5 8.5L6.5 11.5L12.5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function PencilIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M10.5 2.5L13.5 5.5L5.5 13.5H2.5V10.5L10.5 2.5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

export function TriangleAlertIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M8 2.5L14.5 13.5H1.5L8 2.5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <line x1="8" y1="7" x2="8" y2="9.8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <circle cx="8" cy="11.6" r="0.8" fill="currentColor" />
    </svg>
  );
}

export function XCircleIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.4" />
      <path d="M6 6L10 10M10 6L6 10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export function HelpCircleIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.4" />
      <path
        d="M6.3 6.2c0-1 .8-1.7 1.8-1.7s1.7.6 1.7 1.5c0 1.2-1.6 1.2-1.6 2.4"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
      <circle cx="8" cy="11" r="0.7" fill="currentColor" />
    </svg>
  );
}

export function ClockIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.4" />
      <path d="M8 5V8.5L10.5 10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export function SearchIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4" />
      <path d="M10.5 10.5L13.5 13.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export function DownloadIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M8 2.5V10.5M8 10.5L5 7.5M8 10.5L11 7.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M3 13.5H13" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export function UploadIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M8 10.5V2.5M8 2.5L5 5.5M8 2.5L11 5.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M3 13.5H13" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export function ArrowLeftIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M13 8H3M3 8L7 4M3 8L7 12" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ArrowRightIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M3 8H13M13 8L9 4M13 8L9 12" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ChevronLeftIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M10 12L6 8L10 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ChevronRightIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M6 12L10 8L6 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function AlertCircleIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.4" />
      <line x1="8" y1="5" x2="8" y2="8.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <circle cx="8" cy="11" r="0.7" fill="currentColor" />
    </svg>
  );
}

export function AlertDotIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.4" />
      <line x1="8" y1="5.5" x2="8" y2="8.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <circle cx="8" cy="10.8" r="0.8" fill="currentColor" />
    </svg>
  );
}

export function CheckCircleIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.4" />
      <path d="M5.5 8L7 9.5L10.5 6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function InboxIcon({ size = 18, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M2.5 3.5H13.5V10.5H10.5L9.5 12H6.5L5.5 10.5H2.5V3.5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

export function ChevronDownIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M4 6L8 10L12 6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function SunIcon({ size = 15, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <circle cx="8" cy="8" r="3" stroke="currentColor" strokeWidth="1.3" />
      <path d="M8 2V3.5M8 12.5V14M2 8H3.5M12.5 8H14M3.75 3.75L4.81 4.81M11.19 11.19L12.25 12.25M3.75 12.25L4.81 11.19M11.19 4.81L12.25 3.75" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

export function MoonIcon({ size = 15, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M13.2 9.8A5.5 5.5 0 1 1 6.2 2.8a4.5 4.5 0 0 0 7 7Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  );
}

export function PlayIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M4.5 3L12.5 8L4.5 13V3Z" fill="currentColor" />
    </svg>
  );
}

export function StopIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <rect x="3.5" y="3.5" width="9" height="9" rx="1.5" fill="currentColor" />
    </svg>
  );
}

export function CopyIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <rect x="5.5" y="5.5" width="7.5" height="7.5" rx="1.2" stroke="currentColor" strokeWidth="1.3" />
      <path d="M3.5 10.5V3.5C3.5 2.9 3.9 2.5 4.5 2.5H10.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

export function CommentIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M2.5 3.5H13.5V11H8.5L5.5 13.5V11H2.5V3.5Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  );
}

export function ImageIcon({ size = 18, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <rect x="2" y="2" width="12" height="12" rx="1.5" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="5.5" cy="5.5" r="1.2" fill="currentColor" />
      <path d="M2.5 11.5L6 8L9 11L11.5 8.5L13.5 10.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function HomeIcon({ size = 18, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M2.5 7L8 2.5L13.5 7V13.5H2.5V7Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M6.5 13V9.5H9.5V13" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

export function CompareIcon({ size = 18, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M5.5 2.5V11.5M5.5 2.5L3 5M5.5 2.5L8 5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M10.5 13.5V4.5M10.5 13.5L8 11M10.5 13.5L13 11" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function LinkIcon({ size = 18, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M6.5 9.5L9.5 6.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M7.5 4.5L8.7 3.3C9.7 2.3 11.3 2.3 12.3 3.3C13.3 4.3 13.3 5.9 12.3 6.9L11.1 8.1" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M8.5 11.5L7.3 12.7C6.3 13.7 4.7 13.7 3.7 12.7C2.7 11.7 2.7 10.1 3.7 9.1L4.9 7.9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export function GridIcon({ size = 18, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <rect x="2.5" y="2.5" width="4.5" height="4.5" rx="1" stroke="currentColor" strokeWidth="1.3" />
      <rect x="9" y="2.5" width="4.5" height="4.5" rx="1" stroke="currentColor" strokeWidth="1.3" />
      <rect x="2.5" y="9" width="4.5" height="4.5" rx="1" stroke="currentColor" strokeWidth="1.3" />
      <rect x="9" y="9" width="4.5" height="4.5" rx="1" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

export function BuilderIcon({ size = 18, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <rect x="2" y="2" width="12" height="12" rx="1.3" stroke="currentColor" strokeWidth="1.3" />
      <path d="M2 6H14" stroke="currentColor" strokeWidth="1.3" />
      <path d="M6 6V14" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

export function FileTextIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M9 1.5H3.5C2.7 1.5 2 2.2 2 3V13C2 13.8 2.7 14.5 3.5 14.5H12.5C13.3 14.5 14 13.8 14 13V6.5L9 1.5Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M9 1.5V6.5H14" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <line x1="5" y1="9" x2="11" y2="9" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      <line x1="5" y1="11.5" x2="9" y2="11.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

export function ArrowRightLeftIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M11 2.5L14 5.5L11 8.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M2 5.5H14" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      <path d="M5 13.5L2 10.5L5 7.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M14 10.5H2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

export function ExternalLinkIcon({ size = 13, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M10 2.5H13.5V6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M6.5 9.5L13.5 2.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      <path d="M11.5 8.5V12.5C11.5 13.1 11.1 13.5 10.5 13.5H3.5C2.9 13.5 2.5 13.1 2.5 12.5V5.5C2.5 4.9 2.9 4.5 3.5 4.5H7.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

export function SparklesIcon({ size = 15, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M8 1.5L9.3 5.3L13.5 6.5L10.2 9.2L11.2 13.5L8 11.2L4.8 13.5L5.8 9.2L2.5 6.5L6.7 5.3L8 1.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
    </svg>
  );
}

export function KeyIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <circle cx="5.5" cy="6.5" r="3.5" stroke="currentColor" strokeWidth="1.3" />
      <path d="M8 8.5L13.5 14M11.5 10.5L13 12M10 12L11.5 13.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

export function EyeIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M1.5 8C2.8 4.8 5.2 3 8 3C10.8 3 13.2 4.8 14.5 8C13.2 11.2 10.8 13 8 13C5.2 13 2.8 11.2 1.5 8Z" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="8" cy="8" r="2.2" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

export function EyeOffIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M2 2L14 14M6.8 6.9C6.3 7.4 6 8.1 6 8.8C6 10 7 11 8.2 11C8.9 11 9.6 10.7 10.1 10.2M4.5 4.7C3.3 5.6 2.3 6.9 1.5 8C2.8 11.2 5.2 13 8 13C9.4 13 10.7 12.5 11.8 11.6M8 3C10.8 3 13.2 4.8 14.5 8C13.9 9.4 12.9 10.6 11.7 11.4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

export function ShieldCheckIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <path d="M8 2L13.5 4.5V8.5C13.5 11.8 10.9 13.9 8 14.5C5.1 13.9 2.5 11.8 2.5 8.5V4.5L8 2Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M5.5 8L7.2 9.7L10.5 6.3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function SettingsIcon({ size = 14, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" style={style} className={className}>
      <circle cx="8" cy="8" r="2.2" stroke="currentColor" strokeWidth="1.3" />
      <path
        d="M8 1.5V3M8 13V14.5M14.5 8H13M3 8H1.5M12.36 3.64L11.3 4.7M4.7 11.3L3.64 12.36M12.36 12.36L11.3 11.3M4.7 4.7L3.64 3.64"
        stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"
      />
    </svg>
  );
}
