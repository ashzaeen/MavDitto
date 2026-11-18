import { createContext, useContext, useState } from 'react';

// The Broken Link Inspector's last finished scan, kept in app-level memory so
// leaving the page and coming back still shows it. Unlike the migration run,
// a link scan is never persisted server-side: a hard refresh clears it.
const LinkScanContext = createContext(null);

export function LinkScanProvider({ children }) {
  const [scan, setScan] = useState(null);
  return (
    <LinkScanContext.Provider value={{ scan, setScan }}>
      {children}
    </LinkScanContext.Provider>
  );
}

export function useLinkScan() {
  const ctx = useContext(LinkScanContext);
  if (!ctx) throw new Error('useLinkScan must be used within a LinkScanProvider');
  return ctx;
}
