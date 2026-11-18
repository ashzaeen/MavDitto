import { CompareIcon, ImageIcon, LinkIcon, PencilIcon, BuilderIcon } from '../components/Icons.jsx';

// The whole suite, one entry per capability -- the single list Home's
// curated row and All Tools' exhaustive grid both read from. Add a tool here
// once, and it appears in both places automatically.
export const TOOLS = [
  {
    key: 'migration',
    name: 'Migration Validator',
    description: 'Compare an old site against its replacement and see what the move actually kept.',
    icon: CompareIcon,
    to: '/migration',
  },
  {
    key: 'alt-text',
    name: 'Alt Text Generator',
    description: 'Write screen-reader-ready alt text for one image, or every image on a page.',
    icon: ImageIcon,
    to: '/alt-text',
  },
  {
    key: 'broken-links',
    name: 'Broken Link Inspector',
    description: 'Scan a page or a whole subsite for broken, redirected, or restricted links.',
    icon: LinkIcon,
    to: '/broken-links',
  },
  {
    key: 'content-writer',
    name: 'Content Writer',
    description: "Rewrite a page or an uploaded file into your brand voice.",
    icon: PencilIcon,
    to: '/content-writer',
  },
  {
    key: 'web-builder',
    name: 'Web Builder',
    description: 'Map rewritten content onto your component library, ready to paste in.',
    icon: BuilderIcon,
    to: '/web-builder',
  },
];
