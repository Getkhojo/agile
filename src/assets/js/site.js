/* Agile Tech Expert - page behaviour: scene motion, navigation, forms, portals */
(function () {
  "use strict";
  var CFG = window.ATE || {};
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var fine = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  /* ---------- Scene: dust, parallax, tilt ---------- */
  var dust = document.querySelector(".dust");
  if (dust && !reduce) {
    for (var d = 0; d < 24; d++) {
      var p = document.createElement("i");
      p.style.cssText = "--x:" + (Math.random() * 100).toFixed(1) + "%;--y:" + (30 + Math.random() * 65).toFixed(1) +
        "%;--s:" + (1.5 + Math.random() * 2.5).toFixed(1) + "px;--t:" + (6 + Math.random() * 8).toFixed(1) + "s;--dl:-" + (Math.random() * 10).toFixed(1) + "s";
      dust.appendChild(p);
    }
  }
  var root = document.documentElement;
  var tiltEls = document.querySelectorAll(".tilt");
  var phone = document.querySelector(".phone");
  if (fine && !reduce) {
    var raf = 0, nx = 0, ny = 0;
    window.addEventListener("pointermove", function (e) {
      nx = e.clientX / window.innerWidth - 0.5;
      ny = e.clientY / window.innerHeight - 0.5;
      if (raf) return;
      raf = requestAnimationFrame(function () {
        raf = 0;
        root.style.setProperty("--mx", (-nx).toFixed(3));
        root.style.setProperty("--my", (-ny).toFixed(3));
        tiltEls.forEach(function (el) {
          el.style.setProperty("--tx", (nx * 7).toFixed(2));
          el.style.setProperty("--ty", (ny * -6).toFixed(2));
        });
        if (phone) {
          phone.style.setProperty("--tx", (nx * 18).toFixed(2));
          phone.style.setProperty("--ty", (ny * -12).toFixed(2));
        }
      });
    }, { passive: true });
    document.querySelectorAll(".tcard").forEach(function (f) {
      f.addEventListener("pointermove", function (e) {
        var r = f.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
        f.style.setProperty("--tx", ((x - 0.5) * 14).toFixed(2));
        f.style.setProperty("--ty", ((0.5 - y) * 14).toFixed(2));
        f.style.setProperty("--gx", (x * 100).toFixed(0) + "%");
        f.style.setProperty("--gy", (y * 100).toFixed(0) + "%");
      });
      f.addEventListener("pointerleave", function () { f.style.setProperty("--tx", 0); f.style.setProperty("--ty", 0); });
    });
  }

  /* ---------- Waveforms ---------- */
  var waves = [];
  document.querySelectorAll("[data-wave]").forEach(function (w) {
    var n = parseInt(w.getAttribute("data-wave"), 10);
    if (w.classList.contains("wave") && window.innerWidth < 520) n = 46;
    var bars = [];
    for (var i = 0; i < n; i++) { var b = document.createElement("i"); w.appendChild(b); bars.push(b); }
    waves.push({ bars: bars, big: w.classList.contains("wave") });
  });
  var waveT = 0;
  window.ATE_VOICE_ACTIVE = false;
  function waveFrame() {
    waveT += 0.06;
    var amp = window.ATE_VOICE_ACTIVE ? 1 : 0.55;
    waves.forEach(function (w) {
      var n = w.bars.length;
      for (var i = 0; i < n; i++) {
        var env = Math.sin(Math.PI * i / n);
        var v = Math.abs(Math.sin(i * 0.55 + waveT) * 0.6 + Math.sin(i * 0.21 - waveT * 1.7) * 0.4) * env;
        var h = w.big ? 6 + v * 90 * amp * ((i % 9 === 4) ? 1.6 : 1) : 3 + v * 26;
        w.bars[i].style.setProperty("--h", h.toFixed(1) + "px");
      }
    });
    if (!reduce) setTimeout(function () { requestAnimationFrame(waveFrame); }, 70);
  }
  if (waves.length) waveFrame();

  /* ---------- Navigation ---------- */
  var dd = document.querySelector(".dd");
  var mega = document.getElementById("mega");
  if (dd && mega) {
    dd.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = dd.getAttribute("aria-expanded") === "true";
      dd.setAttribute("aria-expanded", String(!open));
      mega.hidden = open;
    });
    document.addEventListener("click", function (e) {
      if (!mega.hidden && !mega.contains(e.target)) { mega.hidden = true; dd.setAttribute("aria-expanded", "false"); }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !mega.hidden) { mega.hidden = true; dd.setAttribute("aria-expanded", "false"); dd.focus(); }
    });
  }
  var burger = document.querySelector(".burger");
  var drawer = document.getElementById("drawer");
  if (burger && drawer) {
    burger.addEventListener("click", function () {
      drawer.hidden = !drawer.hidden;
      burger.setAttribute("aria-expanded", String(!drawer.hidden));
    });
  }

  /* ---------- Gallery filters ---------- */
  var filters = document.querySelector(".filters");
  if (filters) {
    filters.addEventListener("click", function (e) {
      var b = e.target.closest("button");
      if (!b) return;
      filters.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
      var cat = b.getAttribute("data-cat");
      document.querySelectorAll(".shot").forEach(function (s) {
        s.hidden = cat !== "all" && s.getAttribute("data-cat") !== cat;
      });
    });
  }

  /* ---------- Helpers shared with chat.js ---------- */
  function api(path, body) {
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 12000) : 0;
    return fetch((CFG.apiBase || "/api") + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body),
      signal: ctrl ? ctrl.signal : undefined
    }).then(function (r) {
      clearTimeout(timer);
      return r.json().catch(function () { return {}; }).then(function (data) { return { ok: r.ok, status: r.status, data: data }; });
    }, function () {
      clearTimeout(timer);
      return { ok: false, status: 0, data: {} };
    });
  }
  function waLink(text) {
    return "https://wa.me/" + (CFG.whatsapp || "") + "?text=" + encodeURIComponent(text);
  }
  function leadText(d) {
    return "New inquiry from agiletechexpert.com\nName: " + (d.name || "") + "\nPhone: " + (d.phone || "") +
      (d.email ? "\nEmail: " + d.email : "") + (d.company ? "\nCompany: " + d.company : "") +
      (d.service ? "\nService: " + d.service : "") + (d.mode ? "\nSetup: " + d.mode : "") + (d.message ? "\nMessage: " + d.message : "");
  }
  function validPhone(v) { return /^[+0-9][0-9\s-]{8,15}$/.test((v || "").trim()); }
  window.ATE_API = { post: api, waLink: waLink, leadText: leadText, validPhone: validPhone };

  /* ---------- Inquiry form ---------- */
  document.querySelectorAll("form[data-lead]").forEach(function (form) {
    var status = form.querySelector(".status");
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var fd = new FormData(form), d = {};
      fd.forEach(function (v, k) { d[k] = String(v).trim(); });
      if (d.website) return; /* honeypot */
      status.hidden = false;
      status.className = "status";
      if (!d.name || !validPhone(d.phone)) {
        status.classList.add("err");
        status.textContent = "Please enter your name and a valid phone number so we can reach you.";
        return;
      }
      d.source = "contact-form";
      d.page = location.pathname;
      var btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      status.textContent = "Sending...";
      api("/leads", d).then(function (res) {
        btn.disabled = false;
        if (res.ok) {
          status.classList.add("ok");
          status.textContent = "Thanks, " + d.name.split(" ")[0] + ". Your inquiry is with our team and we'll call you back shortly.";
          form.reset();
        } else {
          status.classList.add("err");
          status.innerHTML = "";
          status.appendChild(document.createTextNode("We couldn't reach our server just now. "));
          var a = document.createElement("a");
          a.href = waLink(leadText(d)); a.target = "_blank"; a.rel = "noopener";
          a.textContent = "Send the same details on WhatsApp";
          status.appendChild(a);
        }
      });
    });
  });

  /* ---------- Portal login ---------- */
  document.querySelectorAll("form[data-auth]").forEach(function (form) {
    var status = form.querySelector(".status");
    var who = form.getAttribute("data-auth");
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var fd = new FormData(form), d = {};
      fd.forEach(function (v, k) { d[k] = String(v).trim(); });
      status.hidden = false;
      status.className = "status err";
      if (!d.username || !d.password) { status.textContent = "Enter your ID and password."; return; }
      var btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      status.className = "status";
      status.textContent = "Signing in...";
      api("/auth/" + who + "/login", { username: d.username, password: d.password, remember: d.remember === "on" }).then(function (res) {
        btn.disabled = false;
        if (res.ok && res.data && res.data.redirect) { location.href = res.data.redirect; return; }
        status.className = "status err";
        if (res.status === 401 || res.status === 403) status.textContent = "That ID and password don't match. Try again or contact your administrator.";
        else if (res.status === 429) status.textContent = "Too many attempts. Wait a few minutes and try again.";
        else status.textContent = "The login service isn't available right now. Please try again later.";
      });
    });
  });

  /* ---------- Hero voice controls hand off to the assistant ---------- */
  document.querySelectorAll("[data-voice]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (b.getAttribute("data-voice") === "hero" && window.ATE_HERO) { window.ATE_HERO.start(); return; }
      if (window.ATE_CHAT) window.ATE_CHAT.open({ voice: true });
    });
  });
  document.querySelectorAll("[data-chat]").forEach(function (b) {
    b.addEventListener("click", function (e) {
      e.preventDefault();
      if (window.ATE_CHAT) window.ATE_CHAT.open({ topic: b.getAttribute("data-chat"), service: b.getAttribute("data-service") || "" });
    });
  });

  var y = document.getElementById("year");
  if (y) y.textContent = new Date().getFullYear();
})();
