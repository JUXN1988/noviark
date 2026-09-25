/* Noviark i18n: español (idioma base) / English. Idioma automático según el sistema; se puede fijar en Ajustes.
   Traduce la interfaz en vivo (también lo que se crea después) sin tocar las respuestas de la IA ni el código. */
(function () {
  const KEY = "noviq_idioma";
  let pref = "auto";
  try { pref = localStorage.getItem(KEY) || "auto"; } catch (e) {}
  const sys = (navigator.language || "es").toLowerCase().startsWith("es") ? "es" : "en";
  const LANG = pref === "auto" ? sys : pref;
  window.NOVIQ_LANG = LANG;
  window.setNoviqLang = v => { try { localStorage.setItem(KEY, v); } catch (e) {} location.reload(); };
  window.getNoviqLangPref = () => pref;
  document.documentElement.lang = LANG;
  window.T = s => s;  // traducción explícita desde el código (para textos nuevos)
  if (LANG === "es") return;

  let DICT = {}, PATS = [], FRAGS = [];
  const SKIP = ".md, pre, code, textarea, .CodeMirror, [data-noi18n], .msg.user, #liveBody, .ptxt, .praz, .live, .fn, .pp, .n";
  const norm = s => s.replace(/\s+/g, " ").trim();
  const numRx = /\d+(?:[.,]\d+)?/g;

  function tr(text) {
    const k = norm(text);
    if (!k || !/[A-Za-zÁÉÍÓÚáéíóúñÑ]/.test(k)) return null;
    if (DICT[k] !== undefined) return DICT[k];
    const nums = k.match(numRx);
    if (nums) {
      const pk = k.replace(numRx, "{n}");
      if (DICT[pk] !== undefined) { let i = 0; return DICT[pk].replace(/\{n\}/g, () => nums[i++] ?? ""); }
    }
    for (const [rx, rep] of PATS) { if (rx.test(k)) return k.replace(rx, rep); }
    let out = k, hit = false;
    for (const [es, en] of FRAGS) { if (out.includes(es)) { out = out.split(es).join(en); hit = true; } }
    return hit ? out : null;
  }
  function doNode(n) {
    if (n.nodeType === 3) {
      const p = n.parentElement; if (!p || p.closest(SKIP)) return;
      const v = n.nodeValue; const t = tr(v);
      if (t !== null && t !== norm(v)) { const lead = v.match(/^\s*/)[0], trail = v.match(/\s*$/)[0]; n.nodeValue = lead + t + trail; }
    } else if (n.nodeType === 1) {
      if (n.closest && n.closest(SKIP) && !n.matches("textarea,input")) return;
      for (const a of ["placeholder", "title", "aria-label"]) {
        const v = n.getAttribute && n.getAttribute(a);
        if (v) { const t = tr(v); if (t !== null && t !== v) n.setAttribute(a, t); }
      }
      if (n.tagName === "OPTION" || n.tagName === "BUTTON" && !n.children.length) { /* texto propio: lo cubre el nodo de texto */ }
      for (const c of n.childNodes) doNode(c);
    }
  }
  let busy = false;
  const obs = new MutationObserver(ms => {
    if (busy) return; busy = true;
    try {
      for (const m of ms) {
        if (m.type === "characterData") doNode(m.target);
        else if (m.type === "attributes") doNode(m.target);
        else m.addedNodes.forEach(doNode);
      }
    } finally { busy = false; }
  });
  // alert/confirm/prompt también se traducen
  const wrap = f => (msg, ...rest) => f.call(window, msg == null ? msg : (tr(String(msg)) ?? String(msg)), ...rest);
  window.alert = wrap(window.alert); window.confirm = wrap(window.confirm); window.prompt = wrap(window.prompt);
  window.T = s => tr(s) ?? s;

  const start = () => {
    doNode(document.body);
    document.title = tr(document.title) || document.title;
    obs.observe(document.body, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["placeholder", "title", "aria-label"]});
  };
  fetch("/static/i18n_en.json").then(r => r.json()).then(j => {
    DICT = j.dict || {};
    PATS = (j.patterns || []).map(([a, b]) => [new RegExp(a), b]);
    FRAGS = Object.entries(j.fragments || {}).sort((a, b) => b[0].length - a[0].length);
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
  }).catch(() => {});
})();
