import React, { useEffect, useState } from "react";
import { Plane } from "lucide-react";

const HERO = "https://images.pexels.com/photos/2611465/pexels-photo-2611465.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940";

function diff(target) {
  const t = new Date(target + "T06:00:00Z").getTime();
  const now = Date.now();
  const d = Math.max(0, t - now);
  return {
    days: Math.floor(d / 86400000),
    hours: Math.floor((d % 86400000) / 3600000),
    mins: Math.floor((d % 3600000) / 60000),
    secs: Math.floor((d % 60000) / 1000),
    past: t < now,
  };
}

export default function Countdown({ date }) {
  const [t, setT] = useState(diff(date));
  useEffect(() => {
    const i = setInterval(() => setT(diff(date)), 1000);
    return () => clearInterval(i);
  }, [date]);

  const cell = (v, l) => (
    <div className="text-center" data-testid={`countdown-${l}`}>
      <div className="font-mono text-4xl sm:text-6xl font-light tabular-nums text-amber-400 glow-amber">{String(v).padStart(2, "0")}</div>
      <div className="text-[10px] font-mono tracking-[0.3em] uppercase text-zinc-500 mt-2">{l}</div>
    </div>
  );

  const sep = <div className="text-3xl sm:text-5xl font-light text-amber-400/40 heartbeat self-start mt-1 sm:mt-2">:</div>;

  return (
    <div className="relative overflow-hidden rounded-3xl grain min-h-[340px] flex items-end border border-white/5" data-testid="countdown-timer">
      <img src={HERO} alt="London skyline at dusk" className="absolute inset-0 w-full h-full object-cover" />
      <div className="absolute inset-0 bg-gradient-to-b from-black/40 via-[#0C0A09]/85 to-[#0C0A09]" />
      <div className="relative z-10 p-8 sm:p-10 w-full">
        <div className="flex items-center gap-2 text-amber-400/90 mb-4">
          <Plane className="w-4 h-4" strokeWidth={1.5} />
          <span className="font-mono tracking-[0.25em] uppercase text-[11px]">One-way · {date}</span>
        </div>
        <h1 className="font-display text-4xl sm:text-6xl font-light leading-[1.05] mb-8 max-w-2xl text-white">
          The round trip <span className="italic text-amber-300">starts here.</span>
        </h1>
        <div className="flex items-start gap-3 sm:gap-6">
          {cell(t.days, "days")}
          {sep}
          {cell(t.hours, "hrs")}
          {sep}
          {cell(t.mins, "min")}
          {sep}
          {cell(t.secs, "sec")}
        </div>
      </div>
    </div>
  );
}
