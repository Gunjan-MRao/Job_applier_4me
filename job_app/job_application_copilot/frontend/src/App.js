import React, { useCallback, useEffect, useState } from "react";
import { Toaster } from "sonner";
import { Home, User, Briefcase, KanbanSquare, ShieldCheck, Globe2 } from "lucide-react";
import Dashboard from "./components/Dashboard";
import ProfileView from "./components/ProfileView";
import JobsView from "./components/JobsView";
import Tracker from "./components/Tracker";
import SponsorCheck from "./components/SponsorCheck";
import GlobalSponsors from "./components/GlobalSponsors";
import { getConfig, listJobs, jobStats } from "./api";

const NAV = [
  ["dashboard", "Dashboard",      Home],
  ["profile",   "Profile",        User],
  ["jobs",      "Opportunities",  Briefcase],
  ["global",    "Global Options", Globe2],
  ["tracker",   "Tracker",        KanbanSquare],
  ["sponsors",  "Sponsor Check",  ShieldCheck],
];

export default function App() {
  const [view,  setView]  = useState("dashboard");
  const [date,  setDate]  = useState("2027-01-06");
  const [jobs,  setJobs]  = useState([]);
  const [stats, setStats] = useState({});

  const reload = useCallback(() => {
    listJobs().then(setJobs).catch(() => {});
    jobStats().then(setStats).catch(() => {});
  }, []);

  useEffect(() => {
    getConfig().then(c => c.departure_date && setDate(c.departure_date)).catch(() => {});
    reload();
  }, [reload]);

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-[#0C0A09]">
      <Toaster position="top-center" theme="dark" richColors />

      {/* Sidebar */}
      <aside className="md:w-64 glass border-b md:border-b-0 md:border-r border-white/10 md:min-h-screen md:sticky md:top-0 z-20">
        <div className="p-6 flex items-center gap-3">
          <div className="w-10 h-10 rounded-2xl bg-amber-500 flex items-center justify-center shadow-[0_0_20px_rgba(245,158,11,0.35)]">
            {/* Plane icon inline */}
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none"
              stroke="#0C0A09" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17.8 19.2L16 11l3.5-3.5C21 6 21 4 19.5 2.5S18 1 16.5 2.5L13 6 4.8 4.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.3c.4-.3.6-.7.5-1.1z"/>
            </svg>
          </div>
          <div>
            <div className="font-display text-xl leading-none text-white">Round&nbsp;Trip</div>
            <div className="text-[10px] font-mono tracking-[0.25em] uppercase text-zinc-500 mt-1">Sponsor Copilot</div>
          </div>
        </div>
        <nav className="px-3 pb-4 flex md:flex-col gap-1 overflow-x-auto">
          {NAV.map(([key, label, Icon]) => (
            <button key={key} onClick={() => setView(key)} data-testid={`nav-${key}`}
              className={`flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm font-medium whitespace-nowrap
                transition-[background-color,color] duration-200
                ${ view === key
                  ? "bg-amber-500/15 text-amber-300 border border-amber-500/20"
                  : "text-zinc-400 hover:text-zinc-100 hover:bg-white/5 border border-transparent"
                }`}>
              <Icon className="w-4 h-4" strokeWidth={1.5} /> {label}
            </button>
          ))}
        </nav>
      </aside>

      {/* Main */}
      <main className="flex-1 p-5 sm:p-8 lg:p-10 max-w-6xl fadeup" key={view}>
        {view === "dashboard" && <Dashboard date={date} stats={stats} jobs={jobs} goto={setView} />}
        {view === "profile"   && <ProfileView onSaved={reload} />}
        {view === "jobs"      && <JobsView jobs={jobs} reload={reload} />}
        {view === "global"    && <GlobalSponsors onJobsFound={reload} />}
        {view === "tracker"   && <Tracker jobs={jobs} reload={reload} />}
        {view === "sponsors"  && <SponsorCheck />}
      </main>
    </div>
  );
}
