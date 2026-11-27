import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles/tokens.css";
import "./styles/bundle.css";
import "./styles/app.css";
import { api } from "./api/ringfence.js";
import { Icon, Mark } from "./components/ui.jsx";
import Queue from "./screens/Queue.jsx";
import CaseScreen from "./screens/Case.jsx";
import { Customers, CustomerProfile } from "./screens/Customers.jsx";

export const AppContext = createContext({ app: null, refreshSlot: () => {} });
export const useApp = () => useContext(AppContext);

function useHashRoute() {
  const read = () => (window.location.hash || "#/queue").replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const f = () => setRoute(read());
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return route;
}

function ActiveSlot({ slot }) {
  if (!slot) return <span className="rf-slot" id="active-slot">No case In Progress</span>;
  return <span className="rf-slot" id="active-slot">In Progress:
    <a href={"#/case/" + slot.case_ref}>{slot.case_ref}</a> {slot.customer_name} · {slot.reporting_period}
    {slot.deferring ? " · deferral requested" : ""}</span>;
}

function App() {
  const route = useHashRoute();
  const [app, setApp] = useState(null);
  const [slot, setSlot] = useState(null);
  const refreshSlot = useCallback(() => api.cases().then((q) => setSlot(q.active_case)).catch(() => {}), []);
  useEffect(() => { api.app().then(setApp).catch(() => setApp(null)); }, []);
  useEffect(() => {                                     // queue / slot: every 30 s and on window focus (contract §5)
    refreshSlot();
    const t = setInterval(refreshSlot, 30000);
    window.addEventListener("focus", refreshSlot);
    return () => { clearInterval(t); window.removeEventListener("focus", refreshSlot); };
  }, [refreshSlot]);
  let body;
  if (route[0] === "case" && route[1]) body = <CaseScreen key={route[1]} caseRef={route[1]} tab={route[2] || "overview"} sub={route[3]} />;
  else if (route[0] === "customers" && route[1]) body = <CustomerProfile key={route[1]} customerId={route[1]} />;
  else if (route[0] === "customers") body = <Customers />;
  else body = <Queue />;
  const nav = [["queue", "Work queue", "inbox"], ["customers", "Customers", "building"]];
  const current = route[0] === "customers" ? "customers" : route[0] === "case" ? "" : "queue";
  return <AppContext.Provider value={{ app, refreshSlot, slot }}>
    <div className="rf-app">
      <header className="rf-topbar">
        <a className="rf-brand" href="#/queue" aria-label="Ringfence home"><Mark /><span>Ringfence</span></a>
        <span className="rf-brand__ctx">Moorwand safeguarding operations · UC-042</span>
        <nav className="rf-nav" aria-label="Primary">{nav.map(([k, label, icon]) =>
          <a key={k} href={"#/" + k} className={"rf-nav__item" + (current === k ? " is-active" : "")}
            aria-current={current === k ? "page" : undefined}><Icon name={icon} />{label}</a>)}</nav>
        <span className="rf-spacer" />
        <ActiveSlot slot={slot} />
        <span className="rf-env" title={app && app.llm ? app.llm.label : ""} id="llm-mode">
          LLM proposals: {app && app.llm ? app.llm.mode : "…"}</span>
        <div className="rf-user"><span className="rf-userbtn" id="analyst-id">
          <span className="rf-avatar">{app ? app.reviewer.reviewer_id.slice(0, 2).toUpperCase() : "··"}</span>
          <span>{app ? app.reviewer.reviewer_id : "…"}</span></span></div>
      </header>
      <main className="rf-main">{body}</main>
    </div></AppContext.Provider>;
}

createRoot(document.getElementById("root")).render(<App />);
