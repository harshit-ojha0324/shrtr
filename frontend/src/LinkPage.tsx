import { useEffect, useState } from "react";
import { api, Gran, Link, n, series, shortDate, splitUrl, Stats, statusOf, sum, useLinkStats, useStore } from "./api";
import { A, BackIcon, CopyButton, EyeIcon, OpenIcon, QrCard } from "./ui";

const hourLabel = (t: number) => new Date(t).toLocaleTimeString(undefined, { hour: "numeric" });

function Kpis({ hour, day }: { hour?: Stats; day?: Stats }) {
  const h = series(hour?.series, "hour", 48);
  const last = sum(h.slice(24).map((p) => p.clicks));
  const prev = sum(h.slice(0, 24).map((p) => p.clicks));
  const change = prev ? Math.round(((last - prev) / prev) * 100) : null;
  const top = h.slice(24).reduce((m, p) => (p.clicks > m.clicks ? p : m));
  const peak = top.clicks ? top : null;
  return (
    <section className="panel kpis" aria-label="Click totals">
      <div className="kpi">
        <div className="l">Last 24 hours</div>
        <div className="v">{hour ? n(last) : "—"}</div>
        <div className={`d ${change === null ? "" : change >= 0 ? "up" : "down"}`}>
          {change === null ? "No clicks the day before" : `${change >= 0 ? "↑" : "↓"} ${Math.abs(change)}% vs day before`}
        </div>
      </div>
      <div className="kpi">
        <div className="l">Last 30 days</div>
        <div className="v">{day ? n(day.total_clicks) : "—"}</div>
        <div className="d">{day ? `${n(Math.round(day.total_clicks / 30))} a day` : ""}</div>
      </div>
      <div className="kpi">
        <div className="l">Busiest hour</div>
        <div className="v">{peak ? hourLabel(peak.t) : "—"}</div>
        <div className="d">{peak ? `${n(peak.clicks)} clicks` : "No clicks yet"}</div>
      </div>
    </section>
  );
}

const W = 640, H = 200, TOP = 24, BOTTOM = 16, PADX = 10;

function ClicksChart({ hour, day, error }: { hour?: Stats; day?: Stats; error: string }) {
  const [gran, setGran] = useState<Gran>("hour");
  const data = gran === "hour" ? hour : day;
  const pts = series(data?.series, gran, gran === "hour" ? 24 : 30);
  const peak = Math.max(...pts.map((p) => p.clicks));
  const max = Math.max(4, peak);
  const y = (v: number) => H - BOTTOM - (v / max) * (H - TOP - BOTTOM);
  const x = (i: number) => PADX + (i * (W - 2 * PADX)) / (pts.length - 1);
  const line = pts.map((p, i) => `${x(i).toFixed(1)},${y(p.clicks).toFixed(1)}`).join(" ");
  const fmt = (t: number) => (gran === "hour" ? hourLabel(t) : new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" }));
  const ticks = [0, 1, 2, 3].map((k) => Math.round((k * (pts.length - 1)) / 3));
  const empty = data && !pts.some((p) => p.clicks);
  return (
    <section className="panel chart" aria-label="Clicks over time">
      <div className="chart-top">
        <b>Clicks</b>
        <div className="seg" role="group" aria-label="Range">
          <button aria-pressed={gran === "hour"} onClick={() => setGran("hour")}>24h</button>
          <button aria-pressed={gran === "day"} onClick={() => setGran("day")}>30d</button>
        </div>
      </div>
      {error ? <p className="err">{error}</p> : (
        <>
          <div className={empty ? "chart-empty" : ""}>
            <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Clicks per ${gran}; busiest ${peak}`}>
              {[0, 0.5, 1].map((f) => <line key={f} className="g" x1="0" x2={W} y1={y(f * max)} y2={y(f * max)} />)}
              <polygon className="a" points={`${PADX},${H - BOTTOM} ${line} ${W - PADX},${H - BOTTOM}`} />
              <polyline className="ln" points={line} />
              {/* stops along the line like stations on a route; the busiest is the big filled one */}
              {pts.map((p, i) =>
                i % 3 === 0 || i === pts.length - 1 ? (
                  <circle key={i} className={i === pts.length - 1 ? "stop now" : "stop"} cx={x(i)} cy={y(p.clicks)} r={i === pts.length - 1 ? 6.5 : 5.5} />
                ) : null,
              )}
              {peak > 0 && (
                <circle className="peak" cx={x(pts.findIndex((p) => p.clicks === peak))} cy={y(peak)} r="10">
                  <title>{`Busiest: ${peak} clicks`}</title>
                </circle>
              )}
            </svg>
            {empty && <p>No clicks in this period yet.</p>}
          </div>
          <div className="axis">
            {ticks.map((i, k) => <span key={k}>{k === 3 ? (gran === "hour" ? "now" : "today") : fmt(pts[i].t)}</span>)}
          </div>
        </>
      )}
    </section>
  );
}

export default function LinkPage({ code }: { code: string }) {
  const { links, upsert } = useStore();
  const known = links.find((l) => l.short_code === code);
  const [fetched, setFetched] = useState<Link | null>(null);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const stats = useLinkStats(code);

  // a link outside the loaded list (deep link, or past the first 200)
  useEffect(() => {
    if (!known && !fetched) api.getLink(code).then(setFetched, (e: Error) => setError(e.message));
  }, [code, known, fetched]);

  const link = known ?? fetched;
  if (!link) {
    return error ? (
      <div className="empty"><div><h2>Couldn't open /{code}</h2><p>{error}</p></div></div>
    ) : (
      <div className="empty"><span className="spin" /></div>
    );
  }

  const status = statusOf(link);
  const host = new URL(link.short_url).host;
  const dest = splitUrl(link.long_url);

  async function remove() {
    try {
      await api.deleteLink(code);
      upsert({ ...link!, is_active: false });
      setConfirming(false);
    } catch (e) {
      setDeleteError((e as Error).message);
    }
  }

  return (
    <>
      <header className="head">
        <div style={{ minWidth: 0 }}>
          <div className="crumb">
            <A href="/" className="only-narrow" aria-label="Back to links"><BackIcon /></A>
            <A href="/">Links</A> › <span className={`pill ${status}`}>{status[0].toUpperCase() + status.slice(1)}</span>
          </div>
          <h1 className="h1">
            {status === "active" ? (
              <a className="short-link" href={link.short_url} target="_blank" rel="noreferrer" title="Open the short link">
                <span>{host}/</span>{link.short_code}
              </a>
            ) : (
              <><span>{host}/</span>{link.short_code}</>
            )}
          </h1>
          <div className="dest">→ <b>{dest.host}</b>{dest.rest}</div>
        </div>
        <div className="acts">
          {/* expired or deleted links no longer redirect: nothing to copy, open or preview */}
          {status === "active" && (
            <>
              <CopyButton text={link.short_url} className="btn primary" />
              <a className="btn" href={link.short_url} target="_blank" rel="noreferrer"><OpenIcon /> Open</a>
              <a className="btn" href={`${link.short_url}+`} target="_blank" rel="noreferrer"><EyeIcon /> Preview</a>
            </>
          )}
          {link.is_active && <button className="btn ghost danger" onClick={() => setConfirming(true)}>Delete</button>}
        </div>
      </header>
      {confirming && (
        <div className="confirm" role="alert">
          <span>Delete <b className="mono">/{link.short_code}</b>? It stops redirecting immediately. Its click history stays.</span>
          <button className="btn danger" onClick={remove}>Delete</button>
          <button className="btn ghost" onClick={() => setConfirming(false)}>Cancel</button>
          {deleteError && <span className="err">{deleteError}</span>}
        </div>
      )}
      <div className="body">
        <div className="col">
          <Kpis hour={stats.data?.hour} day={stats.data?.day} />
          <ClicksChart hour={stats.data?.hour} day={stats.data?.day} error={stats.error} />
          <p className="note">
            Only the time of each click is recorded: no IP address, device or referrer. Counts land a few
            seconds after each click; this page refreshes every 10 seconds.
          </p>
        </div>
        <div className="side">
          {status === "active" ? (
            <QrCard value={link.short_url} name={link.short_code} />
          ) : (
            <div className="panel inactive-note" role="note">
              <b>{status === "expired" ? "This link has expired" : "This link was deleted"}</b>
              <p>It no longer redirects, so there is no QR code to share. Its click history is kept.</p>
            </div>
          )}
          <div className="panel facts">
            <div><span>Created</span>{shortDate(link.created_at)}</div>
            <div><span>Expires</span>{link.expires_at ? shortDate(link.expires_at) : "Never"}</div>
            <div><span>Code</span><span className="mono" style={{ color: "var(--ink)" }}>{link.short_code}</span></div>
            <div><span>Redirect</span>302</div>
          </div>
        </div>
      </div>
    </>
  );
}
