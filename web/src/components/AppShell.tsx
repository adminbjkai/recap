import type { ReactNode } from "react";
import { Link } from "react-router-dom";

type Props = {
  children: ReactNode;
};

/**
 * Top-bar chrome.  Intentionally quiet: wordmark + one primary
 * CTA ("New recording"). Legacy HTML dashboards are still
 * reachable via direct URL and via the footer text link; they do
 * not compete with the primary React surface.
 */
export default function AppShell({ children }: Props) {
  return (
    <div className="recap-app">
      <header className="recap-topbar" role="banner">
        <div className="recap-topbar-inner">
          <Link className="recap-brand" to="/" aria-label="Recap home">
            <span className="recap-brand-mark" aria-hidden>
              R
            </span>
            <span className="recap-brand-name">Recap</span>
            <span className="recap-brand-sub" aria-hidden>
              local-first video docs
            </span>
          </Link>
          <nav className="recap-topnav" aria-label="Primary">
            <Link className="recap-topnav-link" to="/">
              Library
            </Link>
            <Link className="recap-topnav-link primary" to="/new">
              New recording
            </Link>
          </nav>
        </div>
      </header>
      {children}
      <footer className="recap-app-footer" role="contentinfo">
        <p>
          Recap · local-first video documentation ·{" "}
          <a
            className="recap-app-footer-link"
            href="/"
            title="Legacy stdlib HTML dashboard"
          >
            Legacy dashboard
          </a>
        </p>
      </footer>
    </div>
  );
}
