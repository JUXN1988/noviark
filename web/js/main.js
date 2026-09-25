(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const CFG = window.NOVIQ || {}, EN = window.NOVIQ_EN || {}, ESX = window.NOVIQ_ES_EXTRA || {};
  const repoOk = CFG.repo && !/OWNER/.test(CFG.repo);
  const store = {get(k){try{return localStorage.getItem(k)}catch(e){return null}}, set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
  const sget = k => {try{return sessionStorage.getItem(k)}catch(e){return null}}, sset = (k,v) => {try{sessionStorage.setItem(k,v)}catch(e){}};

  /* ---------- idioma ---------- */
  const ES = {}; $$("[data-i]").forEach(el => { ES[el.dataset.i] = el.innerHTML; });
  ES._title = document.title; ES._desc = ($('meta[name="description"]') || {}).content || "";
  let lang = store.get("noviq_web_lang") || ((navigator.language || "es").toLowerCase().startsWith("es") ? "es" : "en");
  const t = k => (lang === "en" ? EN[k] : (ES[k] ?? ESX[k])) ?? ESX[k] ?? k;
  function applyLang() {
    document.documentElement.lang = lang;
    $$("[data-i]").forEach(el => { const v = lang === "en" ? EN[el.dataset.i] : ES[el.dataset.i]; if (v != null) el.innerHTML = v; });
    document.title = t("_title"); const md = $('meta[name="description"]'); if (md) md.content = t("_desc");
    $("#langBtn").textContent = lang === "en" ? "ES" : "EN";
    $$("img[data-src-es]").forEach(im => {
      const L = lang === "en" ? "En" : "Es", ss = im.dataset["srcset" + L];
      if (ss) im.srcset = ss;
      im.src = im.dataset["src" + L];
    });
    const on = $(".shots .tabs .on"); if (on) setShot(on.dataset.shot);
    setHeroOS(); roi(); showCounts();
  }
  $("#langBtn").addEventListener("click", () => { lang = lang === "en" ? "es" : "en"; store.set("noviq_web_lang", lang); applyLang(); });

  /* ---------- descargas ---------- */
  const ua = navigator.userAgent, plat = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
  const mobile = /Android|iPhone|iPad|iPod/i.test(ua) || (/Mac/i.test(plat) && navigator.maxTouchPoints > 1);
  const OS = mobile ? "" : /Win/i.test(plat + ua) ? "win" : /Mac/i.test(plat + ua) ? "mac" : /Linux|X11|Ubuntu/i.test(plat + ua) ? "linux" : "";
  const OSNAME = {win: "Windows", mac: "macOS", linux: "Linux"};
  let macIntel = false;  // Mac con procesador Intel → instalador x86_64
  function detectMacArch() {
    if (OS !== "mac") return Promise.resolve();
    const uad = navigator.userAgentData;
    if (uad && uad.getHighEntropyValues) return uad.getHighEntropyValues(["architecture"]).then(v => { macIntel = v.architecture === "x86"; }).catch(() => {});
    try {  // Safari/Firefox: la GPU delata el procesador (Apple M* o Intel)
      const gl = document.createElement("canvas").getContext("webgl"), ext = gl && gl.getExtension("WEBGL_debug_renderer_info");
      const r = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "";
      macIntel = /Intel|AMD|Radeon/i.test(r) && !/Apple/i.test(r);
    } catch (e) {}
    return Promise.resolve();
  }
  const assetUrl = a => repoOk ? `https://github.com/${CFG.repo}/releases/latest/download/${a}` : "#descargar";
  $$("[data-asset]").forEach(a => { a.href = assetUrl(a.dataset.asset); if (repoOk) a.setAttribute("rel", "noopener"); });
  const gh = repoOk ? `https://github.com/${CFG.repo}` : "#";
  ["#ghLink2", "#ghLink3"].forEach(s => { const e = $(s); if (e) e.href = gh; });
  const lic = $("#licLink"); if (lic) lic.href = repoOk ? gh + "/blob/main/LICENSE.md" : "#planes";
  if (OS) { const c = $(`.dl[data-os="${OS}"]`); if (c) c.classList.add("me"); }
  function setHeroOS() {
    const b = $("#heroDl"), tx = $("#heroDlTxt"); if (!b || !tx || !OS) return;
    const main = OS === "mac" && macIntel ? $('.dl[data-os="mac"] [data-asset$="x86_64.dmg"]') : $(`.dl[data-os="${OS}"] .btn[data-asset]`);
    tx.textContent = `${t("_dl_for")} ${OSNAME[OS]}`;
    if (main && repoOk) { b.href = main.href; b.dataset.track = main.dataset.track; }
  }
  function track(ev, extra) {
    const body = JSON.stringify(Object.assign({t: ev, lang, os: OS || "other", ref: document.referrer ? new URL(document.referrer).hostname : ""}, extra || {}));
    try { if (navigator.sendBeacon && navigator.sendBeacon("/api/track", new Blob([body], {type: "application/json"}))) return; } catch (e) {}
    fetch("/api/track", {method: "POST", body, headers: {"Content-Type": "application/json"}, keepalive: true}).catch(() => {});
  }
  document.addEventListener("click", e => {
    const a = e.target.closest("[data-track]");
    if (a && a.getAttribute("href") && a.getAttribute("href") !== "#descargar") track("download", {asset: a.dataset.track});
    const c = e.target.closest("[data-contact]");
    if (c) { const s = $("#fInteres"); if (s) s.value = c.dataset.contact; }
  });
  if (!sget("noviq_v")) { sset("noviq_v", "1"); track("visit", {path: location.pathname}); }

  /* ---------- contadores (GitHub + web) ---------- */
  let gh_n = null, web_n = null, relTag = "";
  const fmt = n => new Intl.NumberFormat(lang === "en" ? "en-US" : "es-ES").format(n);
  function showCounts() {
    const n = Math.max(gh_n || 0, web_n || 0), few = n < (CFG.minShow || 50);
    ["#statDl", "#mDl"].forEach(s => {
      const e = $(s); if (!e) return;
      e.textContent = few ? "v" + (CFG.version || "4.2") : fmt(n);
      const lab = e.nextElementSibling; if (lab) lab.textContent = few ? t("_stable") : t(s === "#statDl" ? "n4" : "m_dl");
    });
    const r = $("#relInfo"); if (r && relTag) r.textContent = `${t("_dl_rel")} ${relTag}`;
  }
  async function loadCounts() {
    const cached = sget("noviq_counts");
    if (cached) { try { const c = JSON.parse(cached); if (Date.now() - c.t < 6e5) { gh_n = c.gh; web_n = c.web; relTag = c.tag; showCounts(); return; } } catch (e) {} }
    const jobs = [];
    if (repoOk) jobs.push(fetch(`https://api.github.com/repos/${CFG.repo}/releases?per_page=100`).then(r => r.ok ? r.json() : []).then(rs => {
      if (!Array.isArray(rs)) return; gh_n = 0; rs.forEach(rel => (rel.assets || []).forEach(a => { gh_n += a.download_count || 0; }));
      const latest = rs.find(r => !r.draft && !r.prerelease); if (latest) relTag = latest.tag_name;
    }).catch(() => {}));
    jobs.push(fetch("/api/track").then(r => r.ok ? r.json() : null).then(j => { if (j && typeof j.downloads === "number") web_n = j.downloads; }).catch(() => {}));
    await Promise.all(jobs);
    sset("noviq_counts", JSON.stringify({t: Date.now(), gh: gh_n, web: web_n, tag: relTag}));
    showCounts();
  }

  /* ---------- galería ---------- */
  function setShot(k) {
    const im = $("#shotImg"); if (!im) return;
    if (k === "work") { im.srcset = `/img/work_${lang}.webp?v=2 1440w, /img/work_${lang}@2x.webp?v=2 2880w`; im.width = 1440; im.height = 900; }
    else { im.removeAttribute("srcset"); im.width = 1440; im.height = 860; }
    im.src = `/img/${k}_${lang}.webp` + (k === "work" ? "?v=2" : "");
  }
  $$(".shots .tabs button").forEach(b => b.addEventListener("click", () => {
    $$(".shots .tabs button").forEach(x => x.classList.toggle("on", x === b)); setShot(b.dataset.shot);
  }));

  /* ---------- ROI ---------- */
  function roi() {
    const d = +$("#rDevs").value, h = +$("#rHours").value, c = +$("#rCost").value;
    $("#oDevs").textContent = fmt(d); $("#oHours").textContent = h; $("#oCost").textContent = "$" + c;
    const hrs = d * h * 46, val = hrs * c;
    $("#roiVal").textContent = new Intl.NumberFormat(lang === "en" ? "en-US" : "es-ES", {style: "currency", currency: "USD", maximumFractionDigits: 0}).format(val);
    $("#roiHrs").textContent = `${fmt(hrs)} ${t("_yr")}`;
  }
  ["#rDevs", "#rHours", "#rCost"].forEach(s => $(s).addEventListener("input", roi));

  /* ---------- formulario (Netlify Forms por AJAX) ---------- */
  const form = $("#contactForm");
  if (form) form.addEventListener("submit", async e => {
    e.preventDefault();
    const btn = form.querySelector("button[type=submit]"); btn.disabled = true;
    try {
      const r = await fetch("/", {method: "POST", headers: {"Content-Type": "application/x-www-form-urlencoded"}, body: new URLSearchParams(new FormData(form)).toString()});
      if (!r.ok) throw 0;
      track("lead", {asset: (form.interes || {}).value || ""});
      form.innerHTML = `<h3>✓</h3><p class="ok-msg">${t("_sent")}</p>`;
    } catch (err) { btn.disabled = false; alert(t("_err")); }
  });

  /* ---------- UI ---------- */
  $("#menuBtn").addEventListener("click", () => $(".nav").classList.toggle("open"));
  $$(".links a").forEach(a => a.addEventListener("click", () => $(".nav").classList.remove("open")));
  const yr = $("#yr"); if (yr) yr.textContent = new Date().getFullYear();
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(es => es.forEach(x => { if (x.isIntersecting) { x.target.classList.add("in"); io.unobserve(x.target); } }), {threshold: .12});
    $$(".card,.pillar,.plan,.dep,.dl,.tl,.roi,.nums,.inv-grid,.final-box").forEach(el => { el.classList.add("reveal"); io.observe(el); });
  }
  applyLang(); loadCounts(); detectMacArch().then(setHeroOS);
})();
