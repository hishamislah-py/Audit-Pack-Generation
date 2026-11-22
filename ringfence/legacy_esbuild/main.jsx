import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { get } from "./api.js";
import { Mark, Icon } from "./ui.jsx";
import Queue from "./Queue.jsx";
import CaseView from "./CaseView.jsx";

function useRoute() {
  const [hash, setHash] = useState(window.location.hash || "#/queue");
  useEffect(() => {
    const f = () => setHash(window.location.hash || "#/queue");
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
}

function App() {
  const route = useRoute();
  const [app, setApp] = useState(null);
  useEffect(() => { get("app").then(setApp).catch(() => setApp(null)); }, []);
  const llm = app && app.llm ? app.llm.mode : "…";
  let body;
  if (route[0] === "case" && route[1]) body = <CaseView key={route[1]} caseRef={route[1]} tab={route[2] || "overview"} sub={route[3]} app={app} />;
  else body = <Queue />;
  return <div className="rf-app">
    <header className="rf-topbar">
      <a className="rf-brand" href="#/queue" aria-label="Ringfence home"><Mark /><span>Ringfence</span></a>
      <span className="rf-brand__ctx">Moorwand safeguarding operations · UC-042</span>
      <nav className="rf-nav" aria-label="Primary">
        <a href="#/queue" className={"rf-nav__item" + (route[0] !== "case" ? " is-active" : "")}><Icon name="inbox" />Work queue</a>
      </nav>
      <span className="rf-spacer" />
      <span className="rf-llm" id="llm-mode" title={app && app.llm ? app.llm.label : ""}>LLM proposals: {llm}</span>
      <span className="rf-env" title="Proof-of-concept environment with synthetic data">POC · SYNTHETIC DATA</span>
      <div className="rf-user"><span className="rf-userbtn" id="analyst-id"><span className="rf-avatar">{app ? app.reviewer.reviewer_id.slice(0, 2).toUpperCase() : "··"}</span>
        <span>{app ? app.reviewer.reviewer_id : "…"}</span></span></div>
    </header>
    <main className="rf-main">{body}</main>
  </div>;
}

createRoot(document.getElementById("root")).render(<App />);
