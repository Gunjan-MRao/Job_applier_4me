import React from "react";

export function Card({ children, className = "" }) {
  return (
    <div className={`bg-[#1C1917] border border-white/5 rounded-[16px] overflow-hidden shadow-sm ${className}`}>
      {children}
    </div>
  );
}

export function Badge({ children, variant = "default", className = "" }) {
  const variants = {
    default:  "bg-white/10 text-zinc-200 border-white/10",
    amber:    "bg-amber-500/15 text-amber-300 border-amber-500/20",
    emerald:  "bg-emerald-500/10 text-emerald-400 border-emerald-500/20 glow-emerald",
    rose:     "bg-rose-500/10 text-rose-400 border-rose-500/20",
    zinc:     "bg-zinc-800 text-zinc-400 border-zinc-700",
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-mono
      border ${variants[variant] || variants.default} ${className}`}>
      {children}
    </span>
  );
}

export function Button({ children, onClick, variant = "primary", disabled = false, className = "", ...props }) {
  const variants = {
    primary:  "bg-amber-500 hover:bg-amber-400 text-[#0C0A09] font-semibold shadow-[0_0_16px_rgba(245,158,11,0.3)]",
    ghost:    "bg-transparent hover:bg-white/5 text-zinc-300 hover:text-white border border-white/10",
    danger:   "bg-rose-500/15 hover:bg-rose-500/25 text-rose-400 border border-rose-500/20",
    emerald:  "bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-400 border border-emerald-500/20",
  };
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm
        transition-[background-color,transform,opacity] duration-200
        active:scale-[0.97] disabled:opacity-40 disabled:cursor-not-allowed
        ${variants[variant] || variants.primary} ${className}`}
      {...props}>
      {children}
    </button>
  );
}

export function Spinner({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      className="animate-spin" xmlns="http://www.w3.org/2000/svg">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" strokeOpacity="0.25" />
      <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function SectionHeader({ label, sub }) {
  return (
    <div className="mb-6">
      <p className="text-xs font-mono uppercase tracking-[0.2em] text-zinc-500 mb-1">{label}</p>
      {sub && <h2 className="font-display text-3xl text-white font-normal">{sub}</h2>}
    </div>
  );
}
