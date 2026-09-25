/* Noviark 4.0 — interfaz */
"use strict";
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => (s ?? "").toString().replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const TOKEN = window.TOKEN;
/* Ventana nativa (pywebview): los enlaces externos se abren en el navegador del sistema */
const NATIVA = () => !!(window.pywebview && window.pywebview.api && window.pywebview.api.abrir_externo);
const _winOpen = window.open.bind(window);
window.open = (u, t, f) => { if (NATIVA() && /^https?:/i.test(u || "") && !String(u).startsWith(location.origin)) { window.pywebview.api.abrir_externo(u); return null; } return _winOpen(u, t, f); };
document.addEventListener("click", e => { const a = e.target.closest && e.target.closest("a[href]"); if (!a || !NATIVA()) return;
  if (/^https?:/i.test(a.href) && !a.href.startsWith(location.origin)) { e.preventDefault(); window.pywebview.api.abrir_externo(a.href); } }, true);

/* ───────────── API ───────────── */
function api(url, opts = {}) {
  const h = {"X-Token": TOKEN, ...(opts.headers || {})};
  if (opts.body && !(opts.body instanceof FormData)) h["Content-Type"] = "application/json";
  return fetch(url, {...opts, headers: h});
}
const jget = u => api(u).then(r => r.json());
const jpost = (u, b) => api(u, {method: "POST", body: JSON.stringify(b || {})}).then(async r => {
  try { return await r.json(); } catch (e) { return {ok: false, error: r.status === 403 ? "Solo se puede modificar dentro de tus proyectos" : r.status + " " + r.statusText}; } });
const fileUrl = (p, dl) => `/f?p=${encodeURIComponent(p)}&t=${TOKEN}${dl ? "&d=1" : ""}`;
const rawUrl = p => `/raw/${TOKEN}/` + p.replace(/\\/g, "/").replace(/^\/+/, "").split("/").map(encodeURIComponent).join("/");
const openInFolder = p => jpost("/api/abrir", {ruta: p});

let CFG = {}, PROVIDERS = [], PROJECTS = [], TIPOS = [];
let convId = null, convProject = null, curProject = null, busy = false;
let attachments = [], attFiles = [];

/* ───────────── Markdown ───────────── */
function md(text) {
  if (!window.marked) return `<div style="white-space:pre-wrap">${esc(text)}</div>`;
  let h = marked.parse(text || "", {gfm: true, breaks: true});
  return window.DOMPurify ? DOMPurify.sanitize(h) : h;
}
const EXT = {python:"py",py:"py",javascript:"js",js:"js",jsx:"jsx",typescript:"ts",ts:"ts",tsx:"tsx",html:"html",css:"css",json:"json",
  powershell:"ps1",ps1:"ps1",pwsh:"ps1",bash:"sh",sh:"sh",shell:"sh",batch:"bat",bat:"bat",cmd:"bat",dos:"bat",java:"java",c:"c",cpp:"cpp","c++":"cpp",
  csharp:"cs",cs:"cs",go:"go",rust:"rs",php:"php",sql:"sql",yaml:"yml",yml:"yml",xml:"xml",markdown:"md",md:"md",kotlin:"kt",
  swift:"swift",ruby:"rb",arduino:"ino",ino:"ino",lua:"lua",r:"r",vb:"vb",dart:"dart",csv:"csv",text:"txt",txt:"txt",ini:"ini",toml:"toml"};
const LANG_OF = {py:"python",js:"javascript",jsx:"javascript",ts:"typescript",tsx:"typescript",html:"xml",htm:"xml",css:"css",json:"json",ps1:"powershell",
  sh:"bash",bat:"dos",cmd:"dos",java:"java",c:"c",h:"c",cpp:"cpp",cs:"csharp",go:"go",rs:"rust",php:"php",sql:"sql",yml:"yaml",yaml:"yaml",
  xml:"xml",md:"markdown",kt:"kotlin",swift:"swift",rb:"ruby",ino:"arduino",lua:"lua",dart:"dart",ini:"ini",toml:"ini",txt:"plaintext",csv:"plaintext"};
function enhance(el) {
  try { linkifyPaths(el); } catch (e) {}
  el.querySelectorAll("pre > code").forEach(code => {
    const pre = code.parentElement;
    if (pre.parentElement.classList.contains("codebox")) return;
    const lang = ((code.className.match(/language-([\w+#-]+)/) || [])[1] || "").toLowerCase();
    if (window.hljs) { try { hljs.highlightElement(code); } catch (e) {} }
    const box = document.createElement("div"); box.className = "codebox";
    const bar = document.createElement("div"); bar.className = "bar";
    bar.innerHTML = `<span>${esc(lang || "código")}</span><span><button data-a="copy">Copiar</button><button data-a="save">💾 Guardar</button></span>`;
    pre.replaceWith(box); box.append(bar, pre);
    bar.querySelector("[data-a=copy]").onclick = e => { navigator.clipboard.writeText(code.innerText); e.target.textContent = "¡Copiado!"; setTimeout(() => e.target.textContent = "Copiar", 1400); };
    bar.querySelector("[data-a=save]").onclick = async () => {
      const name = prompt("Nombre del archivo (se guarda en el proyecto actual):", "codigo." + (EXT[lang] || "txt"));
      if (!name) return;
      const r = await jpost("/api/guardar_codigo", {nombre: name, contenido: code.innerText, project: convProject});
      if (r.ok) box.after(fileCard({name: r.name, path: r.path, action: "guardado"}, false));
    };
  });
  el.querySelectorAll("img").forEach(img => img.onclick = () => lightbox(img.src));
}

/* ───────────── Elementos del chat ───────────── */
const thread = $("#thread"), msgsEl = $("#msgs");
function scrollEnd(force) { const near = msgsEl.scrollHeight - msgsEl.scrollTop - msgsEl.clientHeight < 200; if (force || near) msgsEl.scrollTop = msgsEl.scrollHeight; }
function userMsg(it) {
  const d = document.createElement("div"); d.className = "msg user";
  d.innerHTML = `<div class="av">${window.NOVIQ_LANG === "en" ? "You" : "Tú"}</div><div class="body"></div>`;
  const b = d.querySelector(".body");
  if (it.images?.length) { const u = document.createElement("div"); u.className = "uimgs"; it.images.forEach(src => { const i = new Image(); i.src = src; i.onclick = () => lightbox(src); u.append(i); }); b.append(u); }
  b.append(document.createTextNode(it.text || ""));
  if (it.files?.length) { const f = document.createElement("div"); f.className = "files"; f.textContent = "📎 " + it.files.map(x => x.split(/[\\/]/).pop()).join(", "); b.append(f); }
  thread.append(d); return d;
}
function aiMsg() {
  const d = document.createElement("div"); d.className = "msg ai";
  d.innerHTML = `<div class="av">N</div><div class="body"></div>`;
  thread.append(d); return d.querySelector(".body");
}
const ICONS = {py:"🐍",js:"📜",ts:"📜",html:"🌐",htm:"🌐",css:"🎨",ps1:"⚡",bat:"⚙",cmd:"⚙",xlsx:"📊",csv:"📊",docx:"📝",pdf:"📕",png:"🖼",jpg:"🖼",jpeg:"🖼",svg:"🖼",json:"🧾",md:"📝",zip:"🗜",java:"☕",cs:"#️⃣",ino:"🔌",txt:"📄"};
const extOf = n => (n.split(".").pop() || "").toLowerCase();
const fmtSize = b => b == null ? "" : b < 1024 ? b + " B" : b < 1048576 ? (b / 1024).toFixed(1) + " KB" : (b / 1048576).toFixed(1) + " MB";
function diffHtml(d) {
  return d.split("\n").map(l => `<span class="${l.startsWith("+") && !l.startsWith("+++") ? "d-add" : l.startsWith("-") && !l.startsWith("---") ? "d-del" : l.startsWith("@@") ? "d-hunk" : ""}">${esc(l)}</span>`).join("\n");
}
function fileCard(f, live) {
  const d = document.createElement("div"); d.className = "filecard";
  d.innerHTML = `<div class="ic">${ICONS[extOf(f.name)] || "📄"}</div><div style="min-width:0;flex:1"><div class="nm">${esc(f.name)} <span class="small">${esc(f.action || "")}</span></div>
    <div class="sz">${esc(f.path || "")}${f.size != null ? " · " + fmtSize(f.size) : ""}${f.lines ? " · " + f.lines + " líneas" : ""}</div></div>
    <div class="acts"><button data-a="pv">👁 Ver</button><button data-a="fo">📂</button><a href="${fileUrl(f.path, 1)}" title="Descargar">⬇</a></div>` +
    (f.diff ? `<details><summary class="small">Ver cambios</summary><pre>${diffHtml(f.diff)}</pre></details>` : "");
  d.querySelector("[data-a=pv]").onclick = () => openPreview(f.path);
  d.querySelector("[data-a=fo]").onclick = () => openInFolder(f.path);
  if (live) {
    if (PV.current === f.path) loadPreview(f.path);
    else if (["html", "htm", "svg"].includes(extOf(f.name)) && f.action !== "editado" && !Renderer.autoPreviewed) { Renderer.autoPreviewed = true; openPreview(f.path); }
  }
  return d;
}
function imageCard(f) {
  const d = document.createElement("div"); d.className = "genimg";
  const u = fileUrl(f.path);
  d.innerHTML = `<img src="${u}" alt=""><div class="cap">${esc(f.name)} · <a href="${fileUrl(f.path, 1)}">Descargar</a> · <a href="#" data-a="fo">Mostrar en carpeta</a></div>`;
  d.querySelector("img").onclick = () => lightbox(u);
  d.querySelector("img").onload = () => scrollEnd();
  d.querySelector("[data-a=fo]").onclick = e => { e.preventDefault(); openInFolder(f.path); };
  return d;
}
function argSummary(name, a) {
  if (!a) return "";
  if (a.ruta) return a.ruta;
  if (a.explicacion) return a.explicacion;
  if (a.texto_error) return a.texto_error.trim().split("\n").pop().slice(0, 140);
  if (a.instrucciones && !a.archivos) return a.instrucciones.split("\n")[0].slice(0, 140);
  if (a.tarea) return a.tarea.slice(0, 140);
  if (a.objetivo) return a.objetivo.slice(0, 140);
  if (a.ediciones) return a.ediciones.length + " ediciones";
  return a.nombre || a.prompt || a.consulta || a.url || a.patron || a.regex || a.ruta_o_url || a.accion || (a.origen ? a.origen + " → " + a.destino : "") ||
    (a.tareas ? a.tareas.length + " tareas" : "") || JSON.stringify(a).slice(0, 140);
}
function toolCard(p) {
  const d = document.createElement("details"); d.className = "tool";
  const a = p.args || {};
  const code = a.comando || a.codigo || "";
  let extra = "";
  if (code) extra = `<pre>${esc(code)}</pre>`;
  else if (p.name?.startsWith("mcp__")) extra = `<pre>${esc(JSON.stringify(a, null, 2))}</pre>`;
  d.innerHTML = `<summary>${esc(p.label)} <span class="arg">${esc(argSummary(p.name, a))}</span><span class="st"><span class="spin"></span></span></summary>${extra}<pre class="live" style="display:none"></pre><pre class="res" style="display:none"></pre>`;
  return d;
}
function finishTool(card, result) {
  if (!card) return;
  const st = card.querySelector(".st");
  const bad = /^(ERROR|El usuario RECHAZÓ|Cancelado)/.test(result) || /^Código de salida: [1-9]/.test(result) || /^TIEMPO AGOTADO/.test(result);
  st.innerHTML = bad ? "⚠ revisar" : "✔";
  st.style.color = bad ? "var(--warn)" : "var(--accent2)";
  const live = card.querySelector(".live"); if (live) live.style.display = "none";
  const r = card.querySelector(".res"); r.style.display = "block"; r.textContent = result;
  if (bad) card.open = false;
}
function confirmCard(p) {
  const d = document.createElement("div"); d.className = "confirm";
  const a = p.args || {};
  const body = a.comando || a.codigo || (a.contenido != null ? `${a.ruta}\n\n${a.contenido.slice(0, 3000)}` : JSON.stringify(a, null, 2));
  const rz = p.riesgo ? `<span class="badge ${p.riesgo === "alto" ? "r" : p.riesgo === "medio" ? "c" : "g"}" title="Evaluado por ${p.fuente_riesgo === "jev" ? "Jev (TypeSafe)" : "las reglas de seguridad de Noviark"}">riesgo ${esc(p.riesgo)}</span>` : "";
  if (p.riesgo === "alto") d.classList.add("alto");
  d.innerHTML = `<b>⚠ La IA quiere usar: ${esc(p.label)}</b> ${rz}${p.riesgo === "alto" ? `<div class="bad-t small">Esta acción puede borrar datos o cambiar el sistema: se pregunta siempre, aunque esté en modo automático.</div>` : ""}<div class="small" style="margin:4px 0">${esc(a.explicacion || argSummary(p.name, a))}</div><pre>${esc(body)}</pre>
    <div class="btns"><button class="btn ok" data-a="1">✔ Permitir</button>${p.riesgo === "alto" ? "" : `<button class="btn" data-a="2">✔ Permitir siempre en esta conversación</button>`}<button class="btn no" data-a="0">✖ Rechazar</button></div>`;
  d.querySelectorAll("[data-a]").forEach(b => b.onclick = () => {
    const v = b.dataset.a;
    jpost("/api/confirm", {id: p.id, approved: v !== "0", always: v === "2"});
    d.querySelector(".btns").innerHTML = v !== "0" ? `<span class="ok-t">Permitido ✔${v === "2" ? " (siempre)" : ""}</span>` : `<span class="bad-t">Rechazado ✖</span>`;
  });
  return d;
}
function askCard(p) {
  const d = document.createElement("div"); d.className = "confirm ask";
  let imgs = [];
  d.innerHTML = `<b>🙋 La IA necesita tu ayuda</b><div class="md" style="margin:6px 0">${md(p.instrucciones)}</div>
    <textarea rows="3" placeholder="Escribe tu respuesta (qué hiciste, qué viste, el dato que pide…). Pega capturas con Ctrl+V aquí."></textarea>
    <div class="uimgs"></div>
    <div class="btns"><button class="btn" data-a="img">📎 Adjuntar captura</button><button class="btn ok" data-a="send">Enviar respuesta</button><button class="btn no" data-a="no">No puedo hacerlo</button></div>
    <input type="file" accept="image/*" multiple hidden>`;
  const ta = d.querySelector("textarea"), box = d.querySelector(".uimgs"), fi = d.querySelector("input[type=file]");
  const addImg = file => { const rd = new FileReader(); rd.onload = () => { const im = new Image(); im.onload = () => {
      const k = Math.min(1, 1568 / Math.max(im.width, im.height)); const c = document.createElement("canvas");
      c.width = Math.round(im.width * k); c.height = Math.round(im.height * k); c.getContext("2d").drawImage(im, 0, 0, c.width, c.height);
      const u = c.toDataURL("image/jpeg", 0.88); imgs.push(u); const t = new Image(); t.src = u; box.append(t); }; im.src = rd.result; }; rd.readAsDataURL(file); };
  ta.addEventListener("paste", e => { [...(e.clipboardData?.items || [])].forEach(it => { if (it.kind === "file") { e.preventDefault(); e.stopPropagation(); addImg(it.getAsFile()); } }); });
  d.querySelector("[data-a=img]").onclick = () => fi.click();
  fi.onchange = () => [...fi.files].forEach(addImg);
  const answer = (texto, imagenes) => { jpost("/api/responder", {id: p.id, texto, imagenes});
    d.querySelector(".btns").innerHTML = `<span class="ok-t">Respuesta enviada ✔</span>`; ta.disabled = true; };
  d.querySelector("[data-a=send]").onclick = () => answer(ta.value || "Listo, ya lo hice.", imgs);
  d.querySelector("[data-a=no]").onclick = () => answer("No puedo hacerlo. " + ta.value, imgs);
  setTimeout(() => ta.focus(), 50);
  return d;
}
function lightbox(src) { const l = $("#lightbox"); l.querySelector("img").src = src; l.style.display = "flex"; }
$("#lightbox").onclick = () => $("#lightbox").style.display = "none";

/* ───────────── Renderizador de respuestas (en vivo e historial) ───────────── */
class Renderer {
  constructor(body, live) {
    this.body = body; this.live = live; this.tools = {}; this.pending = false;
    this.status = null;
    if (live) { this.status = document.createElement("div"); this.status.className = "small"; this.setStatus("Pensando…"); body.append(this.status); }
    this.seg();
  }
  seg() { this.mdEl = null; this.text = ""; this.thinkEl = null; this.thinkText = ""; }
  place(el) { this.status ? this.body.insertBefore(el, this.status) : this.body.append(el); }
  setStatus(t, spin = true) { if (this.status) this.status.innerHTML = (spin ? `<span class="spin"></span> ` : "") + esc(t); }
  reasoning(t) {
    if (!this.thinkEl) { this.thinkEl = document.createElement("details"); this.thinkEl.className = "think"; this.thinkEl.innerHTML = `<summary>💭 Razonando…</summary><div class="t"></div>`; this.place(this.thinkEl); }
    this.thinkText += t; this.thinkEl.querySelector(".t").textContent = this.thinkText; this.setStatus("Razonando…"); scrollEnd();
  }
  token(t) {
    if (this.thinkEl) this.thinkEl.querySelector("summary").textContent = "💭 Razonamiento";
    if (!this.mdEl) { this.mdEl = document.createElement("div"); this.mdEl.className = "md"; this.place(this.mdEl); }
    this.text += t; this.setStatus("Escribiendo…"); this.render();
  }
  render(now) {
    const go = () => { this.pending = false; if (this.mdEl) { this.mdEl.innerHTML = md(this.text); enhance(this.mdEl); } scrollEnd(); };
    if (now) return go();
    if (this.pending) return; this.pending = true; requestAnimationFrame(go);
  }
  assistant(it) { if (it.reasoning) { this.reasoning(it.reasoning); this.thinkEl.querySelector("summary").textContent = "💭 Razonamiento"; } if (it.text) { this.token(it.text); this.render(true); } this.seg(); }
  resetSeg() { if (this.mdEl) this.mdEl.remove(); if (this.thinkEl) this.thinkEl.remove(); this.seg(); }
  brk() { this.render(true); if (this.thinkEl) this.thinkEl.querySelector("summary").textContent = "💭 Razonamiento"; this.seg(); }
  toolStart(p) { const c = toolCard(p); this.tools[p.id] = c; this.place(c); this.setStatus(p.label + "…"); scrollEnd(); }
  toolOutput(p) { const c = this.tools[p.id]; if (!c) return; const l = c.querySelector(".live"); l.style.display = "block"; l.textContent += p.text; l.scrollTop = l.scrollHeight; c.open = true; scrollEnd(); }
  toolResult(p) { finishTool(this.tools[p.id] || [...Object.values(this.tools)].pop(), p.result); this.setStatus("Pensando…"); }
  confirm(p) { this.place(confirmCard(p)); this.setStatus("Esperando tu permiso…", false); scrollEnd(true); }
  ask(p) { this.place(askCard(p)); this.setStatus("Esperando tu respuesta…", false); scrollEnd(true); }
  file(p) { this.place(fileCard(p, this.live)); scrollEnd(); if (this.live && $("#preview").classList.contains("show") && $("#pvFiles").style.display !== "none") { clearTimeout(Renderer._ft); Renderer._ft = setTimeout(loadTree, 600); } }
  image(p) { this.place(imageCard(p)); scrollEnd(); }
  notice(p) { const n = document.createElement("div"); n.className = "notice"; n.textContent = "ℹ " + p.text; this.place(n); }
  project(p) { const n = document.createElement("div"); n.className = "projnote"; n.innerHTML = `🗂 Proyecto activo: <b>${esc(p.name)}</b> <span class="small">${esc(p.path || "")}</span>`; this.place(n); }
  error(p) { const e = document.createElement("div"); e.className = "err"; e.textContent = p.text; this.place(e); scrollEnd(true); }
  finish() {
    this.render(true);
    if (this.thinkEl) this.thinkEl.querySelector("summary").textContent = "💭 Razonamiento";
    if (this.status) this.status.remove(); this.status = null;
  }
}

function showContinue(show) {
  $$(".contbar").forEach(x => x.remove());
  if (!show) return;
  const d = document.createElement("div"); d.className = "contbar";
  d.innerHTML = `<span>💾 Este trabajo quedó a medias. Todo lo hecho está guardado.</span><button class="btn ok">▶ Continuar el trabajo</button>`;
  d.querySelector("button").onclick = () => send({continuar: true});
  thread.append(d); scrollEnd(true);
}
async function refreshContinue() {
  if (!convId) return showContinue(false);
  const c = await jget("/api/conversations/" + convId);
  showContinue(!!c.en_progreso && !c.running);
}
async function showEstado() {
  if (!convId) { alert("Abre o inicia una conversación primero."); return; }
  const r = await jget(`/api/conversations/${convId}/estado`);
  $("#preview").classList.add("show"); PV.current = null; renderTabs();
  $("#pvName").textContent = "📋 Estado del trabajo";
  $("#pvBody").innerHTML = `<div class="md">${md(r.text)}</div>`;
}
function addMsgActions(body) {
  $$(".msgacts").forEach(x => x.remove());
  const a = document.createElement("div"); a.className = "msgacts";
  a.innerHTML = `<button data-a="copy">Copiar</button><button data-a="regen">↻ Regenerar</button>`;
  a.querySelector("[data-a=copy]").onclick = () => navigator.clipboard.writeText([...body.querySelectorAll(".md")].map(x => x.innerText).join("\n\n"));
  a.querySelector("[data-a=regen]").onclick = () => send({regenerate: true});
  body.append(a);
}

/* ───────────── Pantalla inicial ───────────── */
function showEmpty() {
  thread.innerHTML = `<div id="empty"><img src="/static/noviq_icon.png" alt="Noviark" class="hero"><h1>¿Qué construimos hoy?</h1><div>NVIDIA, Gemini, OpenAI, Ollama, LM Studio… con herramientas reales en tu PC, equipo de agentes y respaldo automático.</div>
  <div class="sugs">
    <button class="sug">🐍 Crea un programa en Python con interfaz que organice mi carpeta de Descargas por tipo de archivo</button>
    <button class="sug">🌐 Crea una página web de portafolio moderna y ábrela en el navegador</button>
    <button class="sug">🎨 Dibuja un cajero automático futurista en una ciudad de noche</button>
    <button class="sug">⚡ Revisa mi PC: RAM, disco libre, procesador y los 5 procesos que más memoria usan</button>
    <button class="sug">🔎 Busca las noticias más recientes sobre NVIDIA y hazme un resumen</button>
    <button class="sug">📊 Crea un Excel con un presupuesto mensual con fórmulas y un gráfico</button>
  </div></div>`;
  thread.querySelectorAll(".sug").forEach(b => b.onclick = () => { $("#inp").value = b.textContent.replace(/^\S+\s/, ""); send(); });
  renderTasks([]);
}

/* ───────────── Proyectos y conversaciones ───────────── */
async function loadProjects() {
  const r = await jget("/api/projects");
  PROJECTS = r.projects; TIPOS = r.tipos; CFG.projects_root = r.root;
  const box = $("#projects"); box.innerHTML = "";
  const all = document.createElement("div"); all.className = "item" + (curProject === null ? " active" : "");
  all.innerHTML = `<span>💬</span><span class="t">Todas las conversaciones</span>`;
  all.onclick = () => { curProject = null; loadProjects(); loadConvs(); };
  box.append(all);
  const shown = PROJECTS.slice(0, 6);
  if (curProject && !shown.some(p => p.name === curProject)) { const cp = PROJECTS.find(p => p.name === curProject); if (cp) shown.push(cp); }
  shown.forEach(p => {
    const d = document.createElement("div"); d.className = "item" + (curProject === p.name ? " active" : "");
    d.innerHTML = `<span>${p.externo ? "📂" : TIPO_ICON[p.tipo] || "🗂"}</span><span class="t" title="${esc(p.descripcion || p.path)}">${esc(p.name)}</span>${p.trabajando ? `<span class="run" title="${p.trabajando} IA(s) trabajando aquí"></span>` : ""}<button class="del" title="Ajustes del proyecto">✎</button>`;
    d.onclick = () => showProjectHome(p.name);
    d.querySelector(".del").onclick = e => { e.stopPropagation(); editProject(p); };
    box.append(d);
  });
  if (PROJECTS.length > 6) { const more = document.createElement("div"); more.className = "item"; more.innerHTML = `<span>▦</span><span class="t">Ver todos los proyectos (${PROJECTS.length})</span>`; more.onclick = openProjects; box.append(more); }
  $("#np-tipo").innerHTML = TIPOS.map(t => `<option value="${t}">${t}</option>`).join("");
  if ($("#projsModal").classList.contains("show")) renderProjects();
}
const TIPO_ICON = {python: "🐍", web: "🌐", node: "🟩", java: "☕", csharp: "#️⃣", arduino: "🔌", android: "🤖", datos: "📊", documentos: "📝", flutter: "💙", php: "🐘", general: "🗂"};
let RUN_PREV = new Set(), LAST_CONVS = [];
async function loadConvs() {
  const list = await jget("/api/conversations"); LAST_CONVS = list;
  const now = new Set(list.filter(c => c.running).map(c => c.id));
  RUN_PREV.forEach(id => { if (!now.has(id) && id !== convId) { const c = list.find(x => x.id === id); toast(`✅ Terminó: «${(c && c.title) || "conversación"}»`, () => openConv(id)); } });
  RUN_PREV = now;
  if (HOME && !convId && HOME === curProject && $("#phome")) renderHomeConvs();
  const box = $("#convs"); box.innerHTML = "";
  $("#convHead").textContent = curProject ? "Chats de " + curProject : "Conversaciones";
  list.filter(c => curProject === null || c.project === curProject).forEach(c => {
    const d = document.createElement("div"); d.className = "item" + (c.id === convId ? " active" : "");
    d.innerHTML = `${c.running ? '<span class="run" title="Trabajando en segundo plano"></span>' : ""}<span class="t" title="${esc(c.title)}${c.model ? " · " + esc(c.model) : ""}">${esc(c.title || "Sin título")}</span>${c.project && curProject === null ? `<span class="small">${esc(c.project)}</span>` : ""}<button class="del" title="Borrar">🗑</button>`;
    d.onclick = () => openConv(c.id);
    d.querySelector(".del").onclick = async e => { e.stopPropagation(); if (!confirm("¿Borrar esta conversación?")) return;
      await api("/api/conversations/" + c.id, {method: "DELETE"}); if (c.id === convId) newChat(); loadConvs(); };
    box.append(d);
  });
}
function setProjectChip(name) {
  convProject = name || null;
  const chip = $("#projChip");
  chip.textContent = convProject ? "🗂 " + convProject : "🗂 Sin proyecto";
  updateHint();
}
function newChat() {
  detachView(); FT.custom = null; HOME = null;
  convId = null; setProjectChip(curProject); showEmpty(); loadConvs(); $("#inp").focus(); $("#side").classList.remove("open");
}
async function openConv(id) {
  detachView(); FT.custom = null; HOME = null;
  const c = await jget("/api/conversations/" + id);
  convId = id; $("#side").classList.remove("open");
  setProjectChip(c.project);
  if (c.model) selectModel(c.model);
  thread.innerHTML = "";
  let r = null, lastBody = null;
  for (const it of c.display) {
    if (it.type === "user") { userMsg(it); r = null; continue; }
    if (!r) { lastBody = aiMsg(); r = new Renderer(lastBody, false); }
    switch (it.type) {
      case "assistant": r.assistant(it); break;
      case "tool": r.toolStart(it); break;
      case "tool_result": r.toolResult(it); break;
      case "file": r.file(it); break;
      case "image": r.image(it); break;
      case "notice": r.notice(it); break;
      case "project": r.project(it); break;
      case "error": r.error(it); break;
    }
  }
  renderTasks(c.tasks || []);
  loadConvs(); scrollEnd(true);
  if (c.running) { attachStream(id); return; }
  if (lastBody) addMsgActions(lastBody);
  showContinue(!!c.en_progreso && !c.running);
}
/* ───────────── Escritura en vivo: lo que la IA va escribiendo en los archivos ───────────── */
const LIVE = {bufs: {}, names: {}, key: null, shown: false, t: 0};
function jsonStrField(buf, field) {  // extrae (aunque esté incompleto) el valor de un campo string de un JSON parcial
  const m = new RegExp('"' + field + '"\\s*:\\s*"').exec(buf); if (!m) return null;
  let i = m.index + m[0].length, out = "";
  while (i < buf.length) {
    const c = buf[i];
    if (c === '"') return {v: out, done: true};
    if (c === "\\") {
      const n = buf[i + 1]; if (n === undefined) break;
      if (n === "u") { const h = buf.substr(i + 2, 4); if (h.length < 4) break; out += String.fromCharCode(parseInt(h, 16)); i += 6; continue; }
      out += ({n: "\n", t: "\t", r: "", '"': '"', "\\": "\\", "/": "/", b: "", f: ""})[n] ?? n; i += 2; continue;
    }
    out += c; i++;
  }
  return {v: out, done: false};
}
function liveDelta(p) {
  const k = p.texto ? "t" : "c" + p.i;
  LIVE.bufs[k] = (LIVE.bufs[k] || "") + (p.chunk || ""); if (p.name) LIVE.names[k] = p.name;
  if (Date.now() - LIVE.t < 120) return;  // no redibujar en cada fragmento
  LIVE.t = Date.now();
  const buf = LIVE.bufs[k];
  const name = LIVE.names[k] || ((/"name"\s*:\s*"(\w+)"/.exec(buf) || [])[1]) || "";
  if (name && !["escribir_archivo", "editar_archivo", "ejecutar_python", "ejecutar_powershell", "ejecutar_linux", "contenedor"].includes(name)) return;
  const field = ["contenido", "texto_nuevo", "codigo", "comando"].find(f => buf.includes('"' + f + '"'));
  if (!field) return;
  const val = jsonStrField(buf, field); if (!val || val.v.length < 2) return;
  const ruta = (jsonStrField(buf, "ruta") || {}).v || "";
  if (LIVE.key !== k) { LIVE.key = k; if (!LIVE.shown || $("#preview").classList.contains("show")) { showPanel("live"); LIVE.shown = true; } }
  const verb = {escribir_archivo: "✍ Escribiendo", editar_archivo: "✏ Editando", ejecutar_python: "🐍 Preparando código", ejecutar_powershell: "⚡ Preparando comando"}[name] || "✍ Escribiendo";
  $("#liveHead").innerHTML = `${verb} <b>${esc(ruta || name)}</b> · ${val.v.split("\n").length} líneas ${val.done ? "✔" : '<span class="caret"></span>'}`;
  const body = $("#liveBody"); const atEnd = body.scrollTop + body.clientHeight >= body.scrollHeight - 30;
  body.textContent = val.v; if (atEnd) body.scrollTop = body.scrollHeight;
}
function liveReset() { LIVE.bufs = {}; LIVE.names = {}; LIVE.key = null; }

/* ───────────── Rutas y enlaces clicables (archivos y carpetas de tu PC) ───────────── */
const PATH_RX = /(?:[A-Za-z]:\\|\\\\)[^\s<>"'`|*?]+(?:\\[^\s<>"'`|*?]+)*/g;
function linkifyPaths(root) {
  root.querySelectorAll("code").forEach(c => {
    if (c.closest("pre") || c.closest("a")) return;
    const t = c.textContent.trim();
    if (/^(?:[A-Za-z]:[\\/]|\\\\|~[\\/]|\/(?:home|Users|mnt|tmp)\/)/.test(t)) { c.classList.add("plink"); c.dataset.path = t; c.title = "Abrir (Ctrl+clic: en el Explorador)"; }
  });
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {acceptNode: n => n.parentElement.closest("pre,code,a,.plink,textarea") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT});
  const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach(n => {
    const txt = n.nodeValue; PATH_RX.lastIndex = 0; if (!PATH_RX.test(txt)) return;
    const frag = document.createDocumentFragment(); let last = 0; PATH_RX.lastIndex = 0; let m;
    while ((m = PATH_RX.exec(txt))) {
      const pth = m[0].replace(/[.,;:)\]]+$/, "");
      frag.append(txt.slice(last, m.index)); const a = document.createElement("span"); a.className = "plink"; a.dataset.path = pth; a.textContent = pth; a.title = "Abrir (Ctrl+clic: en el Explorador)"; frag.append(a);
      last = m.index + pth.length;
    }
    frag.append(txt.slice(last)); n.replaceWith(frag);
  });
  root.querySelectorAll("a[href]").forEach(a => { const h = a.getAttribute("href"); if (/^file:/i.test(h)) { a.classList.add("plink"); a.dataset.path = h; } else if (/^https?:/i.test(h)) { a.target = "_blank"; a.rel = "noopener"; } });
}
async function openPathLink(path, external) {
  const r = await jget(`/api/ruta_info?p=${encodeURIComponent(path)}&proyecto=${encodeURIComponent(convProject || "")}`).catch(() => null);
  if (!r || !r.existe) { toast("No encontré: " + path); return; }
  if (external) { openInFolder(r.ruta); return; }
  if (r.dir) { FT.custom = r.ruta; FT.root = null; showPanel("files"); } else openPreview(r.ruta);
}
document.addEventListener("click", e => { const l = e.target.closest(".plink"); if (!l) return; e.preventDefault(); openPathLink(l.dataset.path, e.ctrlKey || e.metaKey); });
function renderTasks(tasks) {
  const t = $("#tasks");
  if (!tasks || !tasks.length) { t.classList.remove("show"); t.innerHTML = ""; return; }
  const done = tasks.filter(x => x.estado === "completada").length;
  const ic = {pendiente: "○", en_progreso: "◐", completada: "●"};
  t.innerHTML = `<div class="th"><span>✅ Tareas (${done}/${tasks.length})</span><span>${t.classList.contains("min") ? "▸" : "▾"}</span></div>` +
    tasks.map(x => `<div class="tk ${x.estado}"><span>${ic[x.estado] || "○"}</span><span>${esc(x.contenido)}</span></div>`).join("");
  t.classList.add("show");
  t.querySelector(".th").onclick = () => { t.classList.toggle("min"); renderTasks(tasks); };
}

/* ───────────── Enviar (cada conversación trabaja en paralelo) ───────────── */
let viewSeq = 0, viewCtrl = null;
function detachView() {  // deja de mostrar el chat actual SIN detener su trabajo (sigue en segundo plano)
  viewSeq++; if (viewCtrl) { try { viewCtrl.abort(); } catch (e) {} viewCtrl = null; }
  setBusy(false); clearFase();
}
async function send(opts = {}) {
  if (busy) { toast("⏳ La IA está trabajando en este chat. Para detenerla pulsa ■ Detener; para trabajar en paralelo abre otro chat o proyecto."); return; }
  const text = opts.continuar ? "" : $("#inp").value.trim();
  if (!opts.regenerate && !opts.continuar && !text && !attachments.length && !attFiles.length) return;
  showContinue(false);
  if (!hasAnyProvider()) { openSettings(); return; }
  const payload = {conversation_id: convId, model: $("#modelSel").value, project: convId ? undefined : curProject, idioma: window.NOVIQ_LANG || "es"};
  if (opts.regenerate) {
    payload.regenerate = true;
    const users = $$(".msg.user"); const last = users[users.length - 1];
    if (last) { while (last.nextSibling) last.nextSibling.remove(); }
  } else if (opts.continuar) {
    Object.assign(payload, {continuar: true, text: ""});
    userMsg({text: "▶ Continuar el trabajo"});
  } else {
    if (!convId) thread.innerHTML = "";
    Object.assign(payload, {text, images: attachments.slice(), files: attFiles.slice()});
    attachments = []; attFiles = []; renderAtt();
    $("#inp").value = ""; autoGrow();
    userMsg({text, images: payload.images, files: payload.files});
  }
  scrollEnd(true);
  $$(".msgacts").forEach(x => x.remove());
  const body = aiMsg();
  const r = new Renderer(body, true);
  Renderer.autoPreviewed = false;
  await runStream("/api/chat", {method: "POST", body: JSON.stringify(payload)}, r, body);
}
async function attachStream(cid) {  // volver a un chat que sigue trabajando: se reproduce su turno en vivo
  const body = aiMsg(); const r = new Renderer(body, true); Renderer.autoPreviewed = true;
  await runStream(`/api/chat/${cid}/stream?since=0`, {}, r, body);
}
async function runStream(url, init, r, body) {
  detachView(); const seq = viewSeq; viewCtrl = new AbortController();
  setBusy(true);
  let aborted = false;
  try {
    const res = await api(url, Object.assign({signal: viewCtrl.signal}, init));
    if (!res.ok) { const j = await res.json().catch(() => ({})); throw new Error(j.error || res.statusText); }
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const {value, done} = await reader.read();
      if (seq !== viewSeq) { aborted = true; try { reader.cancel(); } catch (e) {} break; }
      if (done) break;
      buf += dec.decode(value, {stream: true});
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, i); buf = buf.slice(i + 2);
        let ev = "message", data = "";
        raw.split("\n").forEach(l => { if (l.startsWith("event:")) ev = l.slice(6).trim(); else if (l.startsWith("data:")) data += l.slice(5).trim(); });
        if (!data) continue;
        const p = JSON.parse(data);
        handleEvent(ev, p, r);
      }
    }
  } catch (e) {
    if (e.name === "AbortError" || seq !== viewSeq) aborted = true;
    else r.error({text: "Error: " + e.message + " (¿sigue abierta la ventana del programa?)"});
  }
  if (aborted || seq !== viewSeq) return;  // el usuario cambió de chat: el trabajo sigue en segundo plano
  r.finish(); clearFase(); addMsgActions(body); setBusy(false); viewCtrl = null; loadConvs(); refreshContinue();
}
function handleEvent(ev, p, r) {
  switch (ev) {
    case "meta": convId = p.conversation_id; setProjectChip(p.project); loadConvs(); break;
    case "reasoning": r.reasoning(p.text); break;
    case "token": r.token(p.text); break;
    case "assistant_break": r.brk(); break;
    case "reset_segment": r.resetSeg(); break;
    case "status": r.setStatus(p.text); break;
    case "fase": showFase(p); break;
    case "plan_stream": planStream(p); break;
    case "plan_review": planReview(p, r); break;
    case "plan_done": planDone(p); break;
    case "tool_delta": liveDelta(p); break;
    case "context": showCtx(p); break;
    case "usage": LAST_USAGE = p; break;
    case "model_switch": r.setStatus("Continuando con " + p.model.replace("::", " · ") + "…"); break;
    case "tool_start": r.toolStart(p); showFase({fase: "herramienta", texto: p.label + "…"}); liveReset(); break;
    case "tool_output": r.toolOutput(p); break;
    case "tool_result": r.toolResult(p); break;
    case "confirm": r.confirm(p); break;
    case "ask_user": r.ask(p); break;
    case "file": r.file(p); break;
    case "image": r.image(p); break;
    case "notice": r.notice(p); break;
    case "error": r.error(p); break;
    case "tasks": renderTasks(p.tasks); break;
    case "project": r.project(p); setProjectChip(p.name); loadProjects().then(() => { if ($("#preview").classList.contains("show") && $("#pvFiles").style.display !== "none") { FT.root = null; loadTree(); } }); break;
  }
}
/* Fase de la IA con cronómetro: cargando / leyendo / pensando / respondiendo / usando herramienta */
const FASE = {t0: 0, tAll: 0, timer: null, el: null};
const FASE_IC = {cargando: "📦", procesando: "📖", esperando: "📡", pensando: "💭", escribiendo: "✍", herramienta: "🛠"};
function showFase(p) {
  let el = $("#fase"); if (!el) return;
  if (!FASE.tAll) FASE.tAll = Date.now();
  FASE.t0 = Date.now(); FASE.txt = p.texto || p.fase; FASE.f = p.fase;
  el.style.display = "flex"; el.className = "fase " + (p.fase || "");
  const tick = () => { const s = Math.round((Date.now() - FASE.t0) / 1000), tt = Math.round((Date.now() - FASE.tAll) / 1000);
    const warn = (FASE.f === "cargando" && s > 90) || (FASE.f === "procesando" && s > 120) ? `<span class="fw">· tarda más de lo normal: el modelo puede ser muy grande para tu PC</span>` : "";
    el.innerHTML = `<span class="fi">${FASE_IC[FASE.f] || "⏳"}</span><span class="ft">${esc(FASE.txt)}</span><span class="fs">${s} s</span><span class="small">total ${tt} s</span>${warn}`; };
  tick(); clearInterval(FASE.timer); FASE.timer = setInterval(tick, 1000);
}
function clearFase() { clearInterval(FASE.timer); FASE.tAll = 0; const el = $("#fase"); if (el) el.style.display = "none"; }
function stopGen() { jpost("/api/stop", {conversation_id: convId}); }
function setBusy(b) { busy = b; const s = $("#send"); s.textContent = b ? "■ Detener" : "Enviar"; s.classList.toggle("stop", b); }
function hasAnyProvider() { return PROVIDERS.some(p => p.ok) || Object.values(CFG.providers || {}).some(p => p.has_key); }

/* ───────────── Adjuntos ───────────── */
function addFile(file) {
  if (file.type.startsWith("image/") && file.size < 25e6) {
    const rd = new FileReader();
    rd.onload = () => { const img = new Image(); img.onload = () => {
        const max = 1568, k = Math.min(1, max / Math.max(img.width, img.height));
        const c = document.createElement("canvas"); c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        attachments.push(c.toDataURL("image/jpeg", 0.88)); renderAtt(); };
      img.src = rd.result; };
    rd.readAsDataURL(file);
    return;
  }
  const fd = new FormData(); fd.append("files", file); fd.append("project", convProject || curProject || "");
  api("/api/upload", {method: "POST", body: fd}).then(r => r.json()).then(r => { attFiles.push(...r.files); renderAtt(); });
}
function renderAtt() {
  const a = $("#att"); a.innerHTML = "";
  attachments.forEach((src, i) => { const t = document.createElement("div"); t.className = "th"; t.innerHTML = `<img src="${src}"><button>✕</button>`;
    t.querySelector("button").onclick = () => { attachments.splice(i, 1); renderAtt(); }; a.append(t); });
  attFiles.forEach((p, i) => { const t = document.createElement("div"); t.className = "th"; t.innerHTML = `📄 ${esc(p.split(/[\\/]/).pop())}<button>✕</button>`;
    t.querySelector("button").onclick = () => { attFiles.splice(i, 1); renderAtt(); }; a.append(t); });
}
$("#attBtn").onclick = () => $("#file").click();
$("#file").onchange = e => { [...e.target.files].forEach(addFile); e.target.value = ""; };
document.addEventListener("paste", e => { [...(e.clipboardData?.items || [])].forEach(it => { if (it.kind === "file") addFile(it.getAsFile()); }); });
let dragN = 0;
document.addEventListener("dragenter", e => { if ([...e.dataTransfer.types].includes("Files")) { dragN++; $("#drop").style.display = "flex"; } });
document.addEventListener("dragleave", () => { if (--dragN <= 0) { dragN = 0; $("#drop").style.display = "none"; } });
document.addEventListener("dragover", e => e.preventDefault());
document.addEventListener("drop", e => { e.preventDefault(); dragN = 0; $("#drop").style.display = "none"; [...e.dataTransfer.files].forEach(addFile); });

/* ───────────── Entrada ───────────── */
const inp = $("#inp");
function autoGrow() { inp.style.height = "auto"; inp.style.height = Math.min(inp.scrollHeight, 240) + "px"; }
inp.addEventListener("input", autoGrow);
inp.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
$("#send").onclick = () => busy ? stopGen() : send();
$("#newChat").onclick = newChat;
$("#menuBtn").onclick = () => $("#side").classList.toggle("open");
const projPath = name => (PROJECTS.find(p => p.name === name) || {}).path;
$("#openFolder").onclick = () => openInFolder(convProject ? (projPath(convProject) || CFG.projects_root) : CFG.projects_root);
$("#projChip").onclick = () => { const p = PROJECTS.find(x => x.name === convProject); p ? editProject(p) : openModal("#projModal"); };

/* ───────────── Modelos ───────────── */
async function loadModels(refresh) {
  const sel = $("#modelSel");
  if (refresh) sel.innerHTML = `<option>Cargando modelos…</option>`;
  PROVIDERS = await jget("/api/models" + (refresh ? "?refresh=1" : ""));
  const cur = sel.dataset.want || CFG.model;
  sel.innerHTML = "";
  let found = false;
  PROVIDERS.forEach(p => {
    const g = document.createElement("optgroup");
    g.label = p.ok ? `${p.name} (${p.models.length})` : `${p.name} — ${p.error || "sin conexión"}`;
    if (p.ok) p.models.forEach(m => { const o = document.createElement("option"); o.value = p.id + "::" + m; o.textContent = m; if (o.value === cur) { o.selected = true; found = true; } g.append(o); });
    else { const o = document.createElement("option"); o.disabled = true; o.textContent = p.error === "desactivado" ? "(desactivado en Ajustes)" : "(" + (p.error || "no disponible") + ")"; g.append(o); }
    sel.append(g);
  });
  if (!found && cur) { const o = document.createElement("option"); o.value = cur; o.textContent = cur.replace("::", " · ") + " (actual)"; o.selected = true; sel.prepend(o); }
  const other = document.createElement("option"); other.value = "__other"; other.textContent = "✏ Escribir otro modelo…"; sel.append(other);
  const all = $("#allModels"); if (all) all.innerHTML = PROVIDERS.filter(p => p.ok).flatMap(p => p.models.map(m => `<option value="${esc(p.id + "::" + m)}">`)).join("");
  updateHint(); updateModelBtn();
  jget("/api/catalogo").then(c => { CATALOG = c; if ($("#modelPop").classList.contains("show")) renderModelPop(); updateModelBtn(); }).catch(() => {});
}
let CATALOG = {modelos: {}, recomendaciones: {}};
function stars(n) { return n ? "★".repeat(n) + "☆".repeat(5 - n) : ""; }
function updateModelBtn() {
  const v = $("#modelSel").value || CFG.model || "";
  const i = CATALOG.modelos[v];
  $("#modelBtnName").innerHTML = `${esc(v.split("::").pop())} <span class="small">${esc((v.split("::")[0] || ""))}</span>` + (i && i.estrellas ? ` <span class="stars">${stars(i.estrellas)}</span>` : "");
}
function friendlyLine(i) {
  const t = [];
  if (i.intel >= 5) t.push("🧠 muy inteligente"); else if (i.intel >= 4) t.push("inteligente");
  if (i.prog >= 5) t.push("💻 excelente programando"); else if (i.prog >= 4) t.push("💻 programa bien");
  if (i.razona >= 5) t.push("piensa a fondo");
  if (i.vel >= 5) t.push("⚡ muy rápido"); else if (i.vel >= 4) t.push("⚡ rápido");
  if (i.vision) t.push("👁 ve imágenes");
  if (i.gratis) t.push("🆓 gratis");
  if (i.tools === false) t.push("⚠ usa mal las herramientas");
  return t.join(" · ");
}
function modelItem(id, i, cur, compact) {
  const st = i.estado, local = /^(ollama|lmstudio)::/.test(id);
  const d = document.createElement("div"); d.className = "mitem2" + (id === cur ? " on" : "") + (i.puntaje < 0 ? " bad" : "") + (st && st.bloqueado ? " down" : "");
  const probando = Object.values(VERIF).some(v => v.activo && v.actual === id);
  const icon = probando ? `<span class="spin" title="Probando ahora con tu cuenta…"></span>` : st ? `<span class="badge r" title="${esc(st.motivo + " — " + st.solucion)}">${st.icono} ${st.bloqueado ? "no funciona" : "en pausa"}</span>`
    : i.verificado ? `<span class="vok" title="Probado: funciona con tu cuenta">✅</span>` : local ? `<span class="vok" title="En tu PC">💻</span>` : `<span class="vq" title="Aún no se ha probado con tu cuenta">❔</span>`;
  const desc = (i.desc || "").split(". ")[0];
  d.innerHTML = `<div class="r1">${icon}<span class="n">${esc(id.split("::").pop())}</span>${compact ? `<span class="prov">${esc(i.proveedor || id.split("::")[0])}</span>` : ""}${i.vanguardia ? `<span class="badge v" title="De los más inteligentes que existen">🚀 vanguardia</span>` : ""}${i.tamano_gb ? `<span class="badge">${i.tamano_gb} GB</span>` : ""}<span class="stars">${stars(i.estrellas)}</span></div>
    <div class="r2">${esc(friendlyLine(i))}${desc ? ` — <span class="dsc">${esc(desc.slice(0, 110))}</span>` : ""}</div>`;
  d.onclick = () => chooseModel(id); bindBubble(d, id);
  return d;
}
let GRATIS_LIST = [], VERIF = {};
function renderModelPop() {
  const q = $("#modelSearch").value.trim().toLowerCase(), cur = $("#modelSel").value;
  const soloOk = CFG.solo_operativos !== false;
  $("#soloOk").checked = soloOk;
  $("#searchClear").style.display = q ? "" : "none";
  const R = CATALOG.recomendaciones || {};
  $("#modelRecos").innerHTML = q ? "" : Object.entries(R).filter(([, m]) => m).map(([k, m]) => `<button class="reco" data-m="${esc(m)}"><b>${esc(k)}</b>${esc(m.split("::").pop())}</button>`).join("");
  $("#modelRecos").querySelectorAll(".reco").forEach(b => { b.onclick = () => chooseModel(b.dataset.m); bindBubble(b, b.dataset.m); });
  const vs = Object.values(VERIF).filter(v => v.activo);
  $("#verifLine").innerHTML = vs.length ? vs.map(v => `<div><span class="spin"></span> Probando ${esc(v.nombre)} con tu cuenta: ${v.hechos}/${v.total} · ✅ ${v.ok} funcionan${v.ocupados ? ` · ⏳ ${v.ocupados} ocupados` : ""} — van apareciendo aquí</div>`).join("") : "";
  const box = $("#modelList"); box.innerHTML = "";
  if (q) { const f = document.createElement("div"); f.className = "mfilter"; f.innerHTML = `🔎 Mostrando solo los que coinciden con «${esc(q)}» <button class="linkbtn">✕ Ver todos</button>`; f.querySelector("button").onclick = e => { e.stopPropagation(); $("#modelSearch").value = ""; renderModelPop(); }; box.append(f); }
  const match = (pid, m) => !q || (pid + " " + m + " " + ((CATALOG.modelos[pid + "::" + m] || {}).familia || "")).toLowerCase().includes(q);
  const score = i => (i.verificado ? 1000 : 0) + (i.puntaje || 0);
  // ⭐ Los que ya se probaron y funcionan con tus claves, primero
  if (!q) {
    const best = [];
    PROVIDERS.forEach(p => (p.models || []).forEach(m => { const id = p.id + "::" + m, i = CATALOG.modelos[id] || {};
      if (i.puntaje >= 0 && !(i.estado && i.estado.bloqueado) && (i.verificado || /^(ollama|lmstudio)::/.test(id))) best.push([id, i]); }));
    best.sort((a, b) => (b[1].puntaje || 0) - (a[1].puntaje || 0));
    if (best.length) {
      const g = document.createElement("div"); g.className = "mgroup best"; g.innerHTML = `⭐ Los mejores que funcionan con tus claves <span class="hid">(probados)</span>`; box.append(g);
      best.slice(0, 8).forEach(([id, i]) => box.append(modelItem(id, i, cur, true)));
    }
  }
  const inactivos = [];
  PROVIDERS.forEach(p => {
    if (p.error === "desactivado") { inactivos.push(p); return; }
    let ms = (p.models || []).filter(m => match(p.id, m));
    if (q && !ms.length) return;
    const hidden = soloOk ? ms.filter(m => { const e = (CATALOG.modelos[p.id + "::" + m] || {}).estado; return e && e.bloqueado && p.id + "::" + m !== cur; }) : [];
    ms = ms.filter(m => !hidden.includes(m)).sort((a, b) => score(CATALOG.modelos[p.id + "::" + b] || {}) - score(CATALOG.modelos[p.id + "::" + a] || {}));
    const nOk = ms.filter(m => (CATALOG.modelos[p.id + "::" + m] || {}).verificado).length;
    const g = document.createElement("div"); g.className = "mgroup" + (p.ok ? "" : " down");
    const local = /ollama|lmstudio/.test(p.id);
    if (p.ok) g.innerHTML = `${esc(p.name)} <span class="hid">· ${ms.length} modelos${!local && nOk ? ` · ✅ ${nOk} probados` : ""}${!local && ms.length - nOk ? ` · ❔ ${ms.length - nOk} sin probar` : ""}${hidden.length ? ` · <a class="showhid" title="Mostrar también los que no funcionan">${hidden.length} ocultos porque no funcionan con tu cuenta (ver)</a>` : ""}</span>`;
    else { g.innerHTML = `<b>⛔ ${esc(p.name)} no está funcionando</b><span>${esc(p.error || "no disponible")}</span>`; g.title = "Pulsa para arreglarlo"; g.onclick = () => { closeModelPop(); openFix(p); }; }
    if (!p.ok && q) return;
    const sh = g.querySelector(".showhid"); if (sh) sh.onclick = e => { e.stopPropagation(); CFG.solo_operativos = false; jpost("/api/config", {solo_operativos: false}); renderModelPop(); };
    box.append(g);
    if (p.ok && !ms.length && local) { const e = document.createElement("div"); e.className = "small mempty"; e.textContent = p.id === "ollama" ? "Ollama está abierto pero no tiene modelos descargados (ej.: ollama pull qwen3-coder:30b)." : "LM Studio no tiene modelos cargados/descargados."; box.append(e); }
    ms.forEach(m => box.append(modelItem(p.id + "::" + m, CATALOG.modelos[p.id + "::" + m] || {}, cur, false)));
  });
  // IAs que aún no están conectadas: se muestran con su botón para conseguir la clave gratis
  const byId = Object.fromEntries(GRATIS_LIST.map(g => [g.id, g]));
  const conn = inactivos.filter(p => byId[p.id] && !byId[p.id].decisor && (!q || (p.name + " " + p.id).toLowerCase().includes(q)));
  if (conn.length) {
    const g = document.createElement("div"); g.className = "mgroup"; g.textContent = "➕ Conecta más IAs gratis (aún no disponibles)"; box.append(g);
    conn.forEach(p => {
      const gi = byId[p.id]; const d = document.createElement("div"); d.className = "mconn";
      d.innerHTML = `<div class="ct"><b>${gi.icono} ${esc(gi.nombre)}</b>${gi.sin_cuenta ? ` <span class="badge g">sin cuenta</span>` : ""}<div class="small">${esc(gi.gratis)}</div></div>` +
        (gi.sin_cuenta ? `<button class="btn ok" data-a="on">Activar</button>` : gi.remoto ? `<button class="btn" data-a="gr">Configurar en 🎁 IA gratis</button>` :
          `<button class="btn" data-a="web">🔑 Conseguir clave gratis ↗</button><input type="password" placeholder="Pega la clave" spellcheck="false" autocomplete="off">${gi.pide_cuenta ? `<input data-a="acc" placeholder="ID de cuenta">` : ""}<button class="btn ok" data-a="on">Guardar</button>`) + `<div class="res small"></div>`;
      const w = d.querySelector("[data-a=web]"); if (w) w.onclick = e => { e.stopPropagation(); window.open(gi.clave_url, "_blank"); };
      const gr = d.querySelector("[data-a=gr]"); if (gr) gr.onclick = e => { e.stopPropagation(); closeModelPop(); openModal("#gratisModal"); renderGratis(); renderVanguardia(); };
      d.querySelectorAll("input").forEach(x => x.onclick = e => e.stopPropagation());
      const on = d.querySelector("[data-a=on]");
      if (on) on.onclick = async e => {
        e.stopPropagation(); const res = d.querySelector(".res"); res.innerHTML = `<span class="spin"></span> Probando…`;
        const inp = d.querySelector("input[type=password]"), acc = d.querySelector("[data-a=acc]");
        const r = await jpost("/api/gratis/guardar", {id: p.id, clave: inp ? inp.value : "", cuenta: acc ? acc.value : ""});
        res.innerHTML = r.ok ? `<span class="ok-t">✔ ${r.modelos} modelos. Probando cuáles funcionan…</span>` : `<span class="bad-t">✖ ${esc((r.error || "").slice(0, 160))}</span>`;
        if (r.ok) { await loadModels(false); renderModelPop(); pollVerif(); }
      };
      box.append(d);
    });
  }
  const o = document.createElement("div"); o.className = "mitem"; o.innerHTML = `<span class="n">✏ Escribir otro modelo…</span>`;
  o.onclick = () => { $("#modelSel").value = "__other"; $("#modelSel").onchange({target: $("#modelSel")}); closeModelPop(); }; box.append(o);
}
let VERIF_T = null;
async function pollVerif() {
  try { VERIF = await jget("/api/verificador"); } catch (e) { return; }
  const act = Object.values(VERIF).some(v => v.activo);
  if (act || VERIF_T) {  // mientras se prueban, los modelos van apareciendo en vivo
    const c = await jget("/api/catalogo?rapido=1").catch(() => null); if (c) CATALOG = c;
    try { PROVIDERS = await jget("/api/models"); } catch (e) {}
  }
  if ($("#modelPop").classList.contains("show")) {
    const pop = $("#modelPop"), sc = pop.scrollTop; renderModelPop(); pop.scrollTop = sc;
  }
  clearTimeout(VERIF_T); VERIF_T = act ? setTimeout(pollVerif, 3000) : null;
}
function bindBubble(el, id) {
  el.onmouseenter = () => showBubble(el, id); el.onmouseleave = hideBubble;
}
function showBubble(el, id) {
  const i = CATALOG.modelos[id]; const b = $("#modelBubble");
  if (!i) { b.classList.remove("show"); return; }
  const bar = n => `<span class="bar" style="width:${(n || 0) * 18}px"></span> ${n || 0}/5`;
  const tl = i.tools === true ? "✅ Sí (nativas)" : i.tools === "texto" ? "🟡 Por texto" : i.tools === false ? "❌ Limitado" : "❔ Sin probar";
  b.innerHTML = `<h4>${esc(id.split("::").pop())}</h4><div class="fam">${esc(i.familia)} · ${esc(i.proveedor || "")}</div>
    <div>${esc(i.desc || "")}</div>
    <div class="rows"><span>💻 Programación</span><span>${bar(i.prog)}</span><span>🧠 Inteligencia</span><span>${bar(i.intel)}</span>
    <span>🧩 Razonamiento</span><span>${bar(i.razona)}</span>
    <span>⚡ Velocidad</span><span>${bar(i.vel)}</span><span>💲 Costo</span><span>${i.gratis ? "🆓 Gratis" : "De pago por uso"}</span><span>🪙 Consumo</span><span>${esc(i.tokens || "")}</span>
    <span>🛠 Herramientas</span><span>${tl}</span><span>👁 Visión</span><span>${i.vision ? "✅ Ve imágenes" : "No (Noviark usa un ayudante visual)"}</span>
    ${i.tamano_gb ? `<span>💾 Tamaño</span><span>${i.tamano_gb} GB</span>` : ""}${i.contexto ? `<span>📏 Contexto</span><span>${i.contexto} tokens</span>` : ""}</div>
    ${i.estado ? `<div class="warn"><b>${i.estado.icono} ${i.estado.bloqueado ? "No operativo" : "En pausa"}:</b> ${esc(i.estado.motivo)}<br>💡 ${esc(i.estado.solucion)}</div>` : ""}
    ${i.vanguardia ? `<div class="tip">🚀 De vanguardia: de los modelos más inteligentes disponibles${i.gratis ? " y gratis" : ""}.</div>` : ""}
    ${i.cabe ? `<div class="${String(i.cabe).startsWith("✅") || String(i.cabe).startsWith("☁") ? "" : "warn"}">${esc(i.cabe)}</div>` : ""}
    ${i.para && i.para.length ? `<div class="tip">👍 Recomendado para: <b>${esc(i.para.join(", "))}</b></div>` : ""}${i.evitar || i.puntaje < 0 ? `<div class="warn">⚠ No recomendado como agente</div>` : ""}`;
  const r = el.getBoundingClientRect(); b.classList.add("show");
  const w = 330, x = r.right + 10 + w > innerWidth ? r.left - w - 10 : r.right + 10;
  b.style.left = Math.max(8, x) + "px"; b.style.top = Math.min(innerHeight - b.offsetHeight - 10, Math.max(8, r.top - 10)) + "px";
}
function hideBubble() { $("#modelBubble").classList.remove("show"); }
async function chooseModel(id) {
  if (HOME && !convId && $("#phome")) { await jpost(`/api/projects/${encodeURIComponent(HOME)}`, {modelo: id}); const pp = PROJECTS.find(x => x.name === HOME); if (pp) pp.modelo = id; setTimeout(() => { const e = $("#phModelName"); if (e) e.textContent = id.split("::").pop() + " · " + id.split("::")[0]; }, 50); }
  closeModelPop(); selectModel(id); const sel = $("#modelSel"); sel.value = id; await sel.onchange({target: sel}); updateModelBtn();
}
function closeModelPop() { $("#modelPop").classList.remove("show"); hideBubble(); }
$("#searchClear").onclick = e => { e.stopPropagation(); $("#modelSearch").value = ""; renderModelPop(); $("#modelSearch").focus(); };
$("#modelBtn").onclick = e => { e.stopPropagation(); const p = $("#modelPop"); p.classList.toggle("show"); if (p.classList.contains("show")) { $("#modelSearch").value = ""; renderModelPop(); setTimeout(() => { $("#modelSearch").value = ""; renderModelPop(); }, 60); pollVerif();
  if (!GRATIS_LIST.length) jget("/api/gratis").then(l => { GRATIS_LIST = l; renderModelPop(); }); } else hideBubble(); };
$("#soloOk").onchange = e => { e.stopPropagation(); CFG.solo_operativos = $("#soloOk").checked; jpost("/api/config", {solo_operativos: CFG.solo_operativos}); renderModelPop(); };
$("#verifNow").onclick = async e => { e.stopPropagation(); await jpost("/api/verificador", {forzar: true}); setTimeout(pollVerif, 1500); };
$("#modelSearch").oninput = renderModelPop;
// composedPath: aunque el elemento pulsado se redibuje (y salga del DOM), sabemos que el clic fue DENTRO de la lista
document.addEventListener("click", e => { const path = e.composedPath ? e.composedPath() : [];
  const inside = id => path.some(x => x && x.id === id) || (e.target.closest && e.target.closest("#" + id));
  if (!inside("modelPick")) closeModelPop(); if (!inside("ctxMenu")) $("#ctxMenu").style.display = "none"; });
function selectModel(m) {
  const sel = $("#modelSel"); sel.dataset.want = m;
  if (![...sel.options].some(o => o.value === m)) { const o = document.createElement("option"); o.value = m; o.textContent = m.replace("::", " · "); sel.prepend(o); }
  sel.value = m; updateHint(); updateModelBtn();
}
$("#modelSel").onchange = async e => {
  let v = e.target.value;
  if (v === "__other") {
    const id = prompt("ID del modelo. Ejemplos:\n  nvidia::deepseek-ai/deepseek-v3.1\n  ollama::qwen3:8b\n  lmstudio::openai/gpt-oss-20b\n(sin prefijo = NVIDIA)", "nvidia::");
    if (!id) { e.target.value = CFG.model; return; }
    v = id.includes("::") ? id.trim() : "nvidia::" + id.trim();
    selectModel(v);
  }
  $("#modelSel").dataset.want = v;
  CFG = await jpost("/api/config", {model: v});
  if (convId) jpost("/api/conversations/" + convId, {model: v});
  updateHint();
};
$("#refreshModels").onclick = () => loadModels(true);
$("#permSel").onchange = async e => { CFG = await jpost("/api/config", {permission_mode: e.target.value}); updateHint(); };
let LAST_USAGE = null;
function showCtx(p) {
  const pct = Math.min(100, Math.round(p.usado / p.limite * 100));
  const k = n => n >= 1000 ? (n / 1000).toFixed(1) + "k" : n;
  $("#ctxMeter").innerHTML = `${p.compacto ? "🧭 paso a paso · " : ""}contexto <span class="m"><i class="${pct > 80 ? "hi" : ""}" style="width:${pct}%"></i></span>${k(p.usado)} / ${k(p.limite)} tokens`;
}
function updateHint() {
  const m = ($("#modelSel").value || CFG.model || "").replace("::", " · ");
  const perm = {preguntar: "te pide permiso antes de ejecutar comandos o escribir fuera de los proyectos", auto_seguro: "solo pide permiso para lo riesgoso", auto: "actúa sin pedir permiso"}[CFG.permission_mode] || "";
  $("#hint").textContent = `${m} · ${perm}`;
}

/* ───────────── Panel derecho: vista previa, editor y explorador ───────────── */
const PV = {tabs: [], current: null, editor: null, dirty: false};
const TEXT_EXT = new Set(["py","js","mjs","cjs","ts","tsx","jsx","json","md","txt","css","scss","html","htm","xml","yml","yaml","toml","ini","cfg","env","sql","sh","bat","cmd","ps1","psm1","java","kt","cs","cpp","c","h","hpp","go","rs","rb","php","ino","dart","swift","lua","r","vb","vue","svelte","gradle","properties","csv","log","gitignore","svg"]);
const CM_MODE = {py:"python",js:"javascript",mjs:"javascript",cjs:"javascript",jsx:"javascript",ts:"text/typescript",tsx:"text/typescript",json:"application/json",
  md:"markdown",css:"css",scss:"text/x-scss",html:"htmlmixed",htm:"htmlmixed",xml:"xml",svg:"xml",yml:"yaml",yaml:"yaml",toml:"toml",sql:"sql",sh:"shell",
  ps1:"powershell",psm1:"powershell",java:"text/x-java",kt:"text/x-kotlin",cs:"text/x-csharp",cpp:"text/x-c++src",c:"text/x-csrc",h:"text/x-csrc",hpp:"text/x-c++src",
  ino:"text/x-c++src",go:"go",rs:"rust",php:"application/x-httpd-php",dart:"dart"};
function showPanel(which) {
  $("#preview").classList.add("show");
  $$("#pvSwitch [data-pv]").forEach(b => b.classList.toggle("on", b.dataset.pv === which));
  $("#pvFiles").style.display = which === "files" ? "flex" : "none";
  $("#pvView").style.display = which === "view" ? "flex" : "none";
  $("#pvLive").style.display = which === "live" ? "flex" : "none";
  $("#pvPlan").style.display = which === "plan" ? "flex" : "none";
  if (which === "files") loadTree();
}
$$("#pvSwitch [data-pv]").forEach(b => b.onclick = () => showPanel(b.dataset.pv));
function openPreview(path) {
  if (!PV.tabs.includes(path)) PV.tabs.push(path);
  PV.current = path; showPanel("view"); renderTabs(); loadPreview(path);
}
function renderTabs() {
  const t = $("#pvTabs"); t.innerHTML = "";
  PV.tabs.forEach(p => { const b = document.createElement("button"); b.className = p === PV.current ? "on" : ""; b.textContent = p.split(/[\\/]/).pop(); b.title = p + " (clic derecho para cerrar)";
    b.onclick = () => { if (!confirmDiscard()) return; PV.current = p; renderTabs(); loadPreview(p); };
    b.oncontextmenu = ev => { ev.preventDefault(); PV.tabs = PV.tabs.filter(x => x !== p); if (PV.current === p) { PV.current = PV.tabs[0] || null; if (PV.current) loadPreview(PV.current); else $("#pvBody").innerHTML = ""; } renderTabs(); };
    t.append(b); });
}
function confirmDiscard() { return !PV.dirty || confirm("Hay cambios sin guardar en el editor. ¿Descartarlos?"); }
function setEditing(on) {
  $("#pvEdit").style.display = on ? "none" : ""; $("#pvSave").style.display = on ? "" : "none";
  $("#pvBody").classList.toggle("editing", on); if (!on) { PV.editor = null; PV.dirty = false; }
}
async function loadPreview(path) {
  setEditing(false);
  const b = $("#pvBody"), name = path.split(/[\\/]/).pop(), ext = extOf(name);
  $("#pvName").textContent = name; $("#pvName").title = path;
  $("#pvEdit").style.display = TEXT_EXT.has(ext) || !name.includes(".") ? "" : "none";
  if (["html", "htm"].includes(ext)) { b.innerHTML = `<iframe sandbox="allow-scripts allow-forms allow-modals allow-popups" src="${rawUrl(path)}?v=${Date.now()}"></iframe>`; return; }
  if (["svg", "pdf"].includes(ext)) { b.innerHTML = `<iframe src="${rawUrl(path)}?v=${Date.now()}"></iframe>`; return; }
  if (["png", "jpg", "jpeg", "gif", "webp", "bmp", "ico"].includes(ext)) { b.innerHTML = `<img src="${fileUrl(path)}&v=${Date.now()}">`; return; }
  if (["xlsx", "docx", "pptx", "zip", "exe", "mp3", "mp4", "dll", "7z", "rar"].includes(ext)) { b.innerHTML = `<div class="md">Este tipo de archivo no se puede previsualizar aquí. <a href="${fileUrl(path, 1)}">Descargar</a> o ábrelo desde 📂.</div>`; return; }
  const r = await api(`/api/file_text?p=${encodeURIComponent(path)}`);
  if (!r.ok) { b.innerHTML = `<div class="md">No se pudo abrir el archivo (¿muy grande o binario?).</div>`; return; }
  const {text} = await r.json();
  if (ext === "md") { b.innerHTML = `<div class="md">${md(text)}</div>`; enhance(b); return; }
  const lang = LANG_OF[ext] || "plaintext";
  b.innerHTML = `<pre><code class="language-${lang}"></code></pre>`;
  const code = b.querySelector("code"); code.textContent = text;
  try { hljs.highlightElement(code); } catch (e) {}
  b.querySelector("pre").style.cssText = "padding:14px;font:13px/1.5 Consolas,monospace;margin:0";
}
async function startEdit() {
  if (!PV.current || !window.CodeMirror) return;
  const r = await api(`/api/file_text?p=${encodeURIComponent(PV.current)}`);
  if (!r.ok) { alert("No se puede editar este archivo."); return; }
  const {text} = await r.json();
  const b = $("#pvBody"); b.innerHTML = ""; setEditing(true);
  PV.editor = CodeMirror(b, {value: text, mode: CM_MODE[extOf(PV.current)] || null, theme: "material-darker", lineNumbers: true,
    matchBrackets: true, autoCloseBrackets: true, styleActiveLine: true, indentUnit: 4, tabSize: 4, lineWrapping: false,
    extraKeys: {"Ctrl-S": saveEdit, "Cmd-S": saveEdit, "Ctrl-/": "toggleComment", "Tab": cm => cm.somethingSelected() ? cm.indentSelection("add") : cm.replaceSelection("    ")}});
  PV.editor.on("change", () => { PV.dirty = true; $("#pvName").textContent = "● " + PV.current.split(/[\\/]/).pop(); });
  setTimeout(() => PV.editor.refresh(), 30);
}
async function saveEdit() {
  if (!PV.editor) return;
  const r = await jpost("/api/archivo/guardar", {ruta: PV.current, contenido: PV.editor.getValue(), proyecto: convProject});
  if (r.ok) { PV.dirty = false; $("#pvName").textContent = PV.current.split(/[\\/]/).pop() + " ✔ guardado"; }
  else alert("No se pudo guardar: " + (r.error || "solo se pueden editar archivos dentro de tus proyectos"));
}
$("#pvEdit").onclick = startEdit;
$("#pvSave").onclick = saveEdit;
$("#pvClose").onclick = () => { if (confirmDiscard()) $("#preview").classList.remove("show"); };
$("#pvReload").onclick = () => PV.current && confirmDiscard() && loadPreview(PV.current);
$("#pvExt").onclick = () => PV.current && window.open(["html", "htm", "svg", "pdf"].includes(extOf(PV.current)) ? rawUrl(PV.current) : fileUrl(PV.current), "_blank");
$("#pvFolder").onclick = () => PV.current && openInFolder(PV.current);
$("#estadoBtn").onclick = showEstado;
$("#pvToggle").onclick = () => { if ($("#preview").classList.contains("show")) { if (confirmDiscard()) $("#preview").classList.remove("show"); } else showPanel(PV.current ? "view" : "files"); };

/* Explorador de archivos */
const FT = {root: null, open: new Set(), sel: null};
function treeRoot() { if (FT.custom) return FT.custom; return convProject ? (projPath(convProject) || CFG.projects_root) : (curProject ? projPath(curProject) : CFG.projects_root); }
async function loadTree() {
  const root = treeRoot(); if (!root) return;
  if (FT.root !== root) { FT.root = root; FT.open = new Set(); }
  $("#ftRoot").textContent = "📁 " + root; $("#ftRoot").title = root;
  const box = $("#fileTree"); box.innerHTML = "";
  box.append(await renderDir(root, true));
}
async function renderDir(path, isRoot) {
  const wrap = document.createElement("div"); if (!isRoot) wrap.className = "fkids";
  let r; try { r = await jget(`/api/arbol?ruta=${encodeURIComponent(path)}`); } catch (e) { wrap.innerHTML = `<div class="small">(sin acceso)</div>`; return wrap; }
  if (!r.items) { wrap.innerHTML = `<div class="small">(sin acceso)</div>`; return wrap; }
  if (!r.items.length) wrap.innerHTML = `<div class="small" style="padding:2px 8px">(vacía)</div>`;
  for (const it of r.items) {
    const n = document.createElement("div"); n.className = "fnode" + (FT.sel === it.path ? " sel" : ""); n.dataset.path = it.path; n.dataset.dir = it.dir ? "1" : "";
    n.draggable = true;
    n.innerHTML = `<span class="tw">${it.dir ? (FT.open.has(it.path) ? "▾" : "▸") : ""}</span><span>${it.dir ? "📁" : (ICONS[extOf(it.name)] || "📄")}</span><span>${esc(it.name)}</span>${it.dir ? "" : `<span class="sz">${fmtSize(it.size)}</span>`}`;
    wrap.append(n);
    let kids = null;
    if (it.dir && FT.open.has(it.path)) { kids = await renderDir(it.path); wrap.append(kids); }
    n.onclick = async () => {
      FT.sel = it.path; $$(".fnode.sel").forEach(x => x.classList.remove("sel")); n.classList.add("sel");
      if (it.dir) { if (FT.open.has(it.path)) { FT.open.delete(it.path); kids && kids.remove(); kids = null; n.querySelector(".tw").textContent = "▸"; }
        else { FT.open.add(it.path); kids = await renderDir(it.path); n.after(kids); n.querySelector(".tw").textContent = "▾"; } }
    };
    n.ondblclick = () => { if (!it.dir) { if (confirmDiscard()) openPreview(it.path); } };
    n.oncontextmenu = e => { e.preventDefault(); fileMenu(e, it); };
    n.ondragstart = e => { e.dataTransfer.setData("text/noviq-path", it.path); e.dataTransfer.effectAllowed = "move"; };
    if (it.dir) {
      n.ondragover = e => { if ([...e.dataTransfer.types].includes("text/noviq-path")) { e.preventDefault(); e.stopPropagation(); n.classList.add("drop"); } };
      n.ondragleave = () => n.classList.remove("drop");
      n.ondrop = async e => { e.preventDefault(); e.stopPropagation(); n.classList.remove("drop");
        const src = e.dataTransfer.getData("text/noviq-path"); if (!src || src === it.path) return;
        const r = await jpost("/api/archivo/mover", {origen: src, destino: it.path});
        if (!r.ok) alert(r.error || "No se pudo mover"); FT.open.add(it.path); loadTree(); };
    }
  }
  if (isRoot) { // soltar en la raíz
    wrap.ondragover = e => { if ([...e.dataTransfer.types].includes("text/noviq-path")) e.preventDefault(); };
    wrap.ondrop = async e => { e.preventDefault(); const src = e.dataTransfer.getData("text/noviq-path"); if (!src) return;
      const r = await jpost("/api/archivo/mover", {origen: src, destino: path}); if (!r.ok) alert(r.error || "No se pudo mover"); loadTree(); };
  }
  return wrap;
}
function fileMenu(e, it) {
  const m = $("#ctxMenu");
  const dir = it.dir ? it.path : it.path.replace(/[\\/][^\\/]+$/, "");
  const opts = [
    ...(it.dir ? [] : [["👁 Abrir", () => openPreview(it.path)], ["✏ Editar", async () => { openPreview(it.path); setTimeout(startEdit, 150); }]]),
    ["💬 Pedir a la IA que lo revise", () => { $("#inp").value = `Revisa ${it.dir ? "la carpeta" : "el archivo"} «${it.path}», busca errores y corrígelos si hace falta.`; $("#inp").focus(); }],
    null,
    ["📄 Nuevo archivo aquí", () => newItem(dir, "archivo")], ["📁 Nueva carpeta aquí", () => newItem(dir, "carpeta")],
    ["✎ Renombrar", async () => { const nn = prompt("Nuevo nombre:", it.name); if (!nn || nn === it.name) return;
      const r = await jpost("/api/archivo/renombrar", {ruta: it.path, nombre: nn}); if (!r.ok) alert(r.error || "No se pudo renombrar"); loadTree(); }],
    ["📂 Mostrar en el Explorador", () => openInFolder(it.path)],
    null,
    ["🗑 Enviar a la papelera", async () => { if (!confirm(`¿Enviar «${it.name}» a la papelera?`)) return;
      const r = await jpost("/api/archivo/eliminar", {ruta: it.path}); if (!r.ok) alert(r.msg || "No se pudo eliminar"); loadTree(); }],
  ];
  m.innerHTML = ""; opts.forEach(o => { if (!o) { m.append(document.createElement("hr")); return; } const b = document.createElement("button"); b.textContent = o[0]; b.onclick = () => { m.style.display = "none"; o[1](); }; m.append(b); });
  m.style.display = "block"; m.style.left = Math.min(e.clientX, innerWidth - 210) + "px"; m.style.top = Math.min(e.clientY, innerHeight - m.offsetHeight - 8) + "px";
}
async function newItem(dir, tipo) {
  const n = prompt(tipo === "carpeta" ? "Nombre de la carpeta:" : "Nombre del archivo (con extensión):"); if (!n) return;
  const r = await jpost("/api/archivo/nuevo", {carpeta: dir, nombre: n, tipo}); if (!r.ok) { alert(r.error || "No se pudo crear"); return; }
  FT.open.add(dir); await loadTree(); if (tipo !== "carpeta") { openPreview(r.path); setTimeout(startEdit, 150); }
}
$("#ftNewFile").onclick = () => newItem(FT.sel && document.querySelector(`.fnode.sel`)?.dataset.dir ? FT.sel : treeRoot(), "archivo");
$("#ftNewDir").onclick = () => newItem(FT.sel && document.querySelector(`.fnode.sel`)?.dataset.dir ? FT.sel : treeRoot(), "carpeta");
$("#ftRefresh").onclick = loadTree;
$("#ftOpen").onclick = () => openInFolder(treeRoot());

/* ───────────── Pantalla de proyectos ───────────── */
function openProjects() { openModal("#projsModal"); loadProjects().then(renderProjects); }
function ago(t) { if (!t) return "sin actividad"; const s = Date.now() / 1000 - t; if (s < 3600) return "hace " + Math.max(1, Math.round(s / 60)) + " min"; if (s < 86400) return "hace " + Math.round(s / 3600) + " h"; if (s < 86400 * 30) return "hace " + Math.round(s / 86400) + " días"; return new Date(t * 1000).toLocaleDateString(); }
function renderProjects() {
  const q = $("#pjSearch").value.trim().toLowerCase(), sort = $("#pjSort").value, f = $("#pjFilter").value;
  const runProj = new Set(LAST_CONVS.filter(c => c.running).map(c => c.project));
  let list = PROJECTS.filter(p => (!q || (p.name + " " + (p.tipo || "") + " " + p.path + " " + (p.descripcion || "")).toLowerCase().includes(q))
    && (!f || (f === "trabajando" ? runProj.has(p.name) : f === "externos" ? p.externo : !p.externo)));
  const wk = PROJECTS.filter(p => p.actividad && Date.now() / 1000 - p.actividad < 7 * 86400).length;
  $("#pjStats").textContent = `${PROJECTS.length} proyectos · ${PROJECTS.filter(p => p.externo).length} existentes en tu PC · ${wk} activos esta semana` + (runProj.size ? ` · ⚡ ${runProj.size} trabajando ahora` : "");
  $("#projGrid").className = $("#pjView").value === "list" ? "list" : "";
  if (sort === "nombre") list.sort((a, b) => a.name.localeCompare(b.name)); else if (sort === "tipo") list.sort((a, b) => (a.tipo || "").localeCompare(b.tipo || ""));
  const g = $("#projGrid"); g.innerHTML = list.length ? "" : `<div class="small">No hay proyectos que coincidan.</div>`;
  list.forEach(p => {
    const c = document.createElement("div"); c.className = "pcard" + (p.existe === false ? " missing" : "") + (runProj.has(p.name) ? " running" : "");
    c.innerHTML = `<div class="ph"><span class="pi">${p.externo ? "📂" : ""}${TIPO_ICON[p.tipo] || "🗂"}</span><span class="pn" title="${esc(p.name)}">${esc(p.name)}</span>${runProj.has(p.name) ? `<span class="run" title="Una IA está trabajando aquí"></span>` : ""}<span class="badge">${esc(p.tipo || "general")}</span></div>
      <div class="pd">${esc((p.descripcion || "").slice(0, 110))}</div>
      <div class="pp">${esc(p.path)}${p.existe === false ? " — ⚠ la carpeta ya no existe" : ""}</div>
      <div class="small">🕒 ${ago(p.actividad)} · 💬 ${p.conversaciones || 0} chats${p.externo ? " · existente en tu PC" : ""}${p.comandos && p.comandos.ejecutar ? " · ▶ " + esc(p.comandos.ejecutar) : ""}</div>
      <div class="pa"><button class="go" data-a="chat">💬 Trabajar</button>${p.ultima_conv ? `<button data-a="last">↩ Último chat</button>` : ""}<button data-a="files">📁 Archivos</button><button data-a="test">🧪 Probar</button><button data-a="folder">📂</button><button data-a="edit">✎</button>${p.externo ? `<button data-a="unlink" title="Quitar de Noviark (no borra archivos)">✖</button>` : ""}</div>`;
    c.querySelector("[data-a=chat]").onclick = () => { $("#projsModal").classList.remove("show"); showProjectHome(p.name); };
    const last = c.querySelector("[data-a=last]"); if (last) last.onclick = () => { $("#projsModal").classList.remove("show"); curProject = p.name; loadProjects(); openConv(p.ultima_conv); };
    c.querySelector("[data-a=files]").onclick = () => { $("#projsModal").classList.remove("show"); curProject = p.name; if (!convId) setProjectChip(p.name); loadProjects(); loadConvs(); FT.root = null; showPanel("files"); };
    c.querySelector("[data-a=test]").onclick = () => { $("#projsModal").classList.remove("show"); curProject = p.name; loadProjects(); newChat(); $("#inp").value = "Revisa todo el proyecto: usa probar_proyecto, analiza los errores y corrígelos uno por uno hasta que las pruebas pasen."; send(); };
    c.querySelector("[data-a=folder]").onclick = () => openInFolder(p.path);
    c.querySelector("[data-a=edit]").onclick = () => editProject(p);
    const ul = c.querySelector("[data-a=unlink]"); if (ul) ul.onclick = async () => { if (!confirm(`¿Quitar «${p.name}» de Noviark? Tus archivos NO se borran.`)) return; await jpost(`/api/projects/${encodeURIComponent(p.name)}/quitar`); loadProjects(); };
    g.append(c);
  });
}
$("#allProjs").onclick = openProjects;

/* ───────────── IA gratis ───────────── */
async function renderGratis() {
  const list = await jget("/api/gratis"); GRATIS_LIST = list; const g = $("#gratisGrid"); g.innerHTML = "";
  let grupo = null;
  list.forEach(p => {
    if (p.grupo !== grupo) { grupo = p.grupo; const h = document.createElement("h3"); h.className = "ggroup"; h.textContent = grupo; g.append(h); }
    const d = document.createElement("div"); d.className = "gcard" + (p.activo && (p.ok || p.tiene_clave) ? " on" : "");
    const est = p.activo ? (p.ok ? `<span class="badge g">✔ activo · ${p.modelos} modelos</span>` : `<span class="badge c" title="${esc(p.error || "")}">${esc((p.error || "activo").slice(0, 38))}${(p.error || "").length > 38 ? "…" : ""}</span>`) : (p.tiene_clave ? `<span class="badge">clave guardada</span>` : `<span class="badge">sin conectar</span>`);
    d.innerHTML = `<h3>${p.icono} ${esc(p.nombre)} ${est}</h3><div class="gt">${esc(p.gratis)}</div>` +
      (p.un_clic ? `<button class="btn ok" data-a="oneclick">🔗 Conectar con un clic (inicias sesión en su web)</button>` : "") +
      (p.local ? `<div class="row2"><button class="btn" data-a="web">⬇ Descargar ↗</button><button class="btn ok" data-a="save">Activar</button></div>`
        : p.remoto ? `<div class="row2"><select data-a="mdl"><option value="qwen3-coder:30b">Qwen3-Coder 30B (programar)</option><option value="gpt-oss:20b">GPT-OSS 20B (razona)</option><option value="qwen3:32b">Qwen3 32B</option><option value="devstral:24b">Devstral 24B</option><option value="gemma3:27b">Gemma 3 27B (visión)</option></select><button class="btn" data-a="nb">1. ⬇ Cuaderno para Kaggle</button><button class="btn" data-a="web">2. Abrir Kaggle ↗</button></div><div class="small">3. En Kaggle: New Notebook → File → Import notebook → sube el archivo → GPU T4 x2 + Internet → Run All. 4. Pega aquí la URL y el token que muestra:</div><div class="row2"><input data-a="url" placeholder="https://….trycloudflare.com" value="${esc(p.url || "")}"><input type="password" placeholder="Token"><button class="btn ok" data-a="save">Conectar</button></div>`
        : p.decisor ? `<div class="row2"><button class="btn" data-a="web">Obtener clave ↗</button></div><div class="row2"><input type="password" placeholder="Clave de TypeSafe (opcional)" spellcheck="false"><button class="btn ok" data-a="save">Guardar</button></div>`
        : p.sin_cuenta ? `<div class="row2"><button class="btn ok" data-a="save">⚡ Activar sin cuenta</button><button class="btn" data-a="web">Web ↗</button></div><div class="row2"><input type="password" placeholder="(opcional) clave o token gratis para más límite" spellcheck="false"></div>`
        : p.pide_cuenta ? `<div class="row2"><button class="btn" data-a="web">1. Obtener clave gratis ↗</button></div><div class="row2"><input data-a="acc" placeholder="2. ID de cuenta" value="${esc(p.cuenta || "")}"><input type="password" placeholder="3. Clave (API token)" spellcheck="false"><button class="btn ok" data-a="save">Guardar y probar</button></div>`
        : `<div class="row2"><button class="btn" data-a="web">1. Obtener clave gratis ↗</button></div><div class="row2"><input type="password" placeholder="2. Pega aquí la clave" spellcheck="false"><button class="btn ok" data-a="save">Guardar y probar</button></div>`) +
      (p.id === "openrouter" ? `<label class="chk" style="margin:0;font-size:12.5px"><input type="checkbox" data-a="free" ${p.solo_gratis !== false ? "checked" : ""}> Mostrar solo modelos gratuitos (:free)</label>` : "") +
      `<div class="res"></div>`;
    d.querySelector("[data-a=web]").onclick = () => window.open(p.clave_url, "_blank");
    const nb = d.querySelector("[data-a=nb]"); if (nb) nb.onclick = () => { const a = document.createElement("a"); a.href = `/api/remoto/cuaderno?modelo=${encodeURIComponent(d.querySelector("[data-a=mdl]").value)}&t=${TOKEN}`; a.download = "noviq_servidor_gpu_kaggle.ipynb"; a.click(); };
    const res = d.querySelector(".res");
    d.querySelector("[data-a=save]").onclick = async () => {
      const inp = d.querySelector("input[type=password]"); const free = d.querySelector("[data-a=free]");
      res.innerHTML = `<span class="spin"></span> Probando…`;
      const acc = d.querySelector("[data-a=acc]"), url = d.querySelector("[data-a=url]");
      const r = await jpost("/api/gratis/guardar", Object.assign({id: p.id, clave: inp ? inp.value : "", cuenta: acc ? acc.value : "", url: url ? url.value : ""}, free ? {solo_gratis: free.checked} : {}));
      if (r.nota) { res.innerHTML = `<span class="ok-t">✔ ${esc(r.nota)}</span>`; return; }
      res.innerHTML = r.ok ? `<span class="ok-t">✔ Funciona: ${r.modelos} modelos disponibles${r.ejemplos && r.ejemplos.length ? " (ej. " + esc(r.ejemplos.slice(0, 3).join(", ")) + ")" : ""}</span>` : `<span class="bad-t">✖ ${esc(r.error || "no respondió")}</span>`;
      await loadModels(true); setTimeout(renderGratis, 1200);
    };
    const oc = d.querySelector("[data-a=oneclick]");
    if (oc) oc.onclick = async () => {
      const r = await jpost("/api/gratis/openrouter"); window.open(r.url, "_blank");
      res.innerHTML = `<span class="spin"></span> Inicia sesión en OpenRouter y acepta; Noviark recibirá la clave automáticamente…`;
      let n = 0; const t = setInterval(async () => { const l = await jget("/api/gratis"); const o = l.find(x => x.id === "openrouter");
        if (o && o.tiene_clave && o.activo) { clearInterval(t); res.innerHTML = `<span class="ok-t">✔ Conectado: ${o.modelos} modelos gratis</span>`; await loadModels(true); renderGratis(); }
        if (++n > 100) clearInterval(t); }, 3000);
    };
    g.append(d);
  });
}
$("#openGratis").onclick = () => { openModal("#gratisModal"); renderGratis(); renderVanguardia(); };
$("#pjSearch").oninput = renderProjects; $("#pjSort").onchange = renderProjects; $("#pjFilter").onchange = renderProjects; $("#pjView").onchange = renderProjects;
$("#pjNew").onclick = () => { $("#projsModal").classList.remove("show"); $("#newProj").click(); };
$("#pjImport").onclick = () => { $("#imPath").value = ""; $("#imName").value = ""; $("#imOut").textContent = ""; openModal("#importModal"); };
$("#imPick").onclick = async () => { $("#imOut").innerHTML = `<span class="spin"></span> Se abrió el selector de carpetas de Windows (puede quedar detrás de esta ventana)…`;
  const r = await jpost("/api/elegir_carpeta"); $("#imOut").textContent = r.ruta ? "" : "No se eligió ninguna carpeta."; if (r.ruta) $("#imPath").value = r.ruta; };
$("#imOk").onclick = async () => {
  const ruta = $("#imPath").value.trim(); if (!ruta) return;
  const r = await api("/api/projects/importar", {method: "POST", body: JSON.stringify({ruta, nombre: $("#imName").value.trim()})}).then(x => x.json());
  if (!r.ok) { $("#imOut").innerHTML = `<span class="bad-t">${esc(r.error)}</span>`; return; }
  $("#importModal").classList.remove("show"); $("#projsModal").classList.remove("show");
  curProject = r.name; await loadProjects(); newChat();
  $("#inp").value = `Analiza este proyecto (${r.tipo}): revisa su estructura con mapa_codigo, ejecuta probar_proyecto y dime qué hace, qué errores tiene y qué mejorarías.`;
  $("#inp").focus();
};

/* ───────────── Modales ───────────── */
function openModal(id) { $(id).classList.add("show"); }
$$(".modal").forEach(m => { m.addEventListener("mousedown", e => { if (e.target === m) m.classList.remove("show"); }); m.querySelectorAll("[data-close]").forEach(b => b.onclick = () => m.classList.remove("show")); });
$$(".tabs").forEach(t => t.querySelectorAll("button").forEach(b => b.onclick = () => {
  t.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
  const pane = $("#" + b.dataset.tab); pane.parentElement.querySelectorAll(".tabpane").forEach(p => p.classList.toggle("on", p === pane));
}));

/* Ajustes */
let FB = [];
function provCard(id, p) {
  const st = PROVIDERS.find(x => x.id === id);
  const status = !p.enabled ? "" : st?.ok ? `<span class="ok-t">✔ ${st.models.length} modelos</span>` : st ? `<span class="bad-t">${esc(st.error)}</span>` : "";
  const d = document.createElement("details"); d.className = "prov"; d.dataset.id = id;
  d.open = !!(p.enabled && (p.has_key || p.local)) || id === "nvidia";
  d.innerHTML = `<summary><h3 style="display:inline-flex;width:calc(100% - 20px)">${esc(p.name)} <span class="small">${p.has_key ? "🔑 " : ""}${status}</span><label class="chk" style="margin:0 0 0 auto" onclick="event.stopPropagation()"><input type="checkbox" data-f="enabled" ${p.enabled ? "checked" : ""}> activo</label></h3></summary>
    ${id.startsWith("custom") ? `<label>Nombre</label><input data-f="name" value="${esc(p.name)}">` : ""}
    <label>URL base (…/v1)</label><input data-f="base_url" value="${esc(p.base_url || "")}">
    ${p.local ? `<div class="small">IA local: no necesita clave. ${id === "ollama" ? "Instala Ollama y descarga un modelo (ej. <code>ollama pull qwen3:8b</code>). Para más contexto define OLLAMA_CONTEXT_LENGTH=32768." : "En LM Studio: pestaña Developer → Start Server y carga un modelo."}</div>`
      : `<label>API keys — una por línea (puedes poner claves de varias cuentas: Noviark usa la que funcione con cada modelo)${p.web ? ` · <a href="${esc(p.web)}" target="_blank">obtener clave</a>` : ""}</label><textarea data-f="api_keys" rows="${Math.max(2, (p.api_keys || []).length + 1)}" spellcheck="false" placeholder="pega aquí tu clave">${esc((p.api_keys || []).join("\n"))}</textarea>
      <div class="row2"><span class="small">${(p.api_keys || []).length ? `🔑 ${(p.api_keys || []).length} clave(s) guardada(s)` : "Sin claves"}</span><button class="btn" data-a="testkeys" type="button">🩺 Probar cada clave</button><span class="small kres"></span></div>`}`;
  const tk = d.querySelector("[data-a=testkeys]");
  if (tk) tk.onclick = async () => {
    const out = d.querySelector(".kres"); out.innerHTML = `<span class="spin"></span> Probando…`;
    const r = await jpost("/api/claves/probar", {pid: id});
    out.innerHTML = (r.claves || []).map(k => k.ok ? `<span class="ok-t">✔ clave ${k.n} (${esc(k.mask)}) funciona${k.modelos != null ? " · " + k.modelos + " modelos" : ""}</span>` : `<span class="bad-t">✖ clave ${k.n} (${esc(k.mask)}): ${esc(k.error)}</span>`).join("<br>") || esc(r.error || "sin claves");
  };
  return d;
}
async function openSettings() {
  $("#vaultInfo").textContent = CFG.vault || "";
  const list = $("#provList"); list.innerHTML = "";
  Object.entries(CFG.providers).forEach(([id, p]) => list.append(provCard(id, p)));
  $("#c-temp").value = CFG.temperature; $("#c-max").value = CFG.max_tokens; $("#c-reason").value = CFG.reasoning_effort || "";
  $("#c-img").value = CFG.image_model; $("#c-sys").value = CFG.system_prompt || ""; $("#c-toolmode").value = CFG.tool_mode;
  const L = CFG.local || {};
  $("#l-vram").value = L.vram_gb || 16; $("#l-ram").value = L.ram_gb || 32; $("#l-maxctx").value = String(L.max_ctx || 32768);
  $("#l-numctx").value = L.num_ctx || 0; $("#l-compact").value = L.modo_compacto || "auto"; $("#l-think").value = L.pensar || "auto";
  $("#l-steps").value = L.max_steps || 150; $("#l-native").checked = L.ollama_nativo !== false; $("#l-tests").checked = CFG.pruebas_auto !== false;
  $("#a-ejec").value = CFG.ejecutor || "auto"; $("#a-vision").value = CFG.modelo_vision || ""; $("#a-aux").value = CFG.modelo_auxiliar || "";
  $("#a-team").value = CFG.equipo_max || 3; $("#a-navdir").checked = !!CFG.navegador_directo;
  $("#c-steps").value = CFG.max_steps; $("#c-projdir").value = CFG.projects_dir || ""; $("#c-projroot").textContent = "Carpeta actual: " + CFG.projects_root;
  $("#fb-on").checked = CFG.fallback_enabled !== false; $("#fb-timeout").value = CFG.read_timeout || 240;
  const ESC = CFG.escalado || {}, GD = CFG.guardian || {};
  $("#esc-on").checked = ESC.activo !== false; $("#esc-pago").checked = ESC.permitir_pago !== false; $("#dg-auto").checked = CFG.diagnostico_auto !== false;
  $("#gd-on").checked = GD.activo !== false; $("#gd-chars").value = GD.max_razonamiento || 16000; $("#gd-secs").value = GD.max_seg_razonamiento || 150;
  FB = (CFG.fallback_models || []).slice(); renderFb();
  const ov = CFG.model_overrides || {};
  $("#ovList").innerHTML = Object.keys(ov).length ? Object.entries(ov).map(([k, v]) => `${esc(k)}: ${esc(JSON.stringify(v))}`).join("<br>") : "(nada aprendido todavía)";
  jget("/api/tools").then(t => $("#toolList").innerHTML = t.map(x => `<div><b>${esc(x.name)}</b> — ${esc(x.desc.slice(0, 140))}</div>`).join(""));
  openModal("#cfgModal");
}
function renderFb() {
  const box = $("#fbList");
  box.innerHTML = FB.length ? "" : `<div class="small">(sin respaldo configurado)</div>`;
  FB.forEach((m, i) => {
    const d = document.createElement("div"); d.className = "srv"; d.style.display = "flex"; d.style.gap = "6px"; d.style.alignItems = "center";
    d.innerHTML = `<b>${i + 1}.</b><span style="flex:1">${esc(m.replace("::", " · "))}</span><button class="ib" data-a="up">▲</button><button class="ib" data-a="dn">▼</button><button class="ib" data-a="rm">✕</button>`;
    d.querySelector("[data-a=up]").onclick = () => { if (i > 0) { [FB[i - 1], FB[i]] = [FB[i], FB[i - 1]]; renderFb(); } };
    d.querySelector("[data-a=dn]").onclick = () => { if (i < FB.length - 1) { [FB[i + 1], FB[i]] = [FB[i], FB[i + 1]]; renderFb(); } };
    d.querySelector("[data-a=rm]").onclick = () => { FB.splice(i, 1); renderFb(); };
    box.append(d);
  });
  const sel = $("#fbAdd"); sel.innerHTML = "";
  PROVIDERS.filter(p => p.ok).forEach(p => { const g = document.createElement("optgroup"); g.label = p.name;
    p.models.forEach(m => { const o = document.createElement("option"); o.value = p.id + "::" + m; o.textContent = m; g.append(o); }); sel.append(g); });
  const o = document.createElement("option"); o.value = "__other"; o.textContent = "✏ Escribir otro…"; sel.append(o);
}
$("#fbAddBtn").onclick = () => {
  let v = $("#fbAdd").value;
  if (v === "__other") { v = prompt("ID del modelo (proveedor::modelo), ej. gemini::gemini-3.8-flash"); if (!v) return; }
  if (v && !FB.includes(v)) { FB.push(v); renderFb(); }
};
$("#addProv").onclick = () => {
  let n = 2; while (CFG.providers["custom" + n]) n++;
  const id = "custom" + n; CFG.providers[id] = {name: "Proveedor " + n, base_url: "", enabled: true, api_keys: []};
  $("#provList").append(provCard(id, CFG.providers[id]));
};
$("#openCfg").onclick = openSettings;
$("#cfgSave").onclick = async () => {
  const providers = {};
  $$("#provList .prov").forEach(card => {
    const id = card.dataset.id, o = {};
    card.querySelectorAll("[data-f]").forEach(el => {
      const f = el.dataset.f;
      o[f] = el.type === "checkbox" ? el.checked : f === "api_keys" ? el.value.split(/\s+/).map(x => x.trim()).filter(Boolean) : el.value.trim();
    });
    if (o.api_keys && o.api_keys.length && !CFG.providers[id]?.has_key && !CFG.providers[id]?.local) o.enabled = true;
    providers[id] = o;
  });
  const patch = {
    providers,
    temperature: parseFloat($("#c-temp").value) || 0.6, max_tokens: parseInt($("#c-max").value) || 8192,
    reasoning_effort: $("#c-reason").value, image_model: $("#c-img").value.trim(), system_prompt: $("#c-sys").value,
    ejecutor: $("#a-ejec").value, modelo_vision: $("#a-vision").value.trim(), modelo_auxiliar: $("#a-aux").value.trim(),
    equipo_max: parseInt($("#a-team").value) || 3, navegador_directo: $("#a-navdir").checked,
    local: Object.assign({}, CFG.local || {}, {vram_gb: parseFloat($("#l-vram").value) || 16, ram_gb: parseFloat($("#l-ram").value) || 32,
      max_ctx: parseInt($("#l-maxctx").value) || 32768, num_ctx: parseInt($("#l-numctx").value) || 0, modo_compacto: $("#l-compact").value,
      pensar: $("#l-think").value, max_steps: parseInt($("#l-steps").value) || 150, ollama_nativo: $("#l-native").checked}),
    pruebas_auto: $("#l-tests").checked,
    tool_mode: $("#c-toolmode").value, max_steps: parseInt($("#c-steps").value) || 40, projects_dir: $("#c-projdir").value.trim(),
    fallback_enabled: $("#fb-on").checked, fallback_models: FB, read_timeout: parseInt($("#fb-timeout").value) || 240,
    escalado: Object.assign({}, CFG.escalado || {}, {activo: $("#esc-on").checked, permitir_pago: $("#esc-pago").checked}),
    guardian: Object.assign({}, CFG.guardian || {}, {activo: $("#gd-on").checked,
      max_razonamiento: Math.max(3000, parseInt($("#gd-chars").value) || 16000), max_seg_razonamiento: Math.max(30, parseInt($("#gd-secs").value) || 150)}),
    diagnostico_auto: $("#dg-auto").checked,
  };
  CFG = await jpost("/api/config", patch);
  $("#cfgModal").classList.remove("show");
  await loadModels(true); loadProjects();
};
$("#l-opt").onclick = async () => {
  $("#l-optout").textContent = "Aplicando…";
  const r = await jpost("/api/optimizar_ollama");
  $("#l-optout").textContent = (r.hecho || []).map(x => `${x.ok ? "✔" : "✖"} ${x.var}=${x.valor}`).join("\n") + "\n" + (r.nota || "");
};
$("#diagBtn").onclick = async () => {
  const m = $("#modelSel").value;
  $("#diagOut").innerHTML = `<span class="spin"></span> Probando ${esc(m)}…`;
  const r = await jpost("/api/diagnostico", {model: m});
  $("#diagOut").innerHTML = `<b>${esc(r.verdict || "")}</b>\nModelo: ${esc(r.model)} · ${r.seconds}s` +
    (r.ok ? `\nFin: ${esc(r.finish)} · razonamiento: ${r.reasoning_chars} caracteres · herramientas nativas: ${r.native ? "sí" : "no"}${r.content ? "\nRespuesta: " + esc(r.content) : ""}` : `\n${esc(r.error || "")}`);
  CFG = await jget("/api/config");
};
$("#logBtn").onclick = async () => { const r = await jget("/api/registro"); const o = $("#logOut"); o.style.display = "block"; o.textContent = r.lines.join("\n") || "(vacío)"; o.scrollTop = o.scrollHeight; };
$("#resetOv").onclick = async () => { await jpost("/api/reset_model_overrides"); CFG = await jget("/api/config"); $("#ovList").textContent = "(reiniciado)"; };

/* Proyectos */
$("#newProj").onclick = () => { $("#np-name").value = ""; $("#np-desc").value = ""; $("#np-inst").value = ""; openModal("#projModal"); $("#np-name").focus(); };
$("#np-ok").onclick = async () => {
  const nombre = $("#np-name").value.trim(); if (!nombre) return;
  const r = await jpost("/api/projects", {nombre, tipo: $("#np-tipo").value, descripcion: $("#np-desc").value, instrucciones: $("#np-inst").value});
  $("#projModal").classList.remove("show");
  curProject = r.name; await loadProjects(); newChat();
};
let editing = null;
function editProject(p) {
  editing = p; $("#pe-title").textContent = "🗂 " + p.name; $("#pe-desc").value = p.descripcion || ""; $("#pe-inst").value = p.instrucciones || "";
  openModal("#projEdit");
}
$("#pe-ok").onclick = async () => { await jpost("/api/projects/" + encodeURIComponent(editing.name), {descripcion: $("#pe-desc").value, instrucciones: $("#pe-inst").value}); $("#projEdit").classList.remove("show"); loadProjects(); };
$("#pe-open").onclick = () => openInFolder(editing.path);

/* Memoria */
$("#openMem").onclick = async () => { $("#memText").value = (await jget("/api/memoria")).text; openModal("#memModal"); };
$("#memSave").onclick = async () => { await jpost("/api/memoria", {text: $("#memText").value}); $("#memModal").classList.remove("show"); };

/* MCP */
function renderMcp(servers) {
  $("#mcpStatus").innerHTML = servers.length ? servers.map(s => `<div class="srv"><b>${esc(s.name)}</b> — <span class="${s.status === "conectado" ? "ok-t" : s.status === "error" ? "bad-t" : ""}">${esc(s.status)}</span>
    ${s.tools?.length ? `<div class="small">${s.tools.length} herramientas: ${esc(s.tools.join(", "))}</div>` : ""}${s.error ? `<div class="small bad-t">${esc(s.error)}</div>` : ""}</div>`).join("")
    : `<div class="small">No hay servidores activos.</div>`;
}
$("#openMcp").onclick = async () => {
  const r = await jget("/api/mcp"); $("#mcpText").value = r.config; renderMcp(r.servers); openModal("#mcpModal");
  const s = await jget("/api/sistema");
  $("#mcpSys").innerHTML = (s.node ? `<span class="ok-t">✔ Node.js instalado</span>` : `<span class="bad-t">✖ Falta Node.js (necesario para controlar el navegador): <a href="https://nodejs.org" target="_blank">descárgalo aquí</a> e instala la versión LTS.</span>`)
    + (s.chrome === false ? " · Chrome no detectado" : "") + (s.edge === false ? " · Edge no detectado" : "")
    + (s.navegador_activo ? ` · <span class="ok-t">🌐 Control de navegador ACTIVO</span>` : "");
};
async function addPreset(key) {
  $("#mcpStatus").innerHTML = `<span class="spin"></span> Instalando y arrancando (la primera vez puede tardar 1-2 minutos)…`;
  const r = await jpost("/api/mcp/preset", {key}); $("#mcpText").value = r.config; renderMcp(r.servers);
  let n = 0; const poll = setInterval(async () => { const m = await jget("/api/mcp"); renderMcp(m.servers);
    if (++n > 30 || m.servers.every(x => x.status !== "iniciando")) clearInterval(poll); }, 4000);
}
$("#presetChrome").onclick = () => addPreset("navegador_chrome");
$("#presetEdge").onclick = () => addPreset("navegador_edge");
$("#mcpSave").onclick = async () => {
  $("#mcpStatus").innerHTML = `<span class="spin"></span> Iniciando servidores…`;
  const r = await api("/api/mcp", {method: "POST", body: JSON.stringify({config: $("#mcpText").value})}).then(r => r.json());
  if (!r.ok) { $("#mcpStatus").innerHTML = `<div class="bad-t">${esc(r.error)}</div>`; return; }
  renderMcp(r.servers);
  setTimeout(async () => renderMcp((await jget("/api/mcp")).servers), 6000);
};

/* ───────────── Inicio ───────────── */
(async function init() {
  CFG = await jget("/api/config");
  $("#permSel").value = CFG.permission_mode;
  setProjectChip(null); showEmpty();
  loadProjects(); loadConvs();
  await loadModels(false);
  if (!hasAnyProvider()) openSettings();
  inp.focus();
})();

/* Avisos y seguimiento de los trabajos en segundo plano */
function toast(text, onclick) {
  const t = document.createElement("div"); t.className = "toast"; t.textContent = text;
  if (onclick) { t.style.cursor = "pointer"; t.onclick = () => { onclick(); t.remove(); }; }
  $("#toasts").append(t); setTimeout(() => t.remove(), 9000);
}
const WAIT_SEEN = new Set();
setInterval(async () => {
  if (!RUN_PREV.size) return;
  loadConvs();
  try { const w = await jget("/api/trabajando");
    w.filter(x => x.espera_permiso && x.id !== convId && !WAIT_SEEN.has(x.id)).forEach(x => { WAIT_SEEN.add(x.id); toast(`✋ «${x.title}» espera tu permiso`, () => openConv(x.id)); });
  } catch (e) {}
}, 4000);

/* ───────────── Modo vanguardia (los modelos gratis más inteligentes) ───────────── */
async function applyVanguardia(out) {
  out.innerHTML = `<span class="spin"></span> Probando los modelos gratuitos más inteligentes (puede tardar ~30 s)…`;
  const r = await jpost("/api/vanguardia", {aplicar: true});
  const why = x => x.kind === "ocupado" || x.kind === "limite" ? "ocupado ahora (se probará más tarde)" : x.kind === "no_disponible" ? "tu cuenta no lo tiene" : x.kind === "clave_invalida" || x.kind === "sin_clave" ? "problema con la clave" : "no respondió";
  const des = Object.entries(r.descartados || {});
  const desc = des.length ? `<details class="small"><summary>${des.length} modelo(s) no se usarán por ahora — ver por qué</summary>${des.map(([m, x]) => `<div>• ${esc(m.split("::").pop())}: ${esc(why(x))}</div>`).join("")}</details>` : "";
  if (!r.ok) { out.innerHTML = `<span class="bad-t">✖ ${esc(r.error || "falló")}</span>` + desc; return; }
  out.innerHTML = `<div class="ok-t">✔ Listo. Tu IA principal ahora es <b>${esc(r.modelo.split("::").pop())}</b> (probada: funciona con tu cuenta).</div><div class="small">Si se ocupa o falla, Noviark sigue solo con: ${esc(r.respaldo.map(m => m.split("::").pop()).join(" → ") || "—")}</div>` + desc;
  CFG.model = r.modelo; selectModel(r.modelo); const sel = $("#modelSel"); sel.value = r.modelo; if (convId) jpost("/api/conversations/" + convId, {model: r.modelo});
  loadModels(false);
}
$("#vgApply").onclick = e => { e.stopPropagation(); applyVanguardia($("#modelMsg")); };
$("#vgApply2").onclick = () => applyVanguardia($("#vgOut"));
$("#vgCheck").onclick = async e => {
  e.stopPropagation(); const out = $("#modelMsg");
  const ids = [...new Set([$("#modelSel").value, ...(CATALOG.vanguardia || []), ...(CFG.fallback_models || [])].filter(Boolean))].slice(0, 10);
  out.innerHTML = `<span class="spin"></span> Verificando ${ids.length} modelos…`;
  const r = await jpost("/api/salud/probar", {ids});
  out.innerHTML = Object.entries(r).map(([m, x]) => x.ok ? `<div class="ok-t">✔ ${esc(m.split("::").pop())} funciona (${(x.ms / 1000).toFixed(1)} s)${x.clave > 1 ? ` con tu clave n.º ${x.clave}` : ""}</div>` : `<div class="${x.kind === "ocupado" ? "" : "bad-t"}">${x.kind === "ocupado" ? "⏳" : "✖"} ${esc(m.split("::").pop())}: ${esc((x.motivo || "").split("\n")[0].slice(0, 120))}</div>`).join("");
  loadModels(false);
};
async function renderVanguardia() {
  const c = await jget("/api/catalogo").catch(() => null); if (!c) return;
  CATALOG = c; const V = c.config_vanguardia || {};
  $("#vgPlan").checked = V.planificar !== false; $("#vgAuto").checked = CFG.respaldo_auto !== false;
  const opts = [["auto", "🤖 Automático (el más inteligente gratis que funcione)"], ["no", "Desactivado (la IA principal planifica)"]]
    .concat(Object.entries(c.modelos).filter(([, i]) => i.puntaje >= 0).sort((a, b) => b[1].cerebro - a[1].cerebro).slice(0, 25).map(([m, i]) => [m, `${i.vanguardia ? "🚀 " : ""}${m.split("::").pop()} · ${m.split("::")[0]}${i.gratis ? " 🆓" : ""}`]));
  $("#vgBrain").innerHTML = opts.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("");
  $("#vgBrain").value = c.modelo_cerebro || "auto";
  $("#vgOut").innerHTML = (c.cerebros || []).length ? `Cerebro actual (auto): <b>${esc(c.cerebros[0].split("::").pop())}</b>` : "Conecta un proveedor gratuito para activar el cerebro.";
}
$("#vgPlan").onchange = () => jpost("/api/vanguardia", {planificar: $("#vgPlan").checked});
$("#vgBrain").onchange = () => jpost("/api/vanguardia", {modelo_cerebro: $("#vgBrain").value});
$("#vgAuto").onchange = () => { CFG.respaldo_auto = $("#vgAuto").checked; jpost("/api/config", {respaldo_auto: CFG.respaldo_auto}); };

/* ───────────── Salud: IAs no operativas con motivo y solución ───────────── */
function openFix(p) {
  if (p.kind === "apagado" || (p.error || "").includes("abierto")) { toast("🔌 Abre " + p.name + " (y su servidor) y pulsa ↻ en la lista de modelos."); return; }
  openModal("#gratisModal"); renderGratis(); renderVanguardia();
}
async function checkHealth() {
  const r = await jget("/api/salud").catch(() => null); const bar = $("#healthBar"); if (!r) return;
  const probs = (r.problemas || []).filter(p => p.kind !== "apagado");
  if (!probs.length) { bar.style.display = "none"; return; }
  bar.innerHTML = probs.map(p => `<div class="hb"><span>⚠ <b>${esc(p.nombre)}</b>: <span>${esc((p.error || "").split("\n")[0].slice(0, 200))}</span></span><button class="btn" data-p="${esc(p.id)}">Arreglar</button></div>`).join("") + `<button class="hbx" title="Ocultar">✕</button>`;
  bar.style.display = "block";
  bar.querySelectorAll("[data-p]").forEach(b => b.onclick = () => openFix(probs.find(x => x.id === b.dataset.p)));
  bar.querySelector(".hbx").onclick = () => bar.style.display = "none";
}
setTimeout(checkHealth, 2500);

/* ───────────── PC y tareas programadas ───────────── */
const DIAS = ["L", "M", "X", "J", "V", "S", "D"];
$("#tpDias").innerHTML = DIAS.map((d, i) => `<label class="dchk"><input type="checkbox" value="${i}" checked>${d}</label>`).join("");
$("#tpTipo").onchange = () => { const t = $("#tpTipo").value; $("#tpHora").style.display = t === "diario" ? "" : "none"; $("#tpDias").style.display = t === "diario" ? "" : "none"; $("#tpFecha").style.display = t === "una_vez" ? "" : "none"; $("#tpCada").style.display = t === "intervalo" ? "" : "none"; };
async function renderPc() {
  const st = await jget("/api/pc");
  const w = st.windows_mcp;
  $("#pcState").innerHTML = (st.windows ? "✔ Control integrado disponible (PowerShell + UI Automation)." : "⚠ El control del PC funciona solo en Windows.") +
    "<br>" + (w ? (w.status === "conectado" ? `✔ Windows-MCP conectado (${w.tools.length} herramientas).` : `Windows-MCP: ${esc(w.status)} ${esc(w.error || "")}`) : "Windows-MCP no activado (opcional).");
  const si = await jget("/api/inicio_windows"); $("#pcStartup").checked = !!si.activo;
  $("#tpProj").innerHTML = `<option value="">(sin proyecto)</option>` + PROJECTS.map(p => `<option>${esc(p.name)}</option>`).join("");
  if (convProject) $("#tpProj").value = convProject;
  const list = await jget("/api/programadas"); const box = $("#tpList");
  box.innerHTML = list.length ? "" : `<div class="small">Aún no hay tareas programadas. También puedes pedírselo a la IA: «cada lunes a las 9 revisa mi proyecto y corre las pruebas».</div>`;
  list.forEach(t => {
    const d = document.createElement("div"); d.className = "tprow" + (t.activa ? "" : " off");
    const last = (t.historial || []).slice(-1)[0];
    d.innerHTML = `<div><b>${esc(t.nombre)}</b> <span class="badge">${esc(t.descripcion)}</span>${t.proyecto ? ` <span class="badge">🗂 ${esc(t.proyecto)}</span>` : ""}
      <div class="small">${esc(t.instruccion.slice(0, 160))}</div>
      <div class="small">${t.activa && t.proxima ? "⏭ próxima: " + new Date(t.proxima * 1000).toLocaleString() : "⏸ pausada"}${last ? " · última: " + new Date(last.t * 1000).toLocaleString() + " (" + esc(last.resultado) + ")" : ""}</div></div>
      <div class="pa"><button data-a="run">▶ Ahora</button><button data-a="tog">${t.activa ? "⏸" : "▶ Reanudar"}</button>${last && last.conv ? `<button data-a="ver">💬 Ver</button>` : ""}<button data-a="del">🗑</button></div>`;
    d.querySelector("[data-a=run]").onclick = async () => { const r = await jpost(`/api/programadas/${t.id}/ejecutar`); toast(r.conv && r.conv.length === 16 ? "⏰ Tarea iniciada en segundo plano" : "⏰ " + r.conv); setTimeout(() => { loadConvs(); renderPc(); }, 800); };
    d.querySelector("[data-a=tog]").onclick = async () => { await jpost(`/api/programadas/${t.id}/${t.activa ? "pausar" : "reanudar"}`); renderPc(); };
    d.querySelector("[data-a=del]").onclick = async () => { if (confirm("¿Eliminar la tarea programada?")) { await jpost(`/api/programadas/${t.id}/eliminar`); renderPc(); } };
    const ver = d.querySelector("[data-a=ver]"); if (ver) ver.onclick = () => { $("#pcModal").classList.remove("show"); openConv(last.conv); };
    box.append(d);
  });
}
$("#openPc").onclick = () => { openModal("#pcModal"); $("#tpTipo").onchange(); renderPc(); };
$("#pcTest").onclick = async () => { $("#pcOut").innerHTML = `<span class="spin"></span> Probando…`; const r = await jpost("/api/pc/probar"); $("#pcOut").innerHTML = `<span class="${r.ok ? "ok-t" : "bad-t"}">${esc(r.texto)}</span>`; };
$("#pcMcp").onclick = async () => { $("#pcOut").innerHTML = `<span class="spin"></span> Instalando/activando Windows-MCP (la primera vez tarda 1-2 min)…`; const r = await jpost("/api/pc/activar");
  $("#pcOut").innerHTML = r.ok ? `<span class="ok-t">✔ ${esc(r.nota)}</span>` : `<span class="bad-t">✖ ${esc(r.error)}</span>`; setTimeout(renderPc, 8000); };
$("#pcStartup").onchange = async () => { const r = await jpost("/api/inicio_windows", {activo: $("#pcStartup").checked}); if (!r.ok && $("#pcStartup").checked) { toast("No pude crear el acceso de inicio: " + (r.error || "")); $("#pcStartup").checked = false; } };
$("#tpSave").onclick = async () => {
  const tipo = $("#tpTipo").value, cuando = {tipo};
  if (tipo === "diario") { cuando.hora = $("#tpHora").value || "08:00"; const d = [...$("#tpDias").querySelectorAll("input:checked")].map(x => +x.value); if (d.length && d.length < 7) cuando.dias = d; }
  else if (tipo === "una_vez") cuando.fecha = $("#tpFecha").value;
  else cuando.cada_min = +$("#tpCada").value || 60;
  const r = await jpost("/api/programadas", {nombre: $("#tpName").value, instruccion: $("#tpText").value, cuando, proyecto: $("#tpProj").value || null, modelo: $("#modelSel").value, autonomo: $("#tpAuto").checked});
  $("#tpOut").innerHTML = r.ok ? `<span class="ok-t">✔ Programada: próxima ${new Date(r.tarea.proxima * 1000).toLocaleString()}</span>` : `<span class="bad-t">✖ ${esc(r.error)}</span>`;
  if (r.ok) { $("#tpName").value = ""; $("#tpText").value = ""; renderPc(); }
};

/* ───────────── Aprendizaje ───────────── */
async function renderApr() {
  const r = await jget("/api/aprendizaje"), h = await jget("/api/salud");
  $("#aprOn").checked = r.activo; $("#aprStats").textContent = `${r.stats.errores || 0} errores vistos · ${r.stats.resueltos || 0} soluciones aprendidas · ${Object.keys(r.pip || {}).length} paquetes aprendidos`;
  const mods = Object.entries(h.modelos || {}), provs = Object.entries(h.proveedores || {});
  $("#aprHealth").innerHTML = (mods.length || provs.length) ? `<h3>🩺 Modelos y proveedores no operativos (se reintentan solos)</h3>` + provs.concat(mods).map(([k, e]) =>
    `<div class="tprow"><div><b>${esc(k.replace("::*", ""))}</b> ${e.kind ? `<span class="badge r">${esc(e.kind)}</span>` : ""}<div class="small">${esc(e.motivo)}</div><div class="small">💡 ${esc(e.solucion)}</div></div><div class="pa"><button data-r="${esc(k)}">↻ Reintentar</button></div></div>`).join("") : "";
  $("#aprHealth").querySelectorAll("[data-r]").forEach(b => b.onclick = async () => { await jpost("/api/salud/reset", {model: b.dataset.r}); renderApr(); loadModels(true); });
  $("#aprList").innerHTML = `<h3>📚 Lecciones</h3>` + r.lecciones.map(v => `<div class="tprow"><div><code>${esc(v.firma)}</code> ${v.fuente === "base" ? `<span class="badge">base</span>` : `<span class="badge g">aprendido · ${v.resueltas}×</span>`}
    <div class="small">${(v.soluciones || []).slice(0, 2).map(x => "✔ " + esc(x.pasos)).join("<br>")}</div></div><div class="pa"><button data-f="${esc(v.firma)}">🗑</button></div></div>`).join("");
  $("#aprList").querySelectorAll("[data-f]").forEach(b => b.onclick = async () => { await jpost("/api/aprendizaje", {borrar: b.dataset.f}); renderApr(); });
}
$("#openApr").onclick = () => { openModal("#aprModal"); renderApr(); };
$("#aprOn").onchange = () => jpost("/api/aprendizaje", {activo: $("#aprOn").checked});
$("#aprClear").onclick = async () => { if (confirm("¿Olvidar todo lo aprendido? (se conserva el conocimiento base)")) { await jpost("/api/aprendizaje", {borrar: ""}); renderApr(); } };

/* ───────────── Plan en vivo + aprobación con cuenta regresiva ───────────── */
const PLAN = {raz: null, txt: null, timer: null, id: null};
function planStream(p) {
  const b = $("#planBody");
  if (p.inicio || !PLAN.txt) {
    showPanel("plan");
    b.innerHTML = `<h3>🧠 ${esc(p.modelo || "La IA")} está diseñando el plan…</h3><details open><summary>💭 Razonamiento (en vivo)</summary><pre class="praz"></pre></details><pre class="ptxt"></pre>`;
    PLAN.raz = b.querySelector(".praz"); PLAN.txt = b.querySelector(".ptxt");
    if (p.inicio) return;
  }
  const el = p.tipo === "razonamiento" ? PLAN.raz : PLAN.txt;
  el.textContent += p.text || ""; el.scrollTop = el.scrollHeight;
}
function planForm(pl) {
  const lines = a => (a || []).join("\n");
  return `<label>Resumen</label><textarea data-f="resumen" rows="2">${esc(pl.resumen || "")}</textarea>
    ${pl.tecnologia !== undefined ? `<label>Tecnología</label><input data-f="tecnologia" value="${esc(pl.tecnologia || "")}">` : ""}
    <label>Tareas (una por línea, en orden)</label><textarea data-f="tareas" rows="${Math.min(14, (pl.tareas || []).length + 2)}">${esc(lines(pl.tareas))}</textarea>
    ${pl.estructura ? `<label>Archivos / estructura (uno por línea)</label><textarea data-f="estructura" rows="4">${esc(lines(pl.estructura))}</textarea>` : ""}
    ${pl.pruebas !== undefined ? `<label>Cómo se probará</label><input data-f="pruebas" value="${esc(pl.pruebas || "")}">` : ""}`;
}
function readPlanForm(root) {
  const o = {};
  root.querySelectorAll("[data-f]").forEach(x => { const f = x.dataset.f, v = x.value.trim(); o[f] = (f === "tareas" || f === "estructura") ? v.split("\n").map(t => t.replace(/^\s*\d+[.)-]\s*/, "").trim()).filter(Boolean) : v; });
  return o;
}
function planReview(p, r) {
  showPanel("plan"); PLAN.txt = null;
  const b = $("#planBody"); PLAN.id = p.id;
  b.innerHTML = `<h3>🧠 Plan propuesto${p.modelo ? " por " + esc(p.modelo) : ""}</h3><div class="pcount"><div class="pbar"><span></span></div><span class="ptime"></span></div>
    <div class="small">Revísalo. Si no haces nada se aprueba solo; si empiezas a editar, la cuenta se detiene hasta que pulses «Aprobar».</div>
    <div class="pform">${planForm(p.plan)}</div>
    <div class="pact"><button class="btn ok" data-a="ok">✔ Aprobar y empezar</button><button class="btn" data-a="no">✖ Descartar plan</button></div>`;
  // tarjeta también en el chat
  const card = document.createElement("div"); card.className = "plancard"; card.dataset.id = p.id;
  card.innerHTML = `<b>🧠 Plan listo (${(p.plan.tareas || []).length} tareas)</b> <span class="ptime"></span> <button class="btn" data-a="ver">Ver / editar</button> <button class="btn ok" data-a="ok">✔ Aprobar</button>`;
  r.place(card); scrollEnd(true);
  card.querySelector("[data-a=ver]").onclick = () => showPanel("plan");
  let left = p.segundos, editing = false;
  const send = async (accion, plan) => { clearInterval(PLAN.timer); await jpost(`/api/plan/${p.id}`, {accion, plan}); };
  const tick = () => {
    const txt = editing ? "✏ editando — pulsa Aprobar cuando termines" : `se aprueba solo en ${left} s`;
    $$(".ptime").forEach(x => x.textContent = txt);
    const bar = b.querySelector(".pbar span"); if (bar) bar.style.width = (editing ? 100 : (left / p.segundos) * 100) + "%";
    if (!editing && left-- <= 0) clearInterval(PLAN.timer);
  };
  clearInterval(PLAN.timer); tick(); PLAN.timer = setInterval(tick, 1000);
  b.querySelectorAll("[data-f]").forEach(x => x.addEventListener("input", () => { if (!editing) { editing = true; tick(); jpost(`/api/plan/${p.id}`, {accion: "editando"}); } }));
  const approve = () => send("aprobar", editing ? readPlanForm(b) : null);
  b.querySelector("[data-a=ok]").onclick = approve; card.querySelector("[data-a=ok]").onclick = approve;
  b.querySelector("[data-a=no]").onclick = () => send("cancelar");
}
function planDone(p) {
  clearInterval(PLAN.timer);
  $$(`.plancard[data-id="${p.id}"]`).forEach(c => c.innerHTML = `<b>✔ Plan aprobado${p.editado ? " con tus cambios" : p.auto ? " automáticamente" : ""}</b> <button class="btn" data-a="ver">Ver</button>`);
  $$(".plancard [data-a=ver]").forEach(x => x.onclick = () => showPanel("plan"));
  const b = $("#planBody"); b.querySelectorAll("textarea,input").forEach(x => x.disabled = true);
  b.querySelectorAll(".pact,.pcount").forEach(x => x.remove());
  const h = b.querySelector("h3"); if (h) h.textContent = "✔ Plan aprobado" + (p.editado ? " (editado por ti)" : "");
}

/* ───────────── Pantalla de cada proyecto (en la vista principal) ───────────── */
let HOME = null;
async function showProjectHome(name) {
  detachView(); FT.custom = null; convId = null; curProject = name; HOME = name;
  $("#side").classList.remove("open");
  await loadProjects(); await loadConvs();
  const p = PROJECTS.find(x => x.name === name); if (!p) { newChat(); return; }
  setProjectChip(name); renderTasks([]); showContinue(false);
  if (p.modelo) selectModel(p.modelo);
  const mdl = p.modelo || $("#modelSel").value || CFG.model || "";
  thread.innerHTML = `<div id="phome">
    <div class="phh"><span class="pi">${p.externo ? "📂" : TIPO_ICON[p.tipo] || "🗂"}</span><div class="pht"><h1>${esc(p.name)}</h1>
      <div class="small"><span class="plink" data-path="${esc(p.path)}">${esc(p.path)}</span> · ${esc(p.tipo || "general")}${p.externo ? " · proyecto existente en tu PC" : ""} · 🕒 ${ago(p.actividad)}</div></div></div>
    ${p.descripcion ? `<div class="phd">${esc(p.descripcion)}</div>` : ""}
    <div class="phm">🤖 IA de este proyecto: <b id="phModelName">${esc(mdl.split("::").pop())} · ${esc(mdl.split("::")[0])}</b> <button class="btn" id="phModel">Cambiar IA</button>
      <div class="small">Cada proyecto puede usar una IA distinta y todos pueden trabajar al mismo tiempo: deja uno trabajando, abre otro proyecto y sigue.</div></div>
    <div class="pha">
      <button class="btn ok" data-a="new">💬 Nuevo chat</button>${p.ultima_conv ? `<button class="btn" data-a="last">↩ Continuar último chat</button>` : ""}
      <button class="btn" data-a="files">📁 Archivos</button><button class="btn" data-a="test">🧪 Probar y corregir todo</button>
      <button class="btn" data-a="estado">📋 Estado del trabajo</button><button class="btn" data-a="folder">📂 Abrir carpeta</button><button class="btn" data-a="edit">✎ Ajustes</button></div>
    <h3>💬 Conversaciones de este proyecto</h3><div id="phConvs"></div>
    <h3>⚡ Trabajando ahora en otros proyectos</h3><div id="phOthers"></div>
    <div class="small" style="margin-top:14px">✍ Escribe abajo para empezar un chat nuevo en <b>${esc(p.name)}</b> con la IA elegida.</div></div>`;
  const q = a => thread.querySelector(`[data-a=${a}]`);
  q("new").onclick = () => { HOME = null; convId = null; thread.innerHTML = ""; showEmpty(); setProjectChip(name); $("#inp").focus(); };
  if (q("last")) q("last").onclick = () => openConv(p.ultima_conv);
  q("files").onclick = () => { FT.root = null; showPanel("files"); };
  q("test").onclick = () => { HOME = null; thread.innerHTML = ""; $("#inp").value = "Revisa todo el proyecto: ejecútalo, usa probar_proyecto, analiza los errores y corrígelos uno por uno hasta que funcione sin errores."; send(); };
  q("estado").onclick = async () => { const r = await jget(`/api/projects/${encodeURIComponent(name)}/estado`).catch(() => null); $("#preview").classList.add("show"); showPanel("view"); $("#pvName").textContent = "📋 Estado: " + name; $("#pvBody").innerHTML = `<div class="md">${md((r && r.text) || "Aún no hay trabajo registrado.")}</div>`; };
  q("folder").onclick = () => openInFolder(p.path);
  q("edit").onclick = () => editProject(p);
  $("#phModel").onclick = e => { e.stopPropagation(); $("#modelBtn").click(); };
  renderHomeConvs();
}
async function renderHomeConvs() {
  const box = $("#phConvs"), oth = $("#phOthers"); if (!box) return;
  const mine = LAST_CONVS.filter(c => c.project === HOME);
  box.innerHTML = mine.length ? "" : `<div class="small">Aún no hay chats en este proyecto.</div>`;
  mine.slice(0, 30).forEach(c => {
    const d = document.createElement("div"); d.className = "phc" + (c.running ? " running" : "");
    d.innerHTML = `${c.running ? '<span class="run"></span>' : "💬"} <span class="t">${esc(c.title || "Sin título")}</span><span class="small">${esc((c.model || "").split("::").pop())}</span><span class="small">${c.running ? "trabajando…" : ago(c.updated)}</span>`;
    d.onclick = () => openConv(c.id); box.append(d);
  });
  const others = LAST_CONVS.filter(c => c.running && c.project !== HOME);
  oth.innerHTML = others.length ? "" : `<div class="small">Ninguna otra IA está trabajando ahora.</div>`;
  others.forEach(c => { const d = document.createElement("div"); d.className = "phc running"; d.innerHTML = `<span class="run"></span> <b>${esc(c.project || "Sin proyecto")}</b> · <span class="t">${esc(c.title)}</span><span class="small">${esc((c.model || "").split("::").pop())}</span>`; d.onclick = () => openConv(c.id); oth.append(d); });
}

/* Idioma de la interfaz (automático según el sistema, o fijo) */
try { $("#langSel").value = window.getNoviqLangPref ? window.getNoviqLangPref() : "auto"; $("#langSel").onchange = () => window.setNoviqLang($("#langSel").value); } catch (e) {}

$("#apagarBtn").onclick = async () => {
  if (!confirm("¿Apagar Noviark? Las IAs que estén trabajando se detendrán.")) return;
  try { await jpost("/api/apagar"); } catch (e) {}
  document.body.innerHTML = `<div style="display:grid;place-items:center;height:100vh;color:#e8f0ec;font:18px sans-serif"><div style="text-align:center"><img src="/static/noviq_icon.png" width="96"><p>${window.T ? T("Noviark se apagó. Ya puedes cerrar esta ventana.") : "Noviark se apagó. Ya puedes cerrar esta ventana."}</p></div></div>`;
};
