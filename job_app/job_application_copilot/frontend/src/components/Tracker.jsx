import React, { useState } from "react";
import { toast } from "sonner";
import { Card, FitBadge, SponsorBadge } from "./ui";
import { updateJob } from "../api";
import JobDetail from "./JobDetail";

const COLUMNS = [
  ["saved", "Saved"],
  ["applied", "Applied"],
  ["interview", "Interview"],
  ["offer", "Offer"],
];
const CONFETTI = "https://images.unsplash.com/photo-1569705460033-cfaa4bf9f822?crop=entropy&cs=srgb&fm=jpg&q=85&w=400";

export default function Tracker({ jobs, reload }) {
  const [selected, setSelected] = useState(null);
  const [dragId, setDragId] = useState(null);

  const move = async (id, status) => {
    try {
      await updateJob(id, status);
      if (status === "offer") toast.success("🎉 An offer! That round trip is within reach.");
      else toast.success(`Moved to ${status}`);
      reload();
    } catch { toast.error("Could not update"); }
  };

  const onDrop = (status) => { if (dragId) move(dragId, status); setDragId(null); };

  return (
    <div>
      <h2 className="font-display text-4xl font-normal text-white mb-1">Application Tracker</h2>
      <p className="text-zinc-500 text-sm mb-6 font-mono">Drag cards across stages as her hunt progresses.</p>

      <div className="grid gap-4 md:grid-cols-4">
        {COLUMNS.map(([key, label]) => {
          const col = jobs.filter((j) => (j.status || "saved") === key);
          return (
            <div key={key} className="bg-white/[0.02] border border-white/5 rounded-2xl p-4 min-h-[320px]"
              onDragOver={(e) => e.preventDefault()} onDrop={() => onDrop(key)} data-testid={`column-${key}`}>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-xs font-mono tracking-[0.2em] uppercase text-zinc-500">{label}</h3>
                <span className="text-xs font-mono text-zinc-600">{col.length}</span>
              </div>
              {key === "offer" && col.length > 0 && (
                <img src={CONFETTI} alt="celebration" className="rounded-xl mb-3 h-20 w-full object-cover opacity-90" />
              )}
              <div className="space-y-3">
                {col.map((j) => (
                  <Card key={j.id} draggable onDragStart={() => setDragId(j.id)} onClick={() => setSelected(j)}
                    className="p-3 cursor-grab active:cursor-grabbing hover:border-amber-500/30 transition-colors" data-testid={`tracker-card-${j.id}`}>
                    <div className="flex items-center gap-2 mb-2">
                      <FitBadge score={j.fit_score} level={j.fit_level} />
                    </div>
                    <p className="font-medium text-sm text-zinc-100 leading-snug">{j.title}</p>
                    <p className="text-xs text-zinc-500 mt-0.5">{j.company}</p>
                    <div className="mt-2"><SponsorBadge verified={j.is_licensed_sponsor} small /></div>
                  </Card>
                ))}
                {col.length === 0 && <p className="text-xs text-zinc-600 text-center py-6">Drop here</p>}
              </div>
            </div>
          );
        })}
      </div>
      <JobDetail job={selected} onClose={() => setSelected(null)} onChange={reload} />
    </div>
  );
}
