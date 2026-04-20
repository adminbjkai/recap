import type { ReactNode } from "react";
import { Link } from "react-router-dom";

type Props = {
  children: ReactNode;
};

export default function AppShell({ children }: Props) {
  return (
    <div className="recap-app">
      <header className="recap-topbar">
        <div className="recap-topbar-inner">
          <Link className="recap-brand" to="/">
            <span className="recap-brand-mark" aria-hidden>
              ◈
            </span>
            <span className="recap-brand-name">Recap</span>
          </Link>
          <nav className="recap-topnav" aria-label="Primary">
            <a className="recap-topnav-link" href="/">
              Legacy dashboard
            </a>
            <a className="recap-topnav-link primary" href="/new">
              New job
            </a>
          </nav>
        </div>
      </header>
      {children}
    </div>
  );
}
