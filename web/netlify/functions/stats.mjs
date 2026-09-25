// Panel privado: requiere la clave NOVIARK_ADMIN_KEY (variable de entorno de Netlify, nunca en el código)
import {getStore} from "@netlify/blobs";

export default async (req) => {
  const KEY = Netlify.env.get("NOVIARK_ADMIN_KEY");
  const given = req.headers.get("x-admin-key") || "";
  if (!KEY || given.length !== KEY.length || given !== KEY) {
    await new Promise(r => setTimeout(r, 600));
    return Response.json({error: KEY ? "clave incorrecta" : "Falta configurar NOVIARK_ADMIN_KEY en Netlify"}, {status: 401});
  }
  const store = getStore({name: "noviq-stats", consistency: "strong"});
  const totals = (await store.get("totals", {type: "json"})) || {};
  const {blobs} = await store.list({prefix: "day/"});
  const keys = blobs.map(b => b.key).sort().slice(-90);
  const days = await Promise.all(keys.map(async k => ({day: k.slice(4), ...((await store.get(k, {type: "json"})) || {})})));
  let github = null;
  const repo = Netlify.env.get("NOVIARK_REPO");
  if (repo) {
    try {
      const r = await fetch(`https://api.github.com/repos/${repo}/releases?per_page=100`, {headers: {"user-agent": "noviq-stats"}});
      if (r.ok) {
        const rels = await r.json();
        github = {total: 0, releases: rels.map(rel => {
          const assets = (rel.assets || []).map(a => ({name: a.name, downloads: a.download_count}));
          const n = assets.reduce((s, a) => s + a.downloads, 0); github.total += n;
          return {tag: rel.tag_name, date: rel.published_at, downloads: n, assets};
        })};
      }
    } catch (e) {}
  }
  return Response.json({totals, days, github}, {headers: {"cache-control": "no-store"}});
};

export const config = {path: "/api/stats"};
