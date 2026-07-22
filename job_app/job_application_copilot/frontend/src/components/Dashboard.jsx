import React from "react";
import { motion } from "framer-motion";
import { Briefcase, ShieldCheck, Send, Trophy, ArrowRight } from "lucide-react";
import Countdown from "./Countdown";
import { Card, Button, FitBadge } from "./ui";

function Stat({ icon: Icon, label, value, tint, testid }) {
  return (
    <Card className="p-5 hover:border-white/15 transition-colors" data-testid={testid}>
      <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${tint}`}><Icon className="w-5 h-5" strokeWidth={1.5} /></div>
      <div className="font-mono text-4xl font-light text-white mt-4 tabular-nums">{value}</div>
      <div className="text-xs font-mono uppercase tracking-[0.15em] text-zinc-500 mt-1">{label}</div>
    </Card>
  );
}

export default function Dashboard({ date, stats, jobs, goto }) {
  const top = [...jobs].sort((a, b) => b.fit_score - a.fit_score).slice(0, 4);
  const by = stats.by_status || {};
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
        <div className="md:col-span-8"><Countdown date={date} /></div>
        <div className="md:col-span-4 grid grid-cols-2 gap-4">
          <Stat icon={Briefcase} label="Opportunities" value={stats.total || 0} tint="bg-amber-500/10 text-amber-400" testid="stat-total" />
          <Stat icon={ShieldCheck} label="Sponsors" value={stats.sponsors || 0} tint="bg-emerald-500/10 text-emerald-400" testid="stat-sponsors" />
          <Stat icon={Send} label="Applied" value={by.applied || 0} tint="bg-sky-500/10 text-sky-400" testid="stat-applied" />
          <Stat icon={Trophy} label="Offers" value={by.offer || 0} tint="bg-rose-500/10 text-rose-400" testid="stat-offers" />
        </div>
      </div>

      <div className="flex items-center justify-between pt-2">
        <h2 className="font-display text-3xl font-normal text-white">Best matches right now</h2>
        <Button variant="ghost" onClick={() => goto("jobs")} data-testid="view-all-jobs">View all <ArrowRight className="w-4 h-4" /></Button>
      </div>

      {top.length === 0 ? (
        <Card className="p-12 text-center">
          <p className="font-display text-2xl text-white">Let's get started</p>
          <p className="text-sm mt-2 text-zinc-400">Set up her profile, then add jobs — we'll verify sponsors and draft tailored applications.</p>
          <Button className="mt-5" onClick={() => goto("profile")}>Set up profile <ArrowRight className="w-4 h-4" /></Button>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {top.map((j, i) => (
            <motion.div key={j.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}>
              <Card className="p-5 h-full cursor-pointer hover:-translate-y-1 hover:border-amber-500/30 transition-[transform,border-color] duration-300" onClick={() => goto("jobs")}>
                <FitBadge score={j.fit_score} level={j.fit_level} />
                <h3 className="font-medium text-zinc-100 mt-3 leading-snug">{j.title}</h3>
                <p className="text-sm text-zinc-500 mt-1">{j.company}</p>
              </Card>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
