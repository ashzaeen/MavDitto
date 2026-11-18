// Where the dashboard's data comes from.
//
// Served by `python -m src.server`, it reads the live API, which also lets it
// start runs. Opened as a plain static bundle with no server behind it, it
// falls back to `public/data.json` from `python -m src.export_web` and the run
// form says it needs the server.
//
// Everything is loaded once at the root and passed down, so a filter or a
// navigation never re-fetches.

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

const API = '/api/data';
const STATIC = `${import.meta.env.BASE_URL}data.json`;

const DataContext = createContext(null);

const EMPTY_TOTALS = { clean: 0, minor: 0, major: 0, missing: 0, error: 0 };

async function loadData() {
  // The API first: when the server is running it is authoritative and always
  // current, while the static file is whatever the last export wrote.
  try {
    const response = await fetch(API, { cache: 'no-store' });
    if (response.ok) return { data: await response.json(), live: true };
  } catch {
    /* no server — fall through */
  }
  const response = await fetch(STATIC, { cache: 'no-store' });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return { data: await response.json(), live: false };
}

export function DataProvider({ children }) {
  const [state, setState] = useState({
    status: 'loading',
    data: null,
    live: false,
    error: null,
  });
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const { data, live } = await loadData();
      if (!mounted.current) return;
      const hasAnything = (data.pages && data.pages.length) || data.discovery;
      setState({
        status: hasAnything ? 'loaded' : 'empty',
        data,
        live,
        error: null,
      });
    } catch (error) {
      if (mounted.current) setState({ status: 'error', data: null, live: false, error });
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    refresh();
    return () => {
      mounted.current = false;
    };
  }, [refresh]);

  return (
    <DataContext.Provider value={{ ...state, refresh }}>{children}</DataContext.Provider>
  );
}

export function useData() {
  const state = useContext(DataContext);
  if (state === null) throw new Error('useData must be used inside <DataProvider>');
  return state;
}

/** Convenience accessors so components never guard for missing keys. */
export function usePages() {
  const { data } = useData();
  return data?.pages ?? [];
}

export function useTotals() {
  const { data } = useData();
  return { ...EMPTY_TOTALS, ...(data?.totals ?? {}) };
}

export function useDiscovery() {
  const { data } = useData();
  return data?.discovery ?? null;
}

export function useRedirects() {
  const { data } = useData();
  return data?.redirects ?? [];
}

export function useLastRun() {
  const { data } = useData();
  return data?.lastRun ?? '';
}
