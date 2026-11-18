import { createContext, useContext, useState } from 'react';

// Content Writer's last finished rewrite, held in memory so "Send to Web
// Builder" and Web Builder's "Use Content Writer output" input option work
// without a server round-trip -- same shape as useLinkScan.jsx.
const ContentHandoffContext = createContext(null);

export function ContentHandoffProvider({ children }) {
  const [content, setContent] = useState(null);
  return (
    <ContentHandoffContext.Provider value={{ content, setContent }}>
      {children}
    </ContentHandoffContext.Provider>
  );
}

export function useContentHandoff() {
  const ctx = useContext(ContentHandoffContext);
  if (!ctx) throw new Error('useContentHandoff must be used within a ContentHandoffProvider');
  return ctx;
}
