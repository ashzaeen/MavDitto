import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App.jsx';
import { ThemeProvider } from './ThemeContext.jsx';
import { DataProvider } from './data/useData.jsx';
import { LinkScanProvider } from './data/useLinkScan.jsx';
import { ContentHandoffProvider } from './data/useContentHandoff.jsx';
import './theme.css';
import './content-writer.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <ThemeProvider>
        <DataProvider>
          <LinkScanProvider>
            <ContentHandoffProvider>
              <App />
            </ContentHandoffProvider>
          </LinkScanProvider>
        </DataProvider>
      </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>
);
