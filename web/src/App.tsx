import { Link, Route, Routes } from "react-router-dom";
import TranscriptWorkspacePage from "./pages/TranscriptWorkspacePage";

function AppPlaceholder() {
  return (
    <main className="app-shell app-placeholder">
      <section className="hero-card">
        <p className="eyebrow">Recap web</p>
        <h1>Open a transcript workspace</h1>
        <p>
          This first React slice ships the transcript workspace. Open a
          specific job at <code>/app/job/&lt;id&gt;/transcript</code>.
        </p>
        <Link className="text-link" to="/">
          Legacy dashboard remains available
        </Link>
      </section>
    </main>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/job/:id/transcript" element={<TranscriptWorkspacePage />} />
      <Route path="*" element={<AppPlaceholder />} />
    </Routes>
  );
}
