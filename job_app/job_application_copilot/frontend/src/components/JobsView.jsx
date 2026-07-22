import React, { useState } from "react";
import { motion } from "framer-motion";
import { Plus, Search, Sparkles, Building2, MapPin, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { Card, Button, Input, Textarea, Modal, FitBadge, SponsorBadge, Spinner } from "./ui";
import { addJob, discover, generateAll } from "../api";
import JobDetail from "./JobDetail";

const empty = { title: "", company: "", location: "United Kingdom", url: "", salary: "", description: "" };

export default function JobsView({ jobs, reload }) {
  const [selected, setSelected] = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState(false);
  const [disc, setDisc] = useState(false);
  const [genAll, setGenAll] = useState(false);
  const [query, setQuery] = useState("");
  const [track, setTrack] = useState("uk_sponsored");

  const shown = jobs.filter((j) => (j.track || "uk_sponsored") === track);

  const submit = async () => {
    if (!form.title || !form.company) { toast.error("Title and company are required"); return; }
    setBusy(true);
    try {
      await addJob(form);
      toast.success("Job added — sponsor checked & documents drafted");
      setShowAdd(false); setForm(empty); reload();
    } catch { toast.error("Could not add job"); }
    finally { setBusy(false); }
  };

  const runDiscover = async () => {
    setDisc(true);
    try {
      const r = await discover({ query, location: "United Kingdom" });
      toast.success(r.message || `Discovered ${r.created} jobs`);
      reload();
    } catch { toast.error("Discovery failed"); }
    finally { setDisc(false); }
  };

  const runGenerateAll = async () => {
    setGenAll(true);
    try { const r = await generateAll(); toast.success(`Drafted documents for ${r.generated} jobs`); reload(); }
    catch { toast.error("Bulk generation failed"); }
    finally { setGenAll(false); }
  };

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <h2 className="font-display text-4xl font-normal text-white">Opportunities</h2>
          <p className="text-zinc-500 text-sm mt-1 font-mono">{shown.length} roles · {track === "uk_sponsored" ? "sponsor-verified & AI-scored" : "remote & international"}</p>
        </div>
        <div className="flex gap-2">
          <div className="flex items-center gap-1 bg-[#1C1917] border border-white/10 rounded-full pl-3 pr-1 py-1">
            <Search className="w-4 h-4 text-zinc-500" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Discover roles..." className="bg-transparent text-sm text-zinc-100 placeholder-zinc-600 outline-none w-36" data-testid="discover-input" />
            <Button onClick={runDiscover} disabled={disc} className="px-3 py-1.5 text-sm" data-testid="discover-btn">{disc ? <Spinner /> : <Sparkles className="w-4 h-4" />}</Button>
          </div>
          <Button onClick={() => setShowAdd(true)} data-testid="add-job-btn"><Plus className="w-4 h-4" /> Add job</Button>
          {shown.length > 0 && <Button variant="outline" onClick={runGenerateAll} disabled={genAll} data-testid="generate-all-btn">{genAll ? <Spinner /> : <Wand2 className="w-4 h-4" />} Generate all</Button>}
        </div>
      </div>

      <div className="inline-flex bg-[#0C0A09] border border-white/10 rounded-full p-1 mb-6">
        {[["uk_sponsored", "🇬🇧 UK Sponsored"], ["remote_intl", "🌍 Remote & International"]].map(([k, label]) => (
          <button key={k} onClick={() => setTrack(k)} data-testid={`track-${k}`}
            className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${track === k ? "bg-white/10 text-white" : "text-zinc-500 hover:text-zinc-200"}`}>
            {label} <span className="text-xs font-mono text-zinc-600">{jobs.filter((j) => (j.track || "uk_sponsored") === k).length}</span>
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <Card className="p-12 text-center" data-testid="jobs-empty">
          <p className="font-display text-2xl text-white">No jobs here yet</p>
          <p className="mt-2 text-sm text-zinc-400">Use "Discover" to auto-search job boards, or "Add job" to paste one — we'll verify the sponsor licence and draft a tailored cover letter.</p>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((j, i) => (
            <motion.div key={j.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i * 0.02, 0.4) }}>
              <Card className="p-5 cursor-pointer hover:-translate-y-1 hover:border-amber-500/30 transition-[transform,border-color] duration-300" onClick={() => setSelected(j)} data-testid={`job-card-${i}`}>
                <div className="flex items-start justify-between gap-2">
                  {j.track === "remote_intl"
                    ? <span className="inline-flex items-center rounded-full bg-sky-500/10 text-sky-300 border border-sky-500/25 px-2 py-0.5 text-[11px] font-mono">{j.remote ? "Remote" : "International"}</span>
                    : <SponsorBadge verified={j.is_licensed_sponsor} small />}
                  {(j.track !== "remote_intl" || j.fit_score > 0) && <FitBadge score={j.fit_score} level={j.fit_level} />}
                </div>
                <h3 className="font-medium text-zinc-100 mt-3 leading-snug">{j.title}</h3>
                <div className="text-sm text-zinc-500 mt-1 space-y-0.5">
                  <div className="flex items-center gap-1"><Building2 className="w-3.5 h-3.5" strokeWidth={1.5} />{j.company}</div>
                  <div className="flex items-center gap-1"><MapPin className="w-3.5 h-3.5" strokeWidth={1.5} />{j.location}</div>
                </div>
                <div className="mt-3 flex items-center justify-between text-[11px] font-mono uppercase tracking-wider text-zinc-600">
                  <span>{j.source}</span>
                  <span className={j.cover_letter ? "text-emerald-400/80" : ""}>{j.cover_letter ? "✓ drafted" : "no docs yet"}</span>
                </div>
              </Card>
            </motion.div>
          ))}
        </div>
      )}

      <Modal open={showAdd} onClose={() => setShowAdd(false)} testid="add-job-modal">
        <div className="p-6 sm:p-8">
          <h2 className="font-display text-3xl font-normal mb-1 text-white">Add a job</h2>
          <p className="text-zinc-400 text-sm mb-5">We'll verify the sponsor licence and draft tailored materials.</p>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Input placeholder="Job title *" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} data-testid="input-title" />
              <Input placeholder="Company *" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} data-testid="input-company" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Input placeholder="Location" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} data-testid="input-location" />
              <Input placeholder="Salary (optional)" value={form.salary} onChange={(e) => setForm({ ...form, salary: e.target.value })} />
            </div>
            <Input placeholder="Job URL (optional)" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} data-testid="input-url" />
            <Textarea rows={6} placeholder="Paste the job description here" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} data-testid="input-description" />
          </div>
          <div className="flex justify-end gap-2 mt-5">
            <Button variant="outline" onClick={() => setShowAdd(false)}>Cancel</Button>
            <Button onClick={submit} disabled={busy} data-testid="submit-job-btn">{busy ? <><Spinner /> Drafting…</> : "Add & draft"}</Button>
          </div>
        </div>
      </Modal>

      <JobDetail job={selected} onClose={() => setSelected(null)} onChange={reload} />
    </div>
  );
}
