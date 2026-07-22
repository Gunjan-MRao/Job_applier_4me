import React, { useEffect, useState } from "react";
import { X, Copy, RefreshCw, ExternalLink, Trash2, MapPin, Building2, FileDown, Send, Check, AtSign, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Button, Modal, FitBadge, SponsorBadge, Spinner, Input } from "./ui";
import { regenerate, deleteJob, sendEmail, recruiterEmail } from "../api";

const BASE = process.env.REACT_APP_BACKEND_URL;

export default function JobDetail({ job, onClose, onChange }) {
  const [tab, setTab] = useState("cover");
  const [busy, setBusy] = useState(false);
  const [j, setJ] = useState(job);
  const [showEmail, setShowEmail] = useState(false);
  const [recipient, setRecipient] = useState("");
  const [toSelf, setToSelf] = useState(false);
  const [attachPdf, setAttachPdf] = useState(true);
  const [sending, setSending] = useState(false);
  const [contacts, setContacts] = useState(null);
  const [findingContacts, setFindingContacts] = useState(false);
  useEffect(() => { setJ(job); setContacts(null); }, [job]);
  if (!job || !j) return null;

  const copy = (text) => { navigator.clipboard.writeText(text || ""); toast.success("Copied to clipboard"); };

  const regen = async () => {
    setBusy(true);
    try { const r = await regenerate(j.id); setJ(r); onChange && onChange(); toast.success("Documents regenerated"); }
    catch { toast.error("Could not regenerate"); }
    finally { setBusy(false); }
  };

  const remove = async () => {
    await deleteJob(j.id); onChange && onChange(); onClose(); toast.success("Removed");
  };

  const download = (fmt) => {
    window.open(`${BASE}/api/jobs/${j.id}/export?format=${fmt}`, "_blank");
  };

  const doSend = async () => {
    setSending(true);
    try {
      const r = await sendEmail(j.id, { recipient_email: recipient, to_self: toSelf, attach_pdf: attachPdf });
      if (r.needs_key) toast.info(r.message);
      else { toast.success(r.message); setShowEmail(false); onChange && onChange(); setJ({ ...j, email_sent_to: r.sent_to }); }
    } catch (e) { toast.error(e?.response?.data?.detail || "Send failed"); }
    finally { setSending(false); }
  };

  const findContacts = async () => {
    setFindingContacts(true);
    try { setContacts(await recruiterEmail(j.id)); }
    catch { toast.error("Could not find contacts"); }
    finally { setFindingContacts(false); }
  };

  const tabs = [["cover", "Cover Letter"], ["cv", "CV Summary"], ["recruiter", "Recruiter Msg"], ["contacts", "Find Email"], ["fit", "Why You Fit"]];
  const hasDocs = !!j.cover_letter;
  const pre = "whitespace-pre-wrap font-body text-sm text-zinc-300 leading-relaxed bg-[#0C0A09] border border-white/10 rounded-xl p-4";

  return (
    <Modal open={!!job} onClose={onClose} testid="job-detail-modal">
      <div className="p-6 sm:p-8">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-display text-3xl font-normal text-white" data-testid="job-detail-title">{j.title}</h2>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-zinc-500 mt-1">
              <span className="flex items-center gap-1"><Building2 className="w-4 h-4" strokeWidth={1.5} />{j.company}</span>
              <span className="flex items-center gap-1"><MapPin className="w-4 h-4" strokeWidth={1.5} />{j.location}</span>
            </div>
          </div>
          <button onClick={onClose} className="text-zinc-500 hover:text-white transition-colors" data-testid="job-detail-close"><X /></button>
        </div>

        <div className="flex flex-wrap items-center gap-2 mt-4">
          <FitBadge score={j.fit_score} level={j.fit_level} />
          <SponsorBadge verified={j.is_licensed_sponsor} />
          {j.match && <span className="text-xs font-mono text-emerald-400/80">{j.match.rating} · {j.match.city}</span>}
        </div>

        <div className="flex gap-1 mt-6 border-b border-white/10 overflow-x-auto">
          {tabs.map(([k, label]) => (
            <button key={k} onClick={() => setTab(k)}
              className={`px-4 py-2 text-sm font-medium -mb-px border-b-2 whitespace-nowrap transition-colors ${tab === k ? "border-amber-500 text-amber-400" : "border-transparent text-zinc-500 hover:text-zinc-200"}`}
              data-testid={`tab-${k}`}>{label}</button>
          ))}
        </div>

        <div className="mt-4 min-h-[220px]">
          {!hasDocs ? (
            <div className="text-center py-10 border border-dashed border-white/15 rounded-2xl bg-white/[0.02]" data-testid="no-docs-cta">
              <p className="font-display text-xl text-white">No documents drafted yet</p>
              <p className="text-sm text-zinc-400 mt-1 mb-4">Generate a tailored cover letter, CV summary & recruiter message for this role.</p>
              <Button onClick={regen} disabled={busy} data-testid="generate-docs-btn">{busy ? <><Spinner /> Drafting…</> : <><RefreshCw className="w-4 h-4" /> Generate documents</>}</Button>
            </div>
          ) : (<>
          {tab === "cover" && (
            <div>
              <pre className={pre} data-testid="cover-letter-text">{j.cover_letter}</pre>
              <Button variant="outline" className="mt-3" onClick={() => copy(j.cover_letter)} data-testid="copy-cover-letter"><Copy className="w-4 h-4" /> Copy</Button>
            </div>
          )}
          {tab === "cv" && (
            <div>
              <pre className={pre} data-testid="cv-summary-text">{j.cv_summary}</pre>
              {j.tailoring_tips && (
                <ul className="mt-3 space-y-1 text-sm text-zinc-400 list-disc pl-5">
                  {j.tailoring_tips.map((t, i) => <li key={i}>{t}</li>)}
                </ul>
              )}
              <Button variant="outline" className="mt-3" onClick={() => copy(j.cv_summary)}><Copy className="w-4 h-4" /> Copy</Button>
            </div>
          )}
          {tab === "recruiter" && (
            <div>
              <pre className={pre} data-testid="recruiter-message-text">{j.recruiter_message || "—"}</pre>
              <Button variant="outline" className="mt-3" onClick={() => copy(j.recruiter_message)} data-testid="copy-recruiter-message"><Copy className="w-4 h-4" /> Copy</Button>
            </div>
          )}
          {tab === "fit" && (
            <ul className="space-y-2 text-sm text-zinc-300">
              {(j.why_fit || []).map((r, i) => (
                <li key={i} className="flex gap-2"><span className="text-amber-400">•</span>{r}</li>
              ))}
            </ul>
          )}
          {tab === "contacts" && (
            <div data-testid="contacts-panel">
              {!contacts ? (
                <div className="text-center py-8">
                  <p className="text-sm text-zinc-400 mb-4">Find likely hiring-contact emails at <strong className="text-zinc-200">{j.company}</strong> to send your message to.</p>
                  <Button onClick={findContacts} disabled={findingContacts} data-testid="find-email-btn">{findingContacts ? <><Spinner /> Searching…</> : <><AtSign className="w-4 h-4" /> Find recruiter emails</>}</Button>
                </div>
              ) : (
                <div className="space-y-3">
                  {contacts.domains?.length > 0 && <p className="text-xs font-mono text-zinc-500">Company domain: {contacts.domains.join(", ")}</p>}
                  {contacts.verified?.length > 0 && (
                    <div>
                      <p className="text-xs uppercase tracking-wider text-emerald-400 font-semibold mb-2 flex items-center gap-1"><ShieldCheck className="w-3.5 h-3.5" /> Verified contacts</p>
                      {contacts.verified.map((e, i) => (
                        <div key={i} className="flex items-center justify-between bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2 mb-2">
                          <div className="text-sm"><span className="font-mono text-zinc-100">{e.email}</span>{e.role && <span className="text-zinc-500 text-xs ml-2">{e.role}</span>}</div>
                          <button onClick={() => copy(e.email)} className="text-zinc-500 hover:text-amber-400 transition-colors"><Copy className="w-4 h-4" /></button>
                        </div>
                      ))}
                    </div>
                  )}
                  <div>
                    <p className="text-xs uppercase tracking-wider text-zinc-500 font-semibold mb-2">Likely hiring inboxes (best guesses)</p>
                    {(contacts.guesses || []).map((e, i) => (
                      <div key={i} className="flex items-center justify-between bg-[#0C0A09] border border-white/10 rounded-lg px-3 py-2 mb-2" data-testid={`guess-email-${i}`}>
                        <span className="text-sm font-mono text-zinc-300">{e.email}</span>
                        <button onClick={() => copy(e.email)} className="text-zinc-500 hover:text-amber-400 transition-colors"><Copy className="w-4 h-4" /></button>
                      </div>
                    ))}
                  </div>
                  {!contacts.hunter_enabled && <p className="text-xs text-zinc-600 italic">Tip: these are role-based best guesses. Add a Hunter.io key for verified named recruiter emails.</p>}
                </div>
              )}
            </div>
          )}
          </>)}
        </div>

        {showEmail && hasDocs && (
          <div className="mt-4 p-4 bg-[#0C0A09] border border-white/10 rounded-2xl" data-testid="email-panel">
            <div className="flex items-center gap-2 mb-3 text-sm text-zinc-300">
              <input type="checkbox" checked={toSelf} onChange={(e) => setToSelf(e.target.checked)} data-testid="email-to-self" className="accent-amber-500" />
              <span>Send to my own inbox (ready to forward)</span>
            </div>
            {!toSelf && (
              <Input placeholder="Recruiter / recipient email" value={recipient} onChange={(e) => setRecipient(e.target.value)} data-testid="email-recipient" />
            )}
            <div className="flex items-center gap-2 mt-3 text-sm text-zinc-300">
              <input type="checkbox" checked={attachPdf} onChange={(e) => setAttachPdf(e.target.checked)} data-testid="email-attach-pdf" className="accent-amber-500" />
              <span>Attach cover letter (PDF)</span>
            </div>
            <div className="flex gap-2 mt-3">
              <Button onClick={doSend} disabled={sending} data-testid="email-send-btn">{sending ? <><Spinner /> Sending…</> : <><Send className="w-4 h-4" /> Send</>}</Button>
              <Button variant="outline" onClick={() => setShowEmail(false)}>Cancel</Button>
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 mt-6 pt-4 border-t border-white/10">
          {j.url && <a href={j.url} target="_blank" rel="noreferrer"><Button data-testid="apply-link"><ExternalLink className="w-4 h-4" /> Open job & apply</Button></a>}
          <Button variant="outline" onClick={() => download("pdf")} data-testid="export-pdf-btn"><FileDown className="w-4 h-4" /> PDF</Button>
          <Button variant="outline" onClick={() => download("docx")} data-testid="export-docx-btn"><FileDown className="w-4 h-4" /> DOCX</Button>
          {hasDocs && <Button variant="outline" onClick={() => setShowEmail(!showEmail)} data-testid="send-email-btn">{j.email_sent_to ? <Check className="w-4 h-4 text-emerald-400" /> : <Send className="w-4 h-4" />} {j.email_sent_to ? "Sent" : "Email"}</Button>}
          <Button variant="outline" onClick={regen} disabled={busy} data-testid="regenerate-btn">{busy ? <Spinner /> : <RefreshCw className="w-4 h-4" />} Regenerate</Button>
          <Button variant="danger" onClick={remove} className="ml-auto" data-testid="delete-job-btn"><Trash2 className="w-4 h-4" /> Remove</Button>
        </div>
      </div>
    </Modal>
  );
}
