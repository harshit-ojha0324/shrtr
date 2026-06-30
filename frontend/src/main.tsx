import { FormEvent, StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, getApiKey, setApiKey, StoreProvider, useStore } from "./api";
import Composer from "./Composer";
import LinkPage from "./LinkPage";
import Rail from "./Rail";
import { A, BackIcon, usePath } from "./ui";
import "./index.css";

function Home() {
  const { setComposer, hasKey, links } = useStore();
  return (
    <div className="empty">
      <div>
        <span className="mark" />
        <h2>{!hasKey ? "Connect your API key" : links.length ? "Pick a link to see its clicks" : "Create your first short link"}</h2>
        <p>{!hasKey ? "Open Settings and paste the key printed by make seed." : "Paste a long URL to get a short one with a QR code and live click counts."}</p>
        {hasKey && <button className="btn primary" style={{ marginTop: 8 }} onClick={() => setComposer(true)}>New link</button>}
      </div>
    </div>
  );
}

function Settings() {
  const [key, setKey] = useState(getApiKey());
  const [show, setShow] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    setApiKey(key.trim());
    if (!key.trim()) return setStatus({ ok: true, text: "Key removed." });
    setBusy(true);
    try {
      await api.listLinks(1);
      setStatus({ ok: true, text: "Saved. The key works." });
    } catch (err) {
      setStatus({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <A href="/" className="btn ghost only-narrow" style={{ justifySelf: "start" }}><BackIcon /> Links</A>
      <h1>API key</h1>
      <form onSubmit={save} className="panel">
        <div className="field">
          <label htmlFor="key">Key</label>
          <div style={{ display: "flex", gap: 6 }}>
            <input id="key" className="input" type={show ? "text" : "password"} autoComplete="off" placeholder="Paste the key printed by make seed" value={key} onChange={(e) => setKey(e.target.value)} />
            <button type="button" className="btn" onClick={() => setShow(!show)}>{show ? "Hide" : "Show"}</button>
          </div>
          <div className="hint">Stored only in this browser and sent as the X-API-Key header.</div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button className="btn primary" disabled={busy}>{busy ? <span className="spin" /> : "Save & test"}</button>
          {status && <span className={`hint ${status.ok ? "ok" : "bad"}`} role="status" style={{ margin: 0 }}>{status.text}</span>}
        </div>
      </form>
      <div className="panel">
        <b>Don't have a key?</b>
        <span className="note">With the stack running, create one with:</span>
        <pre>make seed</pre>
      </div>
    </div>
  );
}

function Shell() {
  const path = usePath();
  const { composer, setComposer } = useStore();
  const m = path.match(/^\/links\/([^/]+)$/);
  const code = m ? decodeURIComponent(m[1]) : undefined;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement;
      const mod = e.metaKey || e.ctrlKey;
      if ((e.key === "k" && mod) || (e.key === "n" && !typing && !mod && !e.altKey)) {
        e.preventDefault();
        setComposer(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setComposer]);

  return (
    // phones show one pane: the list at "/", the detail everywhere else
    <div className="shell" data-pane={path === "/" ? "list" : "detail"}>
      <Rail selected={code} />
      <main className="main">
        {code ? <LinkPage key={code} code={code} />
          : path === "/settings" ? <Settings />
          : path === "/" ? <Home />
          : <div className="empty"><div><h2>Page not found</h2><A href="/">Back to links</A></div></div>}
      </main>
      {composer && <Composer />}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <StoreProvider>
      <Shell />
    </StoreProvider>
  </StrictMode>,
);
