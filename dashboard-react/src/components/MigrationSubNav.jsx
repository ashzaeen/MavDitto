import { NavLink } from 'react-router-dom';
import { usePages, useDiscovery, useRedirects } from '../data/useData.jsx';
import { FileTextIcon, AlertCircleIcon, ArrowRightLeftIcon } from './Icons.jsx';

// Contextual sub-navigation for Migration Validator views.
export default function MigrationSubNav() {
  const pages = usePages();
  const discovery = useDiscovery();
  const redirects = useRedirects();

  const migratedCount = pages.length;
  const notMigratedCount = discovery?.notMigrated?.length ?? 0;
  const redirectCount = redirects.length;

  const tabs = [
    {
      to: '/migration/results',
      label: 'Migrated Pages',
      icon: FileTextIcon,
      count: migratedCount,
      variant: 'default',
    },
    {
      to: '/migration/missing',
      label: 'Not Migrated',
      icon: AlertCircleIcon,
      count: notMigratedCount,
      variant: notMigratedCount > 0 ? 'bad' : 'muted',
    },
    {
      to: '/migration/redirects',
      label: 'Redirect Map',
      icon: ArrowRightLeftIcon,
      count: redirectCount,
      variant: 'default',
    },
  ];

  return (
    <nav className="migration-sub-nav" aria-label="Migration Validator views">
      <div className="sub-nav-track">
        {tabs.map((t) => {
          const Icon = t.icon;
          return (
            <NavLink
              key={t.to}
              to={t.to}
              className={({ isActive }) =>
                `sub-nav-tab ${isActive ? 'sub-nav-tab-active' : ''}`
              }
            >
              <Icon size={14} className="sub-nav-tab-icon" />
              <span>{t.label}</span>
              {t.count !== undefined && (
                <span className={`sub-nav-badge sub-nav-badge--${t.variant}`}>
                  {t.count}
                </span>
              )}
            </NavLink>
          );
        })}
      </div>
    </nav>
  );
}
