import React, { useEffect, useState } from "react";
import { ShieldCheck, Search, RefreshCw, Building2 } from "lucide-react";
import { toast } from "sonner";
import { Card, Button, Input, Spinner } from "./ui";
import { searchSponsor, sponsorsStatus, refreshSponsors } from "../api";

export default function SponsorCheck() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState({ count: 0 });
  const [refreshing, setRefreshing] = useState(false);

  const loadStatus = () => sponsorsStatus().then(setStatus).catch(() => {});
  useEffect(() => { loadStatus(); }, []);

  const search = async () => {
    if (!q.trim()) return;
    setBusy(true);
    try { setRes(await searchSponsor(q)); } catch { toast.error("Search failed"); }
    finally { setBusy(false); }
  };

  const refresh = async () => {
    setRefreshing(true);
    try { const r = await refreshSponsors(); if (r.ok) { toast.success(`Loaded ${r.count.toLocaleString()} sponsors`); loadStatus(); } else toast.error(r.error); }
    catch { toast.error("Refresh failed"); }
    finally { setRefreshing(false); }
  };

  return (
    <div className="max-w-2xl">
      <h2 className="font-display text-4xl font-normal text-white mb-1">Sponsor Licence Check</h2>
      <p className="text-zinc-500 text-sm mb-6 font-mono">Verify against the official GOV.UK Register of Licensed Sponsors.</p>

      <Card className="p-5 mb-5 flex items-center justify-between gap-4" data-testid="sponsor-status">
        <div className="text-sm">
          <div className="flex items-center gap-2 font-medium text-zinc-100"><ShieldCheck className="w-4 h-4 text-emerald-400" /> <span className="font-mono">{status.count ? status.count.toLocaleString() : 0}</span> licensed sponsors loaded</div>
          <div className="text-zinc-500 text-xs mt-1">{status.loaded_at ? `Updated ${new Date(status.loaded_at).toLocaleDateString()}` : "Not loaded yet — click sync"}</div>
        </div>
        <Button variant="outline" onClick={refresh} disabled={refreshing} data-testid="sync-sponsors-btn">{refreshing ? <Spinner /> : <RefreshCw className="w-4 h-4" />} Sync register</Button>
      </Card>

      <div className="flex gap-2 mb-5">
        <Input placeholder="Enter a company name…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} data-testid="sponsor-search-input" />
        <Button onClick={search} disabled={busy} data-testid="sponsor-search-btn">{busy ? <Spinner /> : <Search className="w-4 h-4" />} Check</Button>
      </div>

      {res && (
        <Card className="p-6" data-testid="sponsor-result">
          {res.is_licensed_sponsor ? (
            <div>
              <div className="inline-flex items-center gap-2 bg-emerald-500/10 text-emerald-300 border border-emerald-500/25 glow-emerald rounded-full px-3 py-1 text-sm font-mono">
                <ShieldCheck className="w-4 h-4" /> Licensed to sponsor
              </div>
              <p className="mt-4 font-display text-2xl text-white">{res.match.name}</p>
              <p className="text-sm text-zinc-400 font-mono mt-1">{res.match.rating} · {res.match.route} · {res.match.city}</p>
            </div>
          ) : (
            <div>
              <p className="text-zinc-200 font-medium">No exact match on the register for "{res.query}".</p>
              {res.suggestions?.length > 0 && (
                <div className="mt-4">
                  <p className="text-xs uppercase tracking-wider text-zinc-500 mb-2">Similar sponsors</p>
                  <div className="space-y-2">
                    {res.suggestions.map((s, i) => (
                      <div key={i} className="flex items-center gap-2 text-sm text-zinc-400"><Building2 className="w-4 h-4 text-zinc-600" />{s.name} <span className="text-zinc-600">· {s.city}</span></div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
