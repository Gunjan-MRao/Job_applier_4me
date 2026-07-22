import axios from "axios";

// REACT_APP_BACKEND_URL is set in frontend/.env -> http://127.0.0.1:8001
const BASE = process.env.REACT_APP_BACKEND_URL || "http://127.0.0.1:8001";
export const api = axios.create({ baseURL: `${BASE}/api` });

export const getConfig            = ()         => api.get("/config").then(r => r.data);
export const getProfile           = ()         => api.get("/profile").then(r => r.data);
export const saveProfile          = (p)        => api.post("/profile", p).then(r => r.data);
export const parseCV              = (file)     => {
  const fd = new FormData();
  fd.append("file", file);
  return api.post("/profile/parse-cv", fd, { headers: { "Content-Type": "multipart/form-data" } }).then(r => r.data);
};
export const sponsorsStatus       = ()         => api.get("/sponsors/status").then(r => r.data);
export const refreshSponsors      = ()         => api.post("/sponsors/refresh").then(r => r.data);
export const searchSponsor        = (q)        => api.get("/sponsors/search", { params: { q } }).then(r => r.data);
export const listJobs             = (status)   => api.get("/jobs", { params: status ? { status } : {} }).then(r => r.data);
export const jobStats             = ()         => api.get("/jobs/stats").then(r => r.data);
export const addJob               = (j)        => api.post("/jobs", j).then(r => r.data);
export const updateJob            = (id, status) => api.patch(`/jobs/${id}`, { status }).then(r => r.data);
export const regenerate           = (id)       => api.post(`/jobs/${id}/regenerate`).then(r => r.data);
export const deleteJob            = (id)       => api.delete(`/jobs/${id}`).then(r => r.data);
export const discover             = (body)     => api.post("/jobs/discover", body).then(r => r.data);
export const generateAll          = ()         => api.post("/jobs/generate-all").then(r => r.data);
export const sponsorshipCountries = (refresh)  => api.get("/sponsorship-countries", { params: refresh ? { refresh: true } : {} }).then(r => r.data);
export const discoverCountry      = (country)  => api.post("/jobs/discover-country", { country }).then(r => r.data);
export const sendEmail            = (id, payload) => api.post(`/jobs/${id}/send-email`, payload).then(r => r.data);
export const recruiterEmail       = (id)       => api.get(`/jobs/${id}/recruiter-email`).then(r => r.data);
