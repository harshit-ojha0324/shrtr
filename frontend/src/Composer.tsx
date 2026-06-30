import { FormEvent, useEffect, useRef, useState } from "react";
import { api, BulkResult, NewLink, useStore } from "./api";
import { navigate } from "./ui";

const MAX_BULK = 50; // the API's per-call cap

// one link per line, optionally "url,alias" or "url alias"; a CSV header row is skipped
function parse(text: string): NewLink[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !/^(long_)?url\b/i.test(l))
    .map((l) => {
      const [long_url, custom_alias] = l.split(/[,\s]+/);
      return custom_alias ? { long_url, custom_alias } : { long_url };
    });
}

type Check = { s: "idle" | "checking" | "ok" | "bad"; reason?: string };

function useAliasCheck(alias: string): Check {
  const [state, setState] = useState<Check>({ s: "idle" });
  useEffect(() => {
    if (!alias) return setState({ s: "idle" });
    setState({ s: "checking" });
    let live = true;
    const t = setTimeout(() => {  // debounced: each check costs a rate-limit token
      api.checkAlias(alias).then(
        (r) => live && setState(r.available ? { s: "ok" } : { s: "bad", reason: r.reason ?? "Unavailable" }),
        () => live && setState({ s: "idle" }),
      );
    }, 350);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [alias]);
  return state;
}

export default function Composer() {
  const { setComposer, upsert, refresh } = useStore();
  const dialog = useRef<HTMLDialogElement>(null);
  const [text, setText] = useState("");
  const [alias, setAlias] = useState("");
  const [expires, setExpires] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [bulk, setBulk] = useState<{ rows: NewLink[]; results: BulkResult[] } | null>(null);
  const rows = parse(text);
  const isBulk = rows.length > 1;
  const check = useAliasCheck(isBulk ? "" : alias.trim());

  // native modal: focus trap, Esc and the backdrop come with <dialog>
  useEffect(() => {
    if (!dialog.current?.open) dialog.current?.showModal(); // StrictMode runs effects twice
  }, []);
  const close = () => dialog.current?.close(); // fires onClose -> unmount

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!rows.length || busy) return;
    setBusy(true);
    setError("");
    try {
      if (isBulk) {
        setBulk({ rows, results: (await api.createBulk(rows)).results });
        refresh();
      } else {
        const body: NewLink = { long_url: rows[0].long_url };
        if (alias.trim()) body.custom_alias = alias.trim();
        if (expires) body.expires_at = new Date(expires).toISOString(); // local time -> UTC
        const link = await api.createLink(body);
        upsert(link);
        close();
        navigate(`/links/${encodeURIComponent(link.short_code)}`);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const created = bulk?.results.filter((r) => r.ok).length ?? 0;
  return (
    <dialog
      ref={dialog}
      className="composer"
      aria-label="New link"
      onClose={() => setComposer(false)}
      onMouseDown={(e) => e.target === dialog.current && close()} // backdrop click
    >
      <form onSubmit={submit}>
        {bulk ? (
          <>
            <div className="bulk-head">
              {created} created{bulk.results.length - created ? ` · ${bulk.results.length - created} failed` : ""}
            </div>
            <div className="bulk-list">
              {bulk.results.map((r) => (
                <div key={r.index} className="bulk-row">
                  <span className={r.ok ? "ok" : "bad"} aria-label={r.ok ? "created" : "failed"}>{r.ok ? "✓" : "✗"}</span>
                  <span className="u">{bulk.rows[r.index]?.long_url}</span>
                  {r.ok ? <span className="mono" style={{ color: "var(--accent)" }}>/{r.link!.short_code}</span> : <span className="bad">{r.error}</span>}
                </div>
              ))}
            </div>
            <div className="foot"><span /><button type="button" className="btn primary" onClick={close} autoFocus>Done</button></div>
          </>
        ) : (
          <>
            <textarea
              autoFocus
              rows={isBulk ? Math.min(8, rows.length + 1) : 2}
              placeholder={"Paste a long URL\nor several, one per line, to shorten in bulk"}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !isBulk) {
                  e.preventDefault();
                  submit();
                }
              }}
              aria-label="Long URL"
            />
            {!isBulk && (
              <div className="opts">
                <div className="field">
                  <label htmlFor="alias">Alias (optional)</label>
                  <input id="alias" className="input" placeholder="my-launch" maxLength={32} value={alias} onChange={(e) => setAlias(e.target.value)} />
                  <div className={`hint ${check.s === "ok" ? "ok" : check.s === "bad" ? "bad" : ""}`} aria-live="polite">
                    {check.s === "checking" ? "Checking…" : check.s === "ok" ? "✓ Available" : check.s === "bad" ? `✗ ${check.reason}` : ""}
                  </div>
                </div>
                <div className="field">
                  <label htmlFor="exp">Expires (optional)</label>
                  <input id="exp" className="input" type="datetime-local" value={expires} onChange={(e) => setExpires(e.target.value)} />
                  <div className="hint">Leave empty to keep it forever.</div>
                </div>
              </div>
            )}
            {error && <div className="err" role="alert" style={{ padding: "0 18px 12px" }}>{error}</div>}
            <div className="foot">
              <span>
                {!isBulk ? "Paste several lines to shorten in bulk · Esc to close"
                  : rows.length > MAX_BULK ? `Too many lines (${rows.length}/${MAX_BULK})`
                  : `${rows.length} links · add ",alias" after a URL to name it`}
              </span>
              <span style={{ display: "flex", gap: 6 }}>
                <button type="button" className="btn" onClick={close}>Cancel</button>
                <button className="btn primary" disabled={busy || !rows.length || rows.length > MAX_BULK || check.s === "bad"}>
                  {busy ? <span className="spin" /> : isBulk ? `Create ${rows.length} links` : "Create link ↵"}
                </button>
              </span>
            </div>
          </>
        )}
      </form>
    </dialog>
  );
}
