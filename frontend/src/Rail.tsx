import { useEffect, useRef, useState } from "react";
import { Link, LinkStatus, n, series, splitUrl, statusOf, sum, useStore } from "./api";
import { A, KeyIcon, SearchIcon, Sparkline, StackIcon, ThemeToggle } from "./ui";

type Filter = "all" | LinkStatus;
const FILTERS: Filter[] = ["all", "active", "expired", "deleted"];
const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

function Row({ link, selected }: { link: Link; selected: boolean }) {
  const { activity } = useStore();
  const status = statusOf(link);
  const h = series(activity[link.short_code], "hour", 24).map((p) => p.clicks);
  const spark = Array.from({ length: 12 }, (_, i) => h[i * 2] + h[i * 2 + 1]); // 2-hour points
  return (
    <A href={`/links/${encodeURIComponent(link.short_code)}`} className={`item ${status}`} aria-current={selected ? "page" : undefined} title={link.long_url}>
      <span className={`dot ${status}`} role="img" aria-label={status} />
      <div style={{ minWidth: 0 }}>
        <div className="c">/{link.short_code}</div>
        <div className="h">{splitUrl(link.long_url).host}</div>
      </div>
      <div className="n" title="Clicks in the last 24 hours">
        <span>{n(sum(h))}</span>
        <Sparkline values={spark} />
      </div>
    </A>
  );
}

export default function Rail({ selected }: { selected?: string }) {
  const { links, loading, error, hasKey, setComposer } = useStore();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const search = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) {
        e.preventDefault();
        search.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const counts: Record<Filter, number> = { all: links.length, active: 0, expired: 0, deleted: 0 };
  links.forEach((l) => counts[statusOf(l)]++);
  const t = q.trim().toLowerCase();
  const shown = links.filter(
    (l) =>
      (filter === "all" || statusOf(l) === filter) &&
      (!t || l.short_code.toLowerCase().includes(t) || l.long_url.toLowerCase().includes(t)),
  );

  return (
    <aside className="rail" aria-label="Your links">
      <div className="rail-top">
        <div className="brand">
          <A href="/"><span className="mark" />shrtr</A>
          <span className="kbd" title="Ctrl+K or N: new link · /: search">⌘K</span>
        </div>
        <button className="newbtn" onClick={() => setComposer(true)}>New link <span className="kbd">N</span></button>
        <label className="search">
          <SearchIcon />
          <input ref={search} placeholder="Search links" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search links" />
        </label>
        <div className="filters" role="group" aria-label="Filter by status">
          {FILTERS.map((f) => (
            <button key={f} aria-pressed={filter === f} onClick={() => setFilter(f)}>{cap(f)} {counts[f]}</button>
          ))}
        </div>
      </div>
      {!hasKey && (
        <div className="banner">
          Add your API key in <A href="/settings">Settings</A> to see your links. <code className="mono">make seed</code> prints one.
        </div>
      )}
      <nav className="list">
        {error && <div className="rail-msg err">{error}</div>}
        {hasKey && loading && !links.length && <div className="rail-msg"><span className="spin" /></div>}
        {hasKey && !loading && !error && !shown.length && (
          <div className="rail-msg">{t || filter !== "all" ? "No links match." : "No links yet. Press N to create one."}</div>
        )}
        {shown.map((l) => <Row key={l.short_code} link={l} selected={l.short_code === selected} />)}
      </nav>
      <div className="rail-foot">
        <button className="btn ghost" onClick={() => setComposer(true)}><StackIcon /> Bulk import</button>
        <div style={{ display: "flex", gap: 2 }}>
          <A className="btn ghost" href="/settings"><KeyIcon /> API key</A>
          <ThemeToggle />
        </div>
      </div>
    </aside>
  );
}
