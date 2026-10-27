/* FileForge — démo de la roue + téléchargements selon le système */
(() => {
  "use strict";
  const DATA = window.FF_DATA || { demo: {}, icons: {} };
  const C = 380, NS = "http://www.w3.org/2000/svg";
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const icon = (name, size) => {
    const body = DATA.icons[name];
    return body ? `<svg viewBox="0 0 24 24" width="${size || 20}" height="${size || 20}" aria-hidden="true">${body}</svg>` : "";
  };
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  document.querySelectorAll("[data-icon]").forEach(el => el.insertAdjacentHTML("afterbegin", icon(el.dataset.icon, 22)));

  /* ───────── géométrie ───────── */
  const pt = (r, a) => { const t = (a - 90) * Math.PI / 180; return [C + r * Math.cos(t), C + r * Math.sin(t)]; };
  const sector = (r0, r1, a0, a1) => {
    const L = a1 - a0 > 180 ? 1 : 0, [x0, y0] = pt(r1, a0), [x1, y1] = pt(r1, a1), [x2, y2] = pt(r0, a1), [x3, y3] = pt(r0, a0);
    return `M${x0} ${y0}A${r1} ${r1} 0 ${L} 1 ${x1} ${y1}L${x2} ${y2}A${r0} ${r0} 0 ${L} 0 ${x3} ${y3}Z`;
  };
  const annulus = (r0, r1) => `M${C} ${C - r1}A${r1} ${r1} 0 1 1 ${C - .01} ${C - r1}Z M${C} ${C - r0}A${r0} ${r0} 0 1 0 ${C - .01} ${C - r0}Z`;

  /* ───────── scène (760×760, mise à l'échelle) ───────── */
  const frame = document.getElementById("wheel-frame"), stage = document.getElementById("stage");
  // on cadre le disque utile (rayon ~320) plutôt que toute la scène de 760 px
  const fit = () => { const s = frame.clientWidth / 640; stage.style.transform = `translate(${-60 * s}px, ${-60 * s}px) scale(${s})`; };
  new ResizeObserver(fit).observe(frame); fit();

  const enter = (el, delay) => {
    el.classList.add("pre");
    if (reduce) { el.classList.remove("pre"); return; }
    setTimeout(() => requestAnimationFrame(() => requestAnimationFrame(() => el.classList.remove("pre"))), delay || 0);
  };
  const leave = el => { if (!el) return; el.classList.add("out"); setTimeout(() => el.remove(), 180); };
  let hubEl = null, catRing = null, fanRing = null, extra = [];

  function ring(cls, items, o) {
    const L = document.createElement("div");
    L.className = "ring " + (cls || "");
    L.innerHTML = '<svg viewBox="0 0 760 760" width="760" height="760"></svg>';
    const svg = L.firstChild, n = items.length, w = o.span / n, g = o.gap ?? 1.4;
    items.forEach((it, i) => {
      const a0 = o.start + i * w, a1 = a0 + w, full = n === 1 && o.span >= 359;
      const p = document.createElementNS(NS, "path");
      p.setAttribute("d", full ? annulus(o.r0, o.r1) : sector(o.r0, o.r1, a0 + g / 2, a1 - g / 2));
      p.setAttribute("fill-rule", "evenodd");
      p.setAttribute("class", "seg");
      p.setAttribute("tabindex", "0");
      p.setAttribute("role", "button");
      p.setAttribute("aria-label", it.aria || it.label);
      p.style.setProperty("--c", it.color);
      p.addEventListener("mouseenter", () => o.hover && o.hover(i, it));
      p.addEventListener("focus", () => o.hover && o.hover(i, it));
      p.addEventListener("click", e => { e.stopPropagation(); o.click && o.click(i, it); });
      p.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); o.click && o.click(i, it); } });
      svg.appendChild(p); it._p = p;
      const mid = (a0 + a1) / 2, rm = (o.r0 + o.r1) / 2, [x, y] = full ? [C, C - rm] : pt(rm, mid);
      const mw = Math.max(58, Math.min(o.maxw || 120, Math.min(w, 180) * Math.PI / 180 * rm * .8));
      const lb = document.createElement("div");
      lb.className = "lbl";
      lb.style.cssText = `left:${x}px;top:${y}px;width:${mw}px`;
      lb.style.setProperty("--c", it.color);
      lb.innerHTML = (it.icon ? icon(it.icon, 21) : "") + `<span>${esc(it.label)}</span>`;
      L.appendChild(lb); it._l = lb;
    });
    stage.appendChild(L); enter(L, o.delay);
    return L;
  }
  const setOn = (items, idx) => items.forEach((it, j) => { it._p.classList.toggle("on", j === idx); it._l.classList.toggle("on", j === idx); });
  function hub(r, html, delay) {
    if (hubEl) hubEl.remove();
    const h = document.createElement("div");
    h.className = "hub";
    h.style.cssText = `left:${C - r}px;top:${C - r}px;width:${2 * r}px;height:${2 * r}px`;
    h.innerHTML = html;
    stage.appendChild(h); enter(h, delay); hubEl = h;
    return h;
  }
  const clear = () => { stage.innerHTML = ""; hubEl = catRing = fanRing = null; extra = []; };

  /* ───────── résultats simulés ───────── */
  const RESULT = {
    pdf_to_word: f => [f.stem + ".docx"], pdf_to_excel: f => [f.stem + ".xlsx"], pdf_to_pptx: f => [f.stem + ".pptx"],
    pdf_to_text: f => [f.stem + ".md"], pdf_to_images: f => [f.stem + "_images", "12 images, une par page"],
    pdf_compress: f => [f.stem + "_compressé.pdf", "4,8 Mo → 1,2 Mo (−75 %)"], pdf_split: f => [f.stem + "_divisé", "12 PDF d'une page"],
    pdf_sign: f => [f.stem + "_signé.pdf"], pdf_protect: f => [f.stem + "_protégé.pdf", "Chiffrement AES-256"],
    pdf_ocr: f => [f.stem + "_ocr.pdf", "Le texte est maintenant cherchable"], pdf_redact: f => [f.stem + "_caviardé.pdf", "3 zones masquées définitivement"],
    pdf_extract_images: f => [f.stem + "_images_extraites", "7 images extraites"], make_zip: f => [f.name + ".zip"],
    img_convert: f => [f.stem + ".jpg"], img_compress: f => [f.stem + "_compressé.heic", "3,1 Mo → 0,9 Mo (−71 %)"],
    img_to_pdf: f => [f.stem + ".pdf"], img_strip: f => [f.stem + "_sans-meta.heic", "Position GPS et appareil retirés"],
    img_resize: f => [f.stem + "_2016x1512.heic"], vid_mp4: f => [f.stem + ".mp4"], vid_gif: f => [f.stem + "_anim.gif"],
    vid_audio: f => [f.stem + ".mp3"], vid_compress: f => [f.stem + "_compressé.mp4", "182 Mo → 24 Mo (−87 %)"],
    vid_frame: f => [f.stem + "_image_12s.jpg"], vid_trim: f => [f.stem + "_extrait.mp4"],
    doc_to_pdf: f => [f.stem + ".pdf"], tab_convert: f => [f.stem + ".csv"], office_convert: f => [f.stem + ".ods"],
  };
  const OPTIONS = {
    pdf_compress: ["Légère", "Recommandée", "Forte"],
    img_convert: ["JPG", "PNG", "WEBP", "AVIF", "TIFF", "GIF"],
    vid_compress: ["Légère", "Recommandée (1080p)", "Forte (720p, mail)"],
    tab_convert: ["Excel (.xlsx)", "CSV", "JSON"],
  };
  const resultFor = (a, file) => {
    const f = { name: file, stem: file.replace(/\.[^.]+$/, ""), ext: file.split(".").pop() };
    return (RESULT[a.id] || (() => [`${f.stem}_${a.label.toLowerCase().split(" ")[0]}.${f.ext}`]))(f);
  };

  /* ───────── états de la roue ───────── */
  const hint = document.getElementById("hint");
  let current = Object.keys(DATA.demo)[0], timer = null, cur = -1, fanItems = [];

  function hubInfo(st) {
    return `<div class="badge" style="--c:${st.color}">${esc(st.badge)}</div><div class="name">${esc(current)}</div><div class="sub">${st.cats.reduce((n, c) => n + c.actions.length, 0)} actions possibles</div>`;
  }
  function showMain(first) {
    clearTimeout(timer); clear(); cur = -1;
    const st = DATA.demo[current], n = st.cats.length, w = 360 / n;
    const items = st.cats.map(c => ({ label: c.label, icon: c.icon, color: c.color, aria: `Catégorie ${c.label}` }));
    catRing = ring("cats", items, { r0: 98, r1: 178, start: -w / 2, span: 360, gap: 1.6, maxw: 96, delay: first ? 120 : 0,
      hover: i => openCat(i, items), click: i => openCat(i, items) });
    hub(92, hubInfo(st), first ? 0 : 0);
    hint.textContent = "Survole une catégorie, puis choisis une action.";
    if (n === 1) openCat(0, items);
  }
  function openCat(i, items) {
    if (cur === i && fanRing) return;
    cur = i; setOn(items, i);
    const st = DATA.demo[current], cat = st.cats[i], k = cat.actions.length, w0 = 360 / st.cats.length;
    let w = Math.min(46, Math.max(30, 300 / k)), span = k * w;
    if (span > 352) { w = 352 / k; span = 352; }
    leave(fanRing);
    fanItems = cat.actions.map(a => ({ ...a, color: cat.color, aria: a.full }));
    fanRing = ring("fan", fanItems, { r0: 186, r1: 306, start: i * w0 - span / 2, span, gap: 1.2, maxw: 112,
      hover: (j, it) => { setOn(fanItems, j); hubAction(it); }, click: (j, it) => pick(it) });
    hubEl.innerHTML = hubInfo(st);
  }
  function hubAction(it) {
    hubEl.innerHTML = `<div class="big" style="--c:${it.color}">${icon(it.icon, 32)}</div><div class="title">${esc(it.full)}</div><div class="note">clic pour essayer</div>`;
  }
  function pick(a) {
    if (OPTIONS[a.id]) return showChoice(a);
    run(a);
  }
  function showChoice(a) {
    clear();
    const opts = OPTIONS[a.id], n = opts.length, w = 360 / n;
    const items = opts.map(o => ({ label: o, color: a.color, aria: o }));
    ring("", items, { r0: 124, r1: n > 4 ? 270 : 246, start: -w / 2, span: 360, gap: 1.5, maxw: 120,
      hover: i => setOn(items, i), click: () => run(a) });
    hub(114, `<div class="title">${esc(a.full)}</div><div class="note">Les options s'affichent aussi en roue</div>`);
    hint.textContent = "Choisis une option.";
  }
  function run(a) {
    clear();
    const s = document.createElement("div");
    s.className = "spin"; s.style.cssText = `left:${C - 122}px;top:${C - 122}px;width:244px;height:244px`;
    stage.appendChild(s);
    hub(108, `<div class="big" style="--c:#a78bfa">${icon(a.icon, 28)}</div><div class="title">${esc(a.full)}…</div>`);
    hint.textContent = "Traitement…";
    timer = setTimeout(() => done(a), reduce ? 300 : 900);
  }
  function done(a) {
    clear();
    const [out, note] = resultFor(a, current);
    const items = [{ label: "Ouvrir", icon: "circle-check", color: "#22c55e" }, { label: "Enchaîner", icon: "repeat", color: "#22c55e" },
                   { label: "Retour", icon: "undo-2", color: "#475569" }];
    ring("", items, { r0: 136, r1: 226, start: -60, span: 360, gap: 1.5, maxw: 96, hover: i => setOn(items, i), click: () => showMain() });
    const ck = icon("circle-check", 34).replace("<svg", '<svg class="check"');
    hub(128, `<div class="big" style="--c:#22c55e">${ck}</div><div class="title">Terminé</div><div class="out">${esc(out)}</div>${note ? `<div class="note">${esc(note)}</div>` : ""}`);
    hint.textContent = "Le résultat est créé à côté de l'original, qui reste intact.";
    timer = setTimeout(() => showMain(), 5200);
  }

  /* sélecteur de fichier d'exemple */
  const picker = document.getElementById("file-picker");
  Object.entries(DATA.demo).forEach(([name, st], i) => {
    const b = document.createElement("button");
    b.type = "button"; b.setAttribute("role", "radio"); b.textContent = name;
    b.style.setProperty("--c", st.color);
    b.setAttribute("aria-checked", i === 0 ? "true" : "false");
    b.addEventListener("click", () => {
      current = name;
      picker.querySelectorAll("button").forEach(x => x.setAttribute("aria-checked", x === b ? "true" : "false"));
      showMain(true);
    });
    picker.appendChild(b);
  });
  stage.addEventListener("click", e => { if (e.target === stage) showMain(); });
  showMain(true);

  /* ───────── système et téléchargements ───────── */
  const NAMES = { macos: "macOS", windows: "Windows", linux: "Linux" };
  function detectOS() {
    const p = ((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "").toLowerCase();
    const ua = navigator.userAgent.toLowerCase();
    if (/iphone|ipad|android/.test(ua)) return null;
    if (p.includes("mac") || ua.includes("mac os")) return "macos";
    if (p.includes("win") || ua.includes("windows")) return "windows";
    if (p.includes("linux") || ua.includes("linux") || ua.includes("x11")) return "linux";
    return null;
  }
  const human = b => b < 1024 * 1024 ? `${Math.round(b / 1024)} Ko` : `${(b / 1048576).toFixed(1).replace(".", ",")} Mo`;
  const os = detectOS();
  const heroBtn = document.getElementById("hero-dl"), heroMeta = document.getElementById("hero-meta");
  if (os) {
    const card = document.querySelector(`.os[data-os="${os}"]`);
    card.classList.add("mine");
    card.querySelector(".yours").hidden = false;
    heroBtn.innerHTML = icon("download", 19) + `Télécharger pour ${NAMES[os]}`;
    heroBtn.href = card.querySelector(".btn").getAttribute("href");
    heroBtn.setAttribute("download", "");
    document.getElementById("hero-other").textContent = "Autres systèmes";
  } else {
    heroBtn.innerHTML = icon("download", 19) + "Choisir mon système";
    document.getElementById("hero-other").hidden = true;
    document.getElementById("dl-lead").textContent =
      "FileForge s'installe sur un ordinateur (macOS, Windows ou Linux). Ouvre cette page depuis ton ordinateur pour télécharger la bonne version.";
  }
  document.querySelectorAll(".os .btn").forEach(b => b.insertAdjacentHTML("afterbegin", icon("download", 19)));

  fetch("downloads/manifest.json", { cache: "no-cache" }).then(r => r.ok ? r.json() : null).then(m => {
    if (!m) return;
    document.getElementById("version").textContent = `FileForge ${m.version}`;
    const sums = document.getElementById("sums");
    sums.innerHTML = "";
    for (const [k, f] of Object.entries(m.files)) {
      const meta = document.querySelector(`[data-meta="${k}"]`);
      if (meta) meta.textContent = `${f.name}, ${human(f.bytes)}, version ${m.version}`;
      sums.insertAdjacentHTML("beforeend", `<dt>${esc(f.name)}</dt><dd>${esc(f.sha256)}</dd>`);
    }
    if (os && m.files[os]) heroMeta.textContent = `Version ${m.version}, ${human(m.files[os].bytes)}. Aussi pour ${Object.keys(NAMES).filter(k => k !== os).map(k => NAMES[k]).join(" et ")}.`;
  }).catch(() => {});
})();
