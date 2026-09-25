// Contador de visitas y descargas de noviq (sin cookies ni datos personales: solo totales por día, sistema, país e idioma)
import {getStore} from "@netlify/blobs";
import {bump, inc} from "../lib/bump.mjs";

const EVENTS = new Set(["visit", "download", "lead"]);
const clean = (s, n = 24) => String(s || "").toLowerCase().replace(/[^a-z0-9._-]/g, "").slice(0, n);

export default async (req, context) => {
  const store = getStore({name: "noviq-stats", consistency: "strong"});
  if (req.method === "GET") {
    const tot = (await store.get("totals", {type: "json"})) || {};
    return Response.json({downloads: tot.download || 0}, {headers: {"cache-control": "public, max-age=300"}});
  }
  if (req.method !== "POST") return new Response(null, {status: 405});
  const ua = req.headers.get("user-agent") || "";
  if (/bot|crawl|spider|slurp|preview|headless|lighthouse|pingdom|uptime/i.test(ua)) return new Response(null, {status: 204});
  let b = {};
  try { b = JSON.parse((await req.text()) || "{}"); } catch (e) { return new Response(null, {status: 400}); }
  if (!EVENTS.has(b.t)) return new Response(null, {status: 400});
  const ev = b.t, os = clean(b.os, 8) || "other", lang = b.lang === "en" ? "en" : "es";
  const country = clean(context.geo?.country?.code || "xx", 2).toUpperCase() || "XX";
  const asset = clean(b.asset), ref = clean(b.ref, 60), day = new Date().toISOString().slice(0, 10);
  await Promise.all([
    bump(store, "totals", d => {
      inc(d, ev);
      d[ev + "_os"] = d[ev + "_os"] || {}; inc(d[ev + "_os"], os);
      if (ev === "visit") {
        d.country = d.country || {}; inc(d.country, country);
        d.lang = d.lang || {}; inc(d.lang, lang);
        if (ref && !ref.includes("netlify.app")) { d.ref = d.ref || {}; inc(d.ref, ref); }
      }
      if (asset) { d[ev + "_asset"] = d[ev + "_asset"] || {}; inc(d[ev + "_asset"], asset); }
      d.updated = Date.now();
    }),
    bump(store, "day/" + day, d => { inc(d, ev); }),
  ]);
  return new Response(null, {status: 204});
};

export const config = {path: "/api/track"};
