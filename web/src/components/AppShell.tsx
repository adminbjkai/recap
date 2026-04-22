import type { ReactNode } from "react";
import { Link } from "react-router-dom";

type Props = {
  children: ReactNode;
};

/**
 * Topbar chrome.  Kept intentionally quiet: wordmark + one primary
 * CTA. Secondary links (Library, Legacy) are subordinate so the
 * primary "New recording" action is the obvious next step on every
 * page.
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
            <a
              className="recap-topnav-fallback"
              href="/"
              title="Legacy stdlib HTML dashboard"
            >
              Legacy
            </a>
          </nav>
        </div>
      </header>
      {children}
    </div>
  );
}
