import React, { useEffect, useRef, useState } from "react";
import { Upload, Save, Plus, X } from "lucide-react";
import { toast } from "sonner";
import { Card, Button, Input, Textarea, Spinner } from "./ui";
import { getProfile, saveProfile, parseCV } from "../api";

const BANNER = "https://images.unsplash.com/photo-1543269664-02e941c052f7?crop=entropy&cs=srgb&fm=jpg&q=85&w=940";

function Tags({ label, items, onChange, testid }) {
  const [val, setVal] = useState("");
  const add = () => { if (val.trim()) { onChange([...(items || []), val.trim()]); setVal(""); } };
  return (
    <div>
      <label className="text-xs uppercase tracking-wider text-zinc-500 font-mono">{label}</label>
      <div className="flex flex-wrap gap-2 mt-2 mb-2">
        {(items || []).map((t, i) => (
          <span key={i} className="inline-flex items-center gap-1 bg-amber-500/10 text-amber-300 border border-amber-500/25 rounded-full px-3 py-1 text-sm">
            {t}<button onClick={() => onChange(items.filter((_, j) => j !== i))}><X className="w-3 h-3" /></button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <Input value={val} onChange={(e) => setVal(e.target.value)} onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())} placeholder={`Add ${label.toLowerCase()}…`} data-testid={testid} />
        <Button variant="outline" onClick={add}><Plus className="w-4 h-4" /></Button>
      </div>
    </div>
  );
}

export default function ProfileView({ onSaved }) {
  const [p, setP] = useState(null);
  const [busy, setBusy] = useState(false);
  const [parsing, setParsing] = useState(false);
  const fileRef = useRef();

  useEffect(() => { getProfile().then(setP).catch(() => setP({})); }, []);

  const upload = async (e) => {
    const file = e.target.files[0]; if (!file) return;
    setParsing(true);
    try { const r = await parseCV(file); setP(r.profile); toast.success(r.parsed ? "CV parsed with AI" : "CV text saved"); }
    catch (err) { toast.error(err?.response?.data?.detail || "Could not parse CV"); }
    finally { setParsing(false); }
  };

  const save = async () => {
    setBusy(true);
    try { const saved = await saveProfile(p); setP(saved); toast.success("Profile saved"); onSaved && onSaved(); }
    catch { toast.error("Could not save"); }
    finally { setBusy(false); }
  };

  if (!p) return <div className="flex justify-center py-20"><Spinner className="text-amber-400 w-8 h-8" /></div>;
  const set = (k, v) => setP({ ...p, [k]: v });
  const lbl = "text-xs uppercase tracking-wider text-zinc-500 font-mono";

  return (
    <div className="max-w-3xl">
      <div className="relative rounded-3xl overflow-hidden mb-6 h-44 border border-white/5">
        <img src={BANNER} alt="candidate" className="w-full h-full object-cover" />
        <div className="absolute inset-0 bg-gradient-to-t from-[#0C0A09] via-[#0C0A09]/50 to-transparent flex items-end p-6">
          <div>
            <h2 className="font-display text-4xl font-normal text-white">{p.candidate_name || "The Candidate"}</h2>
            <p className="text-amber-300/80 text-sm font-mono mt-1">{p.target_roles?.join(" · ") || "Set up her profile to begin"}</p>
          </div>
        </div>
      </div>

      <Card className="p-6 mb-5">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h3 className="font-medium text-zinc-100">Upload her CV</h3>
            <p className="text-sm text-zinc-500">PDF or DOCX — we'll auto-extract skills, roles and a summary.</p>
          </div>
          <input ref={fileRef} type="file" accept=".pdf,.docx,.txt" className="hidden" onChange={upload} data-testid="cv-file-input" />
          <Button onClick={() => fileRef.current.click()} disabled={parsing} data-testid="upload-cv-btn">{parsing ? <><Spinner /> Parsing…</> : <><Upload className="w-4 h-4" /> Upload CV</>}</Button>
        </div>
      </Card>

      <Card className="p-6 space-y-4">
        <div className="grid sm:grid-cols-2 gap-3">
          <div><label className={lbl}>Name</label><Input className="mt-2" value={p.candidate_name || ""} onChange={(e) => set("candidate_name", e.target.value)} data-testid="input-name" /></div>
          <div><label className={lbl}>Email</label><Input className="mt-2" value={p.email || ""} onChange={(e) => set("email", e.target.value)} data-testid="input-email" /></div>
          <div><label className={lbl}>Phone</label><Input className="mt-2" value={p.phone || ""} onChange={(e) => set("phone", e.target.value)} /></div>
          <div><label className={lbl}>Experience</label><Input className="mt-2" placeholder="e.g. 3 years" value={p.years_experience || ""} onChange={(e) => set("years_experience", e.target.value)} /></div>
        </div>
        <Tags label="Target roles" items={p.target_roles} onChange={(v) => set("target_roles", v)} testid="input-target-role" />
        <Tags label="Skills" items={p.skills} onChange={(v) => set("skills", v)} testid="input-skill" />
        <div><label className={lbl}>Professional summary</label><Textarea className="mt-2" rows={4} value={p.summary || ""} onChange={(e) => set("summary", e.target.value)} data-testid="input-summary" /></div>
        <div className="flex justify-end"><Button onClick={save} disabled={busy} data-testid="save-profile-btn">{busy ? <Spinner /> : <Save className="w-4 h-4" />} Save profile</Button></div>
      </Card>
    </div>
  );
}
