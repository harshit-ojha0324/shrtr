// Small shared pieces: a 3-route router, icons, buttons, sparkline, QR card.
import { AnchorHTMLAttributes, useRef, useState, useSyncExternalStore } from "react";
import { QRCodeCanvas } from "qrcode.react";

/* ---- router: pushState + popstate is all three routes need ---- */

const onNav = (cb: () => void) => {
  window.addEventListener("popstate", cb);
  return () => window.removeEventListener("popstate", cb);
};
export const usePath = () => useSyncExternalStore(onNav, () => location.pathname);

export function navigate(to: string) {
  history.pushState(null, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function A({ href = "/", onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a
      href={href}
      {...rest}
      onClick={(e) => {
        onClick?.(e);
        // let the browser handle new-tab clicks
        if (e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        navigate(href);
      }}
    />
  );
}

/* ---- icons ---- */

const P = {
  viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: 1.6,
  strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true,
};
export const CopyIcon = () => <svg {...P}><rect x="5" y="5" width="8" height="8" rx="2" /><path d="M3 10.5V4a1 1 0 0 1 1-1h6.5" /></svg>;
export const OpenIcon = () => <svg {...P}><path d="M9 3h4v4M13 3 7 9M11.5 9.5V12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5.5a1 1 0 0 1 1-1h2.5" /></svg>;
export const EyeIcon = () => <svg {...P}><path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8Z" /><circle cx="8" cy="8" r="2" /></svg>;
export const SearchIcon = () => <svg {...P} width="14" height="14"><circle cx="7" cy="7" r="4.5" /><path d="m10.5 10.5 3 3" /></svg>;
export const BackIcon = () => <svg {...P}><path d="M10 3 5 8l5 5" /></svg>;
export const KeyIcon = () => <svg {...P}><circle cx="5.5" cy="10.5" r="3" /><path d="m7.6 8.4 5.9-5.9M11 5l1.5 1.5" /></svg>;
export const StackIcon = () => <svg {...P}><path d="M2 5.5 8 2.5l6 3-6 3-6-3ZM2 8.5l6 3 6-3M2 11.5l6 3 6-3" /></svg>;
const SunIcon = () => <svg {...P}><circle cx="8" cy="8" r="3" /><path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M3 13l1-1M12 4l1-1" /></svg>;
const MoonIcon = () => <svg {...P}><path d="M13.5 9.5A5.5 5.5 0 1 1 6.5 2.5a4.5 4.5 0 0 0 7 7Z" /></svg>;

/* ---- controls ---- */

export function CopyButton({ text, className = "btn" }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className={className}
      onClick={() =>
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1400);
        }, () => prompt("Copy this link:", text)) // clipboard needs https or localhost
      }
    >
      <CopyIcon /> <span aria-live="polite">{copied ? "Copied" : "Copy"}</span>
    </button>
  );
}

export function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  function toggle() {
    document.documentElement.classList.toggle("dark", !dark);
    try { localStorage.setItem("theme", dark ? "light" : "dark"); } catch { /* not persisted */ }
    setDark(!dark);
  }
  return (
    <button type="button" className="btn ghost icon" onClick={toggle} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}>
      {dark ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}

export function Sparkline({ values, width = 56, height = 18 }: { values: number[]; width?: number; height?: number }) {
  const max = Math.max(1, ...values);
  const pts = values
    .map((v, i) => `${((i * width) / (values.length - 1 || 1)).toFixed(1)},${(height - 1 - (v / max) * (height - 3)).toFixed(1)}`)
    .join(" ");
  return (
    <svg className="spark" viewBox={`0 0 ${width} ${height}`} width={width} height={height} aria-hidden="true">
      <polyline points={pts} />
    </svg>
  );
}

export function QrCard({ value, name }: { value: string; name: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  function download() {
    const canvas = wrap.current?.querySelector("canvas");
    if (!canvas) return;
    const a = document.createElement("a");
    a.href = canvas.toDataURL("image/png");
    a.download = `${name}-qr.png`;
    a.click();
  }
  return (
    <div className="panel qrbox">
      {/* always black on white so phones can scan it in dark mode */}
      <div ref={wrap} className="qr">
        <QRCodeCanvas value={value} size={352} marginSize={0} level="M" style={{ width: "100%", height: "auto", maxWidth: 176 }} />
      </div>
      <button type="button" className="btn" onClick={download}>Download PNG</button>
    </div>
  );
}
