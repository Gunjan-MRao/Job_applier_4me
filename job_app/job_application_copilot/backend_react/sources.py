"""
Multi-source job aggregator for the React backend.
Copied from Job_app_Emergent/backend/sources.py — no changes.
"""
import os
from urllib.parse import quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = (8, 25)


def _job(title, company, location, url, description="", salary="", source="", remote=False, track="uk_sponsored"):
    def _s(v, default=""):
        if v is None:
            return default
        try:
            import math
            if isinstance(v, float) and math.isnan(v):
                return default
        except Exception:
            pass
        return str(v)
    return {"title": _s(title, "Role"), "company": _s(company, "Unknown"),
            "location": _s(location, "Remote" if remote else "United Kingdom"),
            "url": _s(url), "description": _s(description), "salary": _s(salary),
            "source": _s(source), "remote": remote, "track": track}


def adzuna(query, location):
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        return []
    r = requests.get("https://api.adzuna.com/v1/api/jobs/gb/search/1", params={
        "app_id": app_id, "app_key": app_key, "results_per_page": 30,
        "what": query, "where": location, "content-type": "application/json"}, timeout=TIMEOUT)
    out = []
    for it in r.json().get("results", []):
        out.append(_job(it.get("title"), (it.get("company") or {}).get("display_name"),
                        (it.get("location") or {}).get("display_name"), it.get("redirect_url"),
                        it.get("description"), it.get("salary_min"), "adzuna"))
    return out


def reed(query, location):
    key = os.environ.get("REED_API_KEY")
    if not key:
        return []
    r = requests.get("https://www.reed.co.uk/api/1.0/search",
                     params={"keywords": query, "locationName": location, "resultsToTake": 50},
                     auth=(key, ""), timeout=TIMEOUT)
    out = []
    for it in r.json().get("results", []):
        out.append(_job(it.get("jobTitle"), it.get("employerName"), it.get("locationName"),
                        it.get("jobUrl"), it.get("jobDescription"), it.get("minimumSalary"), "reed"))
    return out


def _scrape(name, url, card_sels, title_sels, base, limit=40):
    out = []
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    if r.status_code != 200:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    cards = []
    for s in card_sels:
        cards = soup.select(s)
        if cards:
            break
    seen = set()
    for card in cards:
        el = None
        for s in title_sels:
            el = card.select_one(s)
            if el:
                break
        if not el:
            continue
        title = el.get_text(" ", strip=True)
        href = el.get("href", "")
        if not title or not href:
            continue
        u = href if href.startswith("http") else f"{base}{href}"
        if u in seen:
            continue
        seen.add(u)
        out.append(_job(title, "Unknown", "United Kingdom", u,
                        card.get_text(" ", strip=True)[:400], "", name))
        if len(out) >= limit:
            break
    return out


def nhs(query, location):
    q = quote_plus(query)
    return _scrape("nhs", f"https://www.jobs.nhs.uk/candidate/search/results?keyword={q}&language=en",
                   ["li.nhsuk-list-panel", "li.search-result", ".nhsuk-card"],
                   ["a.nhsuk-link", "h2 a", "a"], "https://www.jobs.nhs.uk")


def civilservice(query, location):
    q = quote_plus(query)
    return _scrape("civilservice",
                   f"https://www.civilservicejobs.service.gov.uk/csr/index.cgi?SID=&keyword={q}",
                   ["li.search-results-job-box", "div.vac_display_panel", "li"],
                   ["a.search-results-job-box-title", "h3 a", "a"],
                   "https://www.civilservicejobs.service.gov.uk")


def findajob(query, location):
    q = quote_plus(query)
    return _scrape("findajob", f"https://findajob.dwp.gov.uk/search?q={q}",
                   ["div.search-result", "li.search-result"], ["h3 a", "h2 a"],
                   "https://findajob.dwp.gov.uk")


def jobspy_uk(query, location):
    try:
        from jobspy import scrape_jobs
        df = scrape_jobs(site_name=["linkedin", "indeed", "glassdoor"], search_term=query,
                         location=location or "United Kingdom", results_wanted=20,
                         country_indeed="UK", linkedin_fetch_description=False, hours_old=720)
        out = []
        for _, row in df.iterrows():
            desc = row.get("description")
            out.append(_job(row.get("title"), row.get("company"), row.get("location"),
                            row.get("job_url"), desc if isinstance(desc, str) else "",
                            row.get("min_amount"), f"{row.get('site','scrape')}"))
        return out
    except Exception:
        return []


def remotive(query, location):
    r = requests.get("https://remotive.com/api/remote-jobs", params={"search": query, "limit": 30}, timeout=TIMEOUT)
    out = []
    for it in r.json().get("jobs", []):
        out.append(_job(it.get("title"), it.get("company_name"),
                        it.get("candidate_required_location") or "Remote", it.get("url"),
                        it.get("description", "")[:600], it.get("salary"), "remotive",
                        remote=True, track="remote_intl"))
    return out


def remoteok(query, location):
    r = requests.get("https://remoteok.com/api", headers=UA, timeout=TIMEOUT)
    data = r.json()
    out = []
    ql = (query or "").lower()
    for it in data:
        if not isinstance(it, dict) or not it.get("position"):
            continue
        text = f"{it.get('position','')} {' '.join(it.get('tags',[]))}".lower()
        if ql and not any(w in text for w in ql.split()):
            continue
        out.append(_job(it.get("position"), it.get("company"), it.get("location") or "Remote",
                        it.get("url"), (it.get("description") or "")[:600], "", "remoteok",
                        remote=True, track="remote_intl"))
        if len(out) >= 25:
            break
    return out


ADZUNA_COUNTRY = {
    "united kingdom": "gb", "uk": "gb", "britain": "gb",
    "united states": "us", "usa": "us", "us": "us", "america": "us",
    "canada": "ca", "germany": "de", "australia": "au", "singapore": "sg",
    "netherlands": "nl", "holland": "nl", "france": "fr", "spain": "es",
    "italy": "it", "india": "in", "new zealand": "nz", "poland": "pl",
    "brazil": "br", "south africa": "za", "austria": "at", "belgium": "be",
    "switzerland": "ch", "mexico": "mx",
}


def adzuna_country(query, country_name):
    code = ADZUNA_COUNTRY.get((country_name or "").lower().strip())
    if not code:
        return False, []
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        return True, []
    try:
        r = requests.get(f"https://api.adzuna.com/v1/api/jobs/{code}/search/1", params={
            "app_id": app_id, "app_key": app_key, "results_per_page": 30,
            "what": query, "content-type": "application/json"}, timeout=TIMEOUT)
        out = []
        for it in r.json().get("results", []):
            j = _job(it.get("title"), (it.get("company") or {}).get("display_name"),
                     (it.get("location") or {}).get("display_name") or country_name,
                     it.get("redirect_url"), it.get("description"), it.get("salary_min"),
                     f"adzuna-{code}", remote=False, track="remote_intl")
            out.append(j)
        return True, out
    except Exception:
        return True, []


UK_SOURCES = [adzuna, reed, nhs, civilservice, findajob, jobspy_uk]
REMOTE_SOURCES = [remotive, remoteok]


def gather(query, location):
    jobs, breakdown = [], {}
    fns = [(f, "uk_sponsored") for f in UK_SOURCES] + [(f, "remote_intl") for f in REMOTE_SOURCES]
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(f, query, location): f.__name__ for f, _ in fns}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                res = fut.result()
                breakdown[name] = len(res)
                jobs.extend(res)
            except Exception as e:
                breakdown[name] = f"error: {str(e)[:60]}"
    return jobs, breakdown
