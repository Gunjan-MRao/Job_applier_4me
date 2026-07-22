import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Globe2, RefreshCw, Briefcase, Search } from "lucide-react";
import { toast } from "sonner";
import { Card, Button, Spinner } from "./ui";
import { sponsorshipCountries, discoverCountry } from "../api";

const demandColor = (d) => (d === "High" ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/25" : "bg-amber-500/10 text-amber-300 border-amber-500/25");
const diffColor = (d) => (d === "Easy" ? "text-emerald-400" : d === "Hard" ? "text-rose-400" : "text-amber-400");

export default function GlobalSponsors({ onJobsFound }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(null);

  const load = (refresh) => {
    setLoading(true);
    sponsorshipCountries(refresh)
      .then(setData)
      .catch(() => toast.error("Could not load recommendations"))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(false); }, []);

  const findJobs = async (country) => {
    setSearching(country);
    try {
      const r = await discoverCountry(country);
      if (r.unsupported) toast.info(r.message);
      else { toast.success(r.message); onJobsFound && onJobsFound(); }
    } catch { toast.error("Search failed"); }
    finally { setSearching(null); }
  };

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-2">
        <div>
          <h2 className="font-display text-4xl font-normal text-white flex items-center gap-3"><Globe2 className="w-8 h-8 text-amber-400" strokeWidth={1.25} /> Where in the world she can go</h2>
          <p className="text-zinc-500 text-sm mt-2 max-w-2xl">Countries most likely to sponsor an MSc Logistics &amp; Supply Chain Management graduate — ranked by opportunity.</p>
        </div>
        <Button variant="outline" onClick={() => load(true)} disabled={loading} data-testid="refresh-countries-btn">{loading ? <Spinner /> : <RefreshCw className="w-4 h-4" />} Refresh</Button>
      </div>

      {loading && !data ? (
        <div className="flex justify-center py-24"><Spinner className="text-amber-400 w-8 h-8" /></div>
      ) : (
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 mt-6">
          {(data?.countries || []).map((c, i) => (
            <motion.div key={i} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
              <Card className="p-6 h-full flex flex-col hover:border-amber-500/30 transition-colors" data-testid={`country-card-${i}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-3xl leading-none">{c.flag}</span>
                    <h3 className="font-display text-2xl font-normal text-white">{c.country}</h3>
                  </div>
                  <span className={`rounded-full border px-2.5 py-1 text-xs font-mono ${demandColor(c.demand)}`}>{c.demand} demand</span>
                </div>
                <div className="mt-4 text-sm">
                  <span className="text-xs uppercase tracking-wider text-zinc-500 font-mono">Visa route</span>
                  <p className="font-medium text-zinc-200 mt-0.5">{c.visa_route}</p>
                </div>
                <p className="text-sm text-zinc-400 mt-3 flex-1 leading-relaxed">{c.relevance}</p>
                {c.notes && <p className="text-sm text-zinc-500 mt-3 italic border-l-2 border-amber-500/40 pl-3">{c.notes}</p>}
                <div className="mt-4 pt-3 border-t border-white/5 flex items-center justify-between">
                  <span className={`text-xs font-mono ${diffColor(c.difficulty)}`}>Sponsorship: {c.difficulty}</span>
                  <span className="flex items-center gap-1 text-xs text-zinc-600"><Briefcase className="w-3.5 h-3.5" />{(c.job_boards || []).slice(0, 2).join(", ")}</span>
                </div>
                <Button variant="outline" className="mt-4 w-full justify-center" onClick={() => findJobs(c.country)} disabled={searching === c.country} data-testid={`find-jobs-${i}`}>
                  {searching === c.country ? <><Spinner /> Searching {c.country}…</> : <><Search className="w-4 h-4" /> Find live jobs</>}
                </Button>
              </Card>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
