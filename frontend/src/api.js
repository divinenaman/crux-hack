import { fileUrl } from "./lib/fileUrl";

export { fileUrl };

const J = (r) => {
  if (!r.ok) throw new Error(r.statusText || "request failed");
  return r.json();
};
const post = (url, body) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }).then(J);
const get = (url) => fetch(url).then(J);

export const api = {
  health: () => get("/api/health"),
  brands: () => get("/api/brands"),
  createBrand: (id, name) => post("/api/brands", { id, name }),
  brand: (bid) => get(`/api/brands/${bid}`),
  ingest: (bid, root) => post(`/api/brands/${bid}/ingest`, { root }),
  tree: (bid) => get(`/api/brands/${bid}/tree`),
  assets: (bid, params = {}) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== "" && v != null) q.set(k, v);
    });
    return get(`/api/brands/${bid}/assets?${q}`);
  },
  rules: (bid) => get(`/api/brands/${bid}/rules`),
  jobs: (bid) => get(`/api/brands/${bid}/jobs`),
  createJob: (bid, use_case, ratio, variants, folder) =>
    post(`/api/brands/${bid}/jobs`, { use_case, ratio, variants, folder }),
  job: (bid, jid) => get(`/api/brands/${bid}/jobs/${jid}`),
  manifest: (bid, jid, draft = "generated") => get(`/api/brands/${bid}/jobs/${jid}/manifest?draft=${encodeURIComponent(draft)}`),
  createEdit: (bid, jid, parent, instruction) => post(`/api/brands/${bid}/jobs/${jid}/edits`, { parent, instruction }),
  edit: (bid, jid, eid) => get(`/api/brands/${bid}/jobs/${jid}/edits/${eid}`),
  refUrl: (bid, assetId) => `/api/brands/${bid}/refs/${assetId}`,
  fileUrl,
};
