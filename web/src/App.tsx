import { Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import JobsIndexPage from "./pages/JobsIndexPage";
import TranscriptWorkspacePage from "./pages/TranscriptWorkspacePage";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<JobsIndexPage />} />
        <Route
          path="/job/:id/transcript"
          element={<TranscriptWorkspacePage />}
        />
        <Route path="*" element={<JobsIndexPage />} />
      </Routes>
    </AppShell>
  );
}
