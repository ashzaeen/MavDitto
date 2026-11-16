import { Navigate, Routes, Route } from 'react-router-dom';
import Home from './pages/Home.jsx';
import AllTools from './pages/AllTools.jsx';
import MigrationHome from './pages/MigrationHome.jsx';
import MainView from './pages/MainView.jsx';
import PageDetail from './pages/PageDetail.jsx';
import RedirectMap from './pages/RedirectMap.jsx';
import NotMigrated from './pages/NotMigrated.jsx';
import AltTextPage from './pages/AltTextPage.jsx';
import BrokenLinksPage from './pages/BrokenLinksPage.jsx';
import ContentWriterPage from './pages/ContentWriterPage.jsx';
import WebBuilderPage from './pages/WebBuilderPage.jsx';
import SetupWizard from './pages/SetupWizard.jsx';
import Settings from './pages/Settings.jsx';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/all-tools" element={<AllTools />} />

      <Route path="/migration" element={<MigrationHome />} />
      <Route path="/migration/results" element={<MainView />} />
      <Route path="/migration/pages/:id" element={<PageDetail />} />
      <Route path="/migration/missing" element={<NotMigrated />} />
      <Route path="/migration/redirects" element={<RedirectMap />} />

      <Route path="/alt-text" element={<AltTextPage />} />

      <Route path="/broken-links" element={<BrokenLinksPage />} />
      <Route path="/broken-links/*" element={<Navigate to="/broken-links" replace />} />

      <Route path="/content-writer" element={<ContentWriterPage />} />
      <Route path="/web-builder" element={<WebBuilderPage />} />

      <Route path="/setup" element={<SetupWizard />} />
      <Route path="/settings" element={<Settings />} />
    </Routes>
  );
}
