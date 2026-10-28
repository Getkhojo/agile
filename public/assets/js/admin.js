/* Agile Tech Expert - staff/admin portal (vanilla JS, talks to /api/admin/*) */
(function () {
  "use strict";
  var API = (window.ATE && window.ATE.apiBase) || "/api";
  var ROOT = window.ATE_ROOT || "/";
  var LOGIN = ROOT + "portal/employee/";
  var app = document.getElementById("adm");
  if (!app) return;
  document.body.classList.add("portal-app");
  var main = app.querySelector(".adm-main"), nav = app.querySelector(".adm-nav");
  var ME = null, CLIENTS = [];

  var TABS = [
    { id: "overview", label: "Overview", staff: true },
    { id: "leads", label: "Leads", staff: true },
    { id: "conversations", label: "AI conversations", staff: true },
    { id: "usage", label: "AI usage & cost", admin: true },
    { id: "users", label: "Users & accounts", admin: true },
    { id: "billing", label: "Billing", admin: true },
    { id: "activity", label: "Activity log", admin: true }
  ];

  // ---------- helpers
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function inr(n) { return "₹" + Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function num(n) { return Number(n || 0).toLocaleString("en-IN"); }
  function when(s) {
    if (!s) return "";
    var d = new Date(s); if (isNaN(d)) return esc(s);
    return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  }
  function day(s) { var d = new Date(s); return isNaN(d) ? esc(s) : d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }); }
  function call(method, path, body) {
    return fetch(API + path, {
      method: method, credentials: "include",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) {
      if (r.status === 401) { location.replace(LOGIN); throw new Error("signed out"); }
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(d.detail || ("Server error " + r.status));
        return d;
      });
    });
  }
  function get(p) { return call("GET", p); }
  function say(el, ok, text) { if (!el) return; el.className = "msg " + (ok ? "ok" : "err"); el.textContent = text; }
  function formData(form) {
    var o = {};
    Array.prototype.forEach.call(form.elements, function (f) { if (f.name) o[f.name] = f.type === "number" ? (f.value === "" ? null : Number(f.value)) : f.value.trim(); });
    return o;
  }
  function head(title, sub) { return "<h2>" + esc(title) + "</h2>" + (sub ? '<p class="adm-sub">' + sub + "</p>" : ""); }
  function kpi(label, value, extra, cls) { return '<div class="kpi ' + (cls || "") + '"><small>' + esc(label) + "</small><b>" + value + "</b>" + (extra ? "<em>" + extra + "</em>" : "") + "</div>"; }
  function loading() { main.innerHTML = '<p class="empty">Loading…</p>'; }
  function fail(e) { main.innerHTML = '<p class="empty">Could not load: ' + esc(e.message) + "</p>"; }

  // ---------- shell
  function buildNav() {
    var isAdmin = ME.role === "admin";
    var h = '<div class="adm-me"><b>' + esc(ME.name || ME.username) + "</b><small>" + esc(isAdmin ? "Admin" : "Staff") + "</small></div>";
    TABS.forEach(function (t) {
      if (t.admin && !isAdmin) return;
      h += '<button type="button" data-tab="' + t.id + '">' + esc(t.label) + (t.id === "conversations" ? '<span class="badge" id="offBadge" hidden></span>' : "") + "</button>";
    });
    h += '<span class="sp"></span><button type="button" id="admOut">Log out</button>';
    nav.innerHTML = h;
    nav.addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      if (b.id === "admOut") { call("POST", "/auth/logout").then(go, go); return; }
      location.hash = b.getAttribute("data-tab");
    });
    function go() { location.replace(LOGIN); }
  }
  function route() {
    var id = (location.hash || "#overview").slice(1);
    var t = TABS.filter(function (x) { return x.id === id && (!x.admin || ME.role === "admin"); })[0] || TABS[0];
    nav.querySelectorAll("button[data-tab]").forEach(function (b) { b.setAttribute("aria-current", b.getAttribute("data-tab") === t.id ? "page" : "false"); });
    main.onclick = main.onchange = main.onkeydown = null;
    VIEWS[t.id]();
    main.focus({ preventScroll: true });
  }

  // ---------- views
  var VIEWS = {};

  VIEWS.overview = function () {
    loading();
    get("/admin/overview").then(function (d) {
      var badge = document.getElementById("offBadge");
      if (badge) { badge.hidden = !d.offtopic_unreviewed; badge.textContent = d.offtopic_unreviewed; }
      var h = head("Overview", "Today at a glance.") + '<div class="kpis">' +
        kpi("New leads", num(d.leads_new), num(d.leads_today) + " today · " + num(d.leads_total) + " total", d.leads_new ? "warn" : "") +
        kpi("AI conversations today", num(d.conversations_today)) +
        kpi("Possibly off-topic", num(d.offtopic_unreviewed), "not reviewed yet", d.offtopic_unreviewed ? "warn" : "") +
        kpi("Answers marked bad", num(d.bad_answers), "", d.bad_answers ? "warn" : "");
      if (d.ai_month) {
        var m = d.ai_month, t = d.ai_today;
        h += kpi("Voice minutes this month", num(m.voice_minutes), num(m.voice_calls) + " calls · today " + num(t.voice_minutes) + " min") +
          kpi("Chat requests this month", num(m.chat_requests), "today " + num(t.chat_requests)) +
          kpi("AI cost this month (est.)", inr(m.estimated_inr), d.ai_billing === "free" ? "billed now " + inr(m.billed_inr) + " · free tier" : "billed " + inr(m.billed_inr)) +
          kpi("Active clients", num(d.clients), num(d.employees) + " staff accounts") +
          kpi("Unpaid invoices", inr(d.invoices_unpaid_inr), num(d.invoices_unpaid) + " invoices", d.invoices_unpaid ? "warn" : "") +
          kpi("Collected this month", inr(d.paid_this_month_inr), "", "good");
      }
      main.innerHTML = h + "</div>";
    }).catch(fail);
  };

  VIEWS.leads = function () {
    loading();
    get("/leads").then(function (d) {
      var rows = d.leads || [];
      var statuses = ["new", "contacted", "qualified", "won", "lost"];
      main.innerHTML = head("Leads", "Inquiries from the website form, chat and voice. Change the status as you follow up.") +
        '<div class="bar"><input type="search" id="lq" placeholder="Search name, phone, service, message">' +
        '<select id="ls"><option value="">All statuses</option>' + statuses.map(function (s) { return '<option>' + s + "</option>"; }).join("") + "</select>" +
        '<button class="abtn g" id="lcsv" type="button">Download CSV</button><span class="muted2" id="lcount"></span></div>' +
        '<div class="tblw"><table class="tbl" id="lt"></table></div><p class="msg" id="lmsg"></p>';
      function draw() {
        var q = document.getElementById("lq").value.toLowerCase(), s = document.getElementById("ls").value;
        var list = rows.filter(function (x) {
          return (!s || x.status === s) && (!q || [x.name, x.phone, x.service, x.message, x.company, x.email].join(" ").toLowerCase().indexOf(q) >= 0);
        });
        document.getElementById("lcount").textContent = list.length + " of " + rows.length;
        var h = "<thead><tr><th>When</th><th>Name</th><th>Phone</th><th>Service</th><th>Source</th><th>Message</th><th>Status</th><th>Notes</th></tr></thead><tbody>";
        if (!list.length) h += '<tr><td colspan="8" class="empty">No leads.</td></tr>';
        list.forEach(function (x) {
          h += "<tr><td>" + when(x.created_at) + "</td><td>" + esc(x.name) + (x.company ? '<br><span class="muted2">' + esc(x.company) + "</span>" : "") +
            '</td><td><a href="tel:' + esc(x.phone) + '">' + esc(x.phone) + "</a></td><td>" + esc(x.service) + (x.mode ? '<br><span class="muted2">' + esc(x.mode) + "</span>" : "") +
            "</td><td>" + esc(x.source) + "</td><td>" + esc(x.message) + '</td><td><select data-lead="' + x.id + '">' +
            statuses.map(function (s2) { return "<option" + (s2 === x.status ? " selected" : "") + ">" + s2 + "</option>"; }).join("") +
            '</select></td><td><input data-note="' + x.id + '" value="' + esc(x.notes || "") + '" placeholder="add note"></td></tr>';
        });
        document.getElementById("lt").innerHTML = h + "</tbody>";
      }
      draw();
      document.getElementById("lq").addEventListener("input", draw);
      document.getElementById("ls").addEventListener("change", draw);
      var lt = document.getElementById("lt"), lm = document.getElementById("lmsg");
      lt.addEventListener("change", function (e) {
        var id = e.target.getAttribute("data-lead") || e.target.getAttribute("data-note"); if (!id) return;
        var body = e.target.hasAttribute("data-lead") ? { status: e.target.value } : { notes: e.target.value };
        call("PATCH", "/admin/leads/" + id, body).then(function () {
          rows.forEach(function (r) { if (String(r.id) === id) { if (body.status) r.status = body.status; if (body.notes != null) r.notes = body.notes; } });
          say(lm, true, "Saved.");
        }).catch(function (er) { say(lm, false, er.message); });
      });
      document.getElementById("lcsv").addEventListener("click", function () {
        fetch(API + "/leads.csv", { credentials: "include" }).then(function (r) { return r.text(); }).then(function (t) {
          var a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([t], { type: "text/csv" })); a.download = "agile-leads.csv";
          document.body.appendChild(a); a.click(); a.remove();
        });
      });
    }).catch(fail);
  };

  VIEWS.conversations = function () {
    main.innerHTML = head("AI conversations", "Every website chat and voice call, word for word. Check that visitors ask relevant things and that the AI answers well.") +
      '<div class="bar"><select id="ck"><option value="">Chat + voice</option><option value="voice">Voice calls</option><option value="chat">Chat</option></select>' +
      '<select id="cf"><option value="">All</option><option value="offtopic">Possibly off-topic</option><option value="unreviewed">Not reviewed</option><option value="bad">Marked bad</option><option value="good">Marked good</option></select>' +
      '<input type="search" id="cq" placeholder="Search words in the conversation"><button class="abtn g" id="cgo" type="button">Search</button></div>' +
      '<div class="tblw"><table class="tbl" id="ct"></table></div><div class="bar" style="margin-top:10px"><button class="abtn g sm" id="cprev" type="button">Previous</button><button class="abtn g sm" id="cnext" type="button">Next</button><span class="muted2" id="cpage"></span></div>';
    var off = 0, LIM = 50;
    function load() {
      var q = "?limit=" + LIM + "&offset=" + off + "&kind=" + document.getElementById("ck").value + "&flag=" + document.getElementById("cf").value + "&q=" + encodeURIComponent(document.getElementById("cq").value);
      document.getElementById("ct").innerHTML = '<tr><td class="empty">Loading…</td></tr>';
      get("/admin/conversations" + q).then(function (d) {
        var h = "<thead><tr><th>When</th><th>Type</th><th>First question</th><th>Turns</th><th>Flags</th><th>Review</th></tr></thead><tbody>";
        if (!d.items.length) h += '<tr><td colspan="6" class="empty">No conversations match.</td></tr>';
        d.items.forEach(function (c) {
          h += '<tr class="click" data-conv="' + c.id + '"><td>' + when(c.started_at) + "</td><td>" +
            (c.kind === "voice" ? '<span class="pill voice">Voice' + (c.seconds ? " · " + Math.round(c.seconds) + "s" : "") + "</span>" : '<span class="pill">Chat</span>') +
            "</td><td>" + esc((c.first_q || "(visitor did not speak)").slice(0, 110)) + '</td><td class="num">' + c.turns + "</td><td>" +
            (c.offtopic ? '<span class="pill warn">Off-topic?</span>' : "") + "</td><td>" +
            (c.rating === "good" ? '<span class="pill good">Good</span>' : c.rating === "bad" ? '<span class="pill bad">Bad</span>' : '<span class="pill off">—</span>') + "</td></tr>";
        });
        document.getElementById("ct").innerHTML = h + "</tbody>";
        document.getElementById("cpage").textContent = (d.total ? (off + 1) + "–" + Math.min(off + LIM, d.total) : 0) + " of " + d.total;
        document.getElementById("cprev").disabled = off === 0;
        document.getElementById("cnext").disabled = off + LIM >= d.total;
      }).catch(fail);
    }
    ["ck", "cf"].forEach(function (id) { document.getElementById(id).addEventListener("change", function () { off = 0; load(); }); });
    document.getElementById("cgo").addEventListener("click", function () { off = 0; load(); });
    document.getElementById("cq").addEventListener("keydown", function (e) { if (e.key === "Enter") { off = 0; load(); } });
    document.getElementById("cprev").addEventListener("click", function () { off = Math.max(0, off - LIM); load(); });
    document.getElementById("cnext").addEventListener("click", function () { off += LIM; load(); });
    document.getElementById("ct").addEventListener("click", function (e) {
      var tr = e.target.closest("tr[data-conv]"); if (tr) openConv(tr.getAttribute("data-conv"), load);
    });
    load();
  };

  var drawer = document.getElementById("convDrawer");
  if (drawer) document.body.appendChild(drawer);   // escape transformed parents so it covers the whole screen
  function openConv(id, after) {
    drawer.hidden = false;
    var box = drawer.querySelector(".cdrawer-in");
    box.innerHTML = '<p class="empty">Loading…</p>';
    get("/admin/conversations/" + id).then(function (d) {
      var c = d.conversation, h = '<div class="cdrawer-top"><div><b>' + (c.kind === "voice" ? "Voice call" : "Chat") + " #" + c.id + '</b><br><span class="muted2">' +
        when(c.started_at) + (c.gender ? " · " + esc(c.gender) + " voice" : "") + (d.voice ? " · " + Math.round(d.voice.seconds || 0) + "s · ended: " + esc(d.voice.end_reason) + (d.voice.lang ? " · language: " + esc(d.voice.lang) : "") : "") +
        (c.page ? " · " + esc(c.page) : "") + '</span></div><button class="abtn g" type="button" data-close>Close</button></div>';
      if (c.offtopic) h += '<div class="note">Flagged as possibly off-topic: none of the visitor\'s words matched Agile\'s services. Please check.</div>';
      h += '<div class="chatlog">';
      d.turns.forEach(function (t) {
        h += '<div class="bub ' + (t.role === "you" ? "you" : "agile") + '">' + esc(t.text) + "<small>" + (t.role === "you" ? "Visitor" : "Agile") +
          (t.provider ? " · " + esc(t.provider) : "") + (t.in_tok ? " · " + num(t.in_tok) + "/" + num(t.out_tok) + " tokens" : "") + "</small></div>";
      });
      h += '</div><div class="card"><h3>Was the AI\'s answer good?</h3><div class="bar">' +
        '<button class="abtn ' + (c.rating === "good" ? "" : "g") + '" data-rate="good" type="button">👍 Good</button>' +
        '<button class="abtn ' + (c.rating === "bad" ? "r" : "g") + '" data-rate="bad" type="button">👎 Bad</button>' +
        '<button class="abtn g" data-rate="" type="button">Clear</button></div>' +
        '<input id="rnote" style="width:100%;font:inherit;font-size:13px;padding:8px 10px;border:1px solid #cfe1df;border-radius:9px" placeholder="What should it have said? (optional)" value="' + esc(c.note || "") + '">' +
        '<p class="msg" id="rmsg">' + (c.reviewed_by ? "Last reviewed by " + esc(c.reviewed_by) + " · " + when(c.reviewed_at) : "") + "</p></div>";
      box.innerHTML = h;
    }).catch(function (e) { box.innerHTML = '<p class="empty">' + esc(e.message) + '</p><button class="abtn g" data-close type="button">Close</button>'; });
    drawer.onclick = function (e) {
      if (e.target === drawer || e.target.hasAttribute("data-close")) { drawer.hidden = true; if (after) after(); return; }
      var r = e.target.getAttribute("data-rate"); if (r === null) return;
      call("POST", "/admin/conversations/" + id + "/review", { rating: r || null, note: document.getElementById("rnote").value })
        .then(function () { say(document.getElementById("rmsg"), true, "Saved."); drawer.querySelectorAll("[data-rate]").forEach(function (b) {
          var v = b.getAttribute("data-rate"); b.className = "abtn " + (v && v === r ? (v === "bad" ? "r" : "") : "g"); }); })
        .catch(function (er) { say(document.getElementById("rmsg"), false, er.message); });
    };
  }
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && drawer && !drawer.hidden) drawer.click(); });

  VIEWS.usage = function () {
    main.innerHTML = head("AI usage & cost", "Voice minutes, chat requests and what they cost. Estimates use the rates in the server settings; Google's billing page is the final word.") +
      '<div class="bar"><select id="ud"><option value="7">Last 7 days</option><option value="30" selected>Last 30 days</option><option value="90">Last 90 days</option></select></div><div id="ub"><p class="empty">Loading…</p></div>';
    function load() {
      get("/admin/usage?days=" + document.getElementById("ud").value).then(function (d) {
        var s = d.summary, r = d.rates, rows = d.days, max = Math.max.apply(null, rows.map(function (x) { return x.total_inr; }).concat([0.01]));
        var h = (r.billing === "free" ? '<div class="note">Gemini is on the <b>free tier</b>: nothing is billed right now (billed ' + inr(s.billed_inr) +
          '). The estimate shows what this usage would cost on the paid plan.</div>' : "") +
          '<div class="kpis">' + kpi("Voice calls", num(s.voice_calls)) + kpi("Voice minutes", num(s.voice_minutes), "≈ " + inr(r.voice_inr_per_min) + " per minute") +
          kpi("Chat requests", num(s.chat_requests)) + kpi("Estimated cost", inr(s.estimated_inr)) + kpi("Billed now", inr(s.billed_inr), "", "good") + "</div>" +
          '<div class="card"><h3>Estimated cost per day</h3><div class="bars">' + rows.map(function (x) {
            return '<i style="height:' + Math.max(1.5, x.total_inr / max * 100) + '%" data-t="' + esc(x.date) + ": " + inr(x.total_inr) + '"></i>';
          }).join("") + '</div></div><div class="tblw"><table class="tbl"><thead><tr><th>Date</th><th class="num">Voice calls</th><th class="num">Voice min</th><th class="num">Voice ₹</th>' +
          '<th class="num">Chat requests</th><th>Chat by AI</th><th class="num">Chat tokens in/out</th><th class="num">Chat ₹</th><th class="num">Total ₹</th></tr></thead><tbody>';
        rows.slice().reverse().forEach(function (x) {
          var by = Object.keys(x.chat_by_provider).map(function (k) { return esc(k) + " " + x.chat_by_provider[k]; }).join(", ");
          h += "<tr><td>" + day(x.date) + '</td><td class="num">' + x.voice_calls + '</td><td class="num">' + x.voice_minutes + '</td><td class="num">' + inr(x.voice_inr) +
            '</td><td class="num">' + x.chat_requests + "</td><td>" + (by || "—") + '</td><td class="num">' + num(x.chat_in_tokens) + " / " + num(x.chat_out_tokens) +
            '</td><td class="num">' + inr(x.chat_inr) + '</td><td class="num"><b>' + inr(x.total_inr) + "</b></td></tr>";
        });
        h += '</tbody></table></div><p class="muted2" style="margin-top:12px">Rates: 1 USD = ₹' + r.usd_inr + " · voice ₹" + r.voice_inr_per_min + "/min · chat per 1M tokens: " +
          Object.keys(r.price_usd_per_million).map(function (k) { var p = r.price_usd_per_million[k]; return esc(k) + " $" + p[0] + " in / $" + p[1] + " out"; }).join(" · ") +
          ". Change them in backend/.env (USD_INR, VOICE_INR_PER_MIN, PRICE_*, AI_BILLING).</p>";
        document.getElementById("ub").innerHTML = h;
      }).catch(fail);
    }
    document.getElementById("ud").addEventListener("change", load);
    load();
  };

  VIEWS.users = function () {
    loading();
    get("/admin/users").then(function (d) {
      CLIENTS = d.clients;
      var h = head("Users & accounts", "Create logins for your team and your clients. Staff can see leads and AI conversations; admins see everything; clients only see their own invoices.");
      h += '<div class="card"><h3>Add a team member</h3><form class="frm" id="fe" autocomplete="off">' +
        '<label>Username<input name="username" required placeholder="e.g. riya"></label><label>Full name<input name="name"></label>' +
        '<label>Password (min 8)<input name="password" type="password" required autocomplete="new-password"></label>' +
        '<label>Role<select name="role"><option value="staff">Staff</option><option value="admin">Admin</option></select></label>' +
        '<button class="abtn" type="submit">Create login</button></form><p class="msg" id="fem"></p></div>';
      h += '<div class="card"><h3>Add a client</h3><form class="frm" id="fc" autocomplete="off">' +
        '<label>Username<input name="username" required placeholder="e.g. acme"></label><label>Company<input name="company" required></label>' +
        '<label>Contact person<input name="contact_name"></label><label>Phone<input name="phone"></label><label>Email<input name="email" type="email"></label>' +
        '<label>Password (min 8)<input name="password" type="password" required autocomplete="new-password"></label>' +
        '<label class="wide">Notes<input name="notes" placeholder="plan, services, anything useful"></label>' +
        '<button class="abtn" type="submit">Create client login</button></form><p class="msg" id="fcm"></p></div>';
      h += '<div class="card"><h3>Team</h3><div class="tblw"><table class="tbl"><thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Status</th><th>New password</th><th></th></tr></thead><tbody>';
      d.employees.forEach(function (u) {
        var self = u.id === ME.id;
        h += "<tr><td>" + esc(u.username) + (self ? ' <span class="pill">you</span>' : "") + "</td><td>" + esc(u.name) + '</td><td><select data-e-role="' + u.id + '"' + (self ? " disabled" : "") + ">" +
          ["staff", "admin"].map(function (r) { return "<option" + (r === u.role ? " selected" : "") + ">" + r + "</option>"; }).join("") + "</select></td><td>" +
          (u.active ? '<span class="pill good">Active</span>' : '<span class="pill off">Disabled</span>') + '</td><td><input type="password" data-e-pw="' + u.id + '" placeholder="type + Enter" autocomplete="new-password"></td><td>' +
          (self ? "" : '<button class="abtn sm ' + (u.active ? "r" : "g") + '" type="button" data-e-active="' + u.id + '" data-v="' + (u.active ? 0 : 1) + '">' + (u.active ? "Disable" : "Enable") + "</button>") + "</td></tr>";
      });
      h += '</tbody></table></div><p class="msg" id="tem"></p></div>';
      h += '<div class="card"><h3>Clients</h3><div class="tblw"><table class="tbl"><thead><tr><th>Username</th><th>Company</th><th>Contact</th><th class="num">Unpaid</th><th>Status</th><th>New password</th><th></th></tr></thead><tbody>';
      if (!d.clients.length) h += '<tr><td colspan="7" class="empty">No clients yet.</td></tr>';
      d.clients.forEach(function (u) {
        h += "<tr><td>" + esc(u.username) + "</td><td>" + esc(u.company) + (u.notes ? '<br><span class="muted2">' + esc(u.notes) + "</span>" : "") + "</td><td>" + esc(u.contact_name) +
          (u.phone ? '<br><a href="tel:' + esc(u.phone) + '">' + esc(u.phone) + "</a>" : "") + (u.email ? '<br><span class="muted2">' + esc(u.email) + "</span>" : "") +
          '</td><td class="num">' + inr(u.due) + "</td><td>" + (u.active ? '<span class="pill good">Active</span>' : '<span class="pill off">Disabled</span>') +
          '</td><td><input type="password" data-c-pw="' + u.id + '" placeholder="type + Enter" autocomplete="new-password"></td><td><button class="abtn sm ' + (u.active ? "r" : "g") +
          '" type="button" data-c-active="' + u.id + '" data-v="' + (u.active ? 0 : 1) + '">' + (u.active ? "Disable" : "Enable") + "</button></td></tr>";
      });
      h += '</tbody></table></div><p class="msg" id="tcm"></p></div>';
      main.innerHTML = h;

      function create(formId, path, msgId) {
        var f = document.getElementById(formId);
        f.addEventListener("submit", function (e) {
          e.preventDefault();
          call("POST", path, formData(f)).then(function () { say(document.getElementById(msgId), true, "Created. Share the username and password with them."); setTimeout(VIEWS.users, 900); })
            .catch(function (er) { say(document.getElementById(msgId), false, er.message); });
        });
      }
      create("fe", "/admin/employees", "fem");
      create("fc", "/admin/clients", "fcm");
      main.onchange = function (e) {
        var id = e.target.getAttribute("data-e-role");
        if (id) call("PATCH", "/admin/employees/" + id, { role: e.target.value }).then(function () { say(document.getElementById("tem"), true, "Role updated."); })
          .catch(function (er) { say(document.getElementById("tem"), false, er.message); });
      };
      main.onkeydown = function (e) {
        if (e.key !== "Enter") return;
        var eid = e.target.getAttribute("data-e-pw"), cid = e.target.getAttribute("data-c-pw");
        if (!eid && !cid) return;
        e.preventDefault();
        var m = document.getElementById(eid ? "tem" : "tcm");
        call("PATCH", (eid ? "/admin/employees/" + eid : "/admin/clients/" + cid), { password: e.target.value })
          .then(function () { e.target.value = ""; say(m, true, "Password changed. They have been signed out and must use the new password."); })
          .catch(function (er) { say(m, false, er.message); });
      };
      main.onclick = function (e) {
        var eid = e.target.getAttribute("data-e-active"), cid = e.target.getAttribute("data-c-active");
        if (!eid && !cid) return;
        call("PATCH", (eid ? "/admin/employees/" + eid : "/admin/clients/" + cid), { active: e.target.getAttribute("data-v") === "1" })
          .then(VIEWS.users).catch(function (er) { say(document.getElementById(eid ? "tem" : "tcm"), false, er.message); });
      };
    }).catch(fail);
  };

  VIEWS.billing = function () {
    loading();
    Promise.all([get("/admin/users"), get("/admin/invoices")]).then(function (res) {
      CLIENTS = res[0].clients;
      var inv = res[1].items, gst = res[1].gst_pct_default;
      var h = head("Billing", "Create invoices for clients and mark them paid. Clients see their invoices when they log in.");
      if (!CLIENTS.length) h += '<div class="note">Add a client first in <a href="#users">Users &amp; accounts</a>.</div>';
      h += '<div class="card"><h3>New invoice</h3><form class="frm" id="fi"><label>Client<select name="client_id" required>' +
        CLIENTS.filter(function (c) { return c.active; }).map(function (c) { return '<option value="' + c.id + '">' + esc(c.company || c.username) + "</option>"; }).join("") +
        '</select></label><label>For (description)<input name="description" required placeholder="e.g. IVR setup + 1 month support"></label>' +
        '<label>Period<input name="period" placeholder="e.g. Nov 2026"></label><label>Amount before GST (₹)<input name="amount" type="number" min="1" step="0.01" required></label>' +
        '<label>GST %<input name="gst_pct" type="number" min="0" max="28" step="0.01" value="' + gst + '"></label><label>Due in days<input name="due_days" type="number" min="0" value="15"></label>' +
        '<label class="wide">Notes<input name="notes" placeholder="optional"></label><button class="abtn" type="submit"' + (CLIENTS.length ? "" : " disabled") + '>Create invoice</button></form><p class="msg" id="fim"></p></div>';
      var unpaid = inv.filter(function (x) { return x.status === "unpaid"; }).reduce(function (a, x) { return a + x.total; }, 0);
      h += '<div class="kpis">' + kpi("Unpaid", inr(unpaid), "", unpaid ? "warn" : "") + kpi("Invoices", num(inv.length)) + "</div>";
      h += '<div class="tblw"><table class="tbl"><thead><tr><th>Number</th><th>Client</th><th>For</th><th>Issued</th><th>Due</th><th class="num">Amount</th><th class="num">GST</th><th class="num">Total</th><th>Status</th><th></th></tr></thead><tbody>';
      if (!inv.length) h += '<tr><td colspan="10" class="empty">No invoices yet.</td></tr>';
      inv.forEach(function (x) {
        h += "<tr><td><b>" + esc(x.number) + "</b></td><td>" + esc(x.company || x.username) + "</td><td>" + esc(x.description) + (x.period ? '<br><span class="muted2">' + esc(x.period) + "</span>" : "") +
          "</td><td>" + day(x.issued_at) + "</td><td>" + day(x.due_at) + '</td><td class="num">' + inr(x.amount) + '</td><td class="num">' + x.gst_pct + '%</td><td class="num"><b>' + inr(x.total) +
          "</b></td><td>" + (x.status === "paid" ? '<span class="pill good">Paid</span><br><span class="muted2">' + day(x.paid_at) + "</span>" : x.status === "cancelled" ? '<span class="pill off">Cancelled</span>' : '<span class="pill warn">Unpaid</span>') +
          '</td><td style="white-space:nowrap">' + (x.status !== "paid" ? '<button class="abtn sm" data-inv="' + x.id + '" data-s="paid" type="button">Mark paid</button> ' : '<button class="abtn sm g" data-inv="' + x.id + '" data-s="unpaid" type="button">Undo paid</button> ') +
          (x.status === "unpaid" ? '<button class="abtn sm r" data-inv="' + x.id + '" data-s="cancelled" type="button">Cancel</button> ' : "") +
          '<button class="abtn sm g" data-print="' + x.id + '" type="button">Print</button></td></tr>';
      });
      main.innerHTML = h + '</tbody></table></div><p class="msg" id="bim"></p>';
      var fi = document.getElementById("fi");
      fi.addEventListener("submit", function (e) {
        e.preventDefault();
        var d = formData(fi); d.client_id = Number(d.client_id);
        call("POST", "/admin/invoices", d).then(function (r) { say(document.getElementById("fim"), true, "Invoice " + r.number + " created: " + inr(r.total)); setTimeout(VIEWS.billing, 900); })
          .catch(function (er) { say(document.getElementById("fim"), false, er.message); });
      });
      main.onclick = function (e) {
        var id = e.target.getAttribute("data-inv");
        if (id) {
          call("PATCH", "/admin/invoices/" + id, { status: e.target.getAttribute("data-s") }).then(VIEWS.billing)
            .catch(function (er) { say(document.getElementById("bim"), false, er.message); });
          return;
        }
        var pid = e.target.getAttribute("data-print");
        if (pid) printInvoice(inv.filter(function (x) { return String(x.id) === pid; })[0]);
      };
    }).catch(fail);
  };

  function printInvoice(x) {
    var c = CLIENTS.filter(function (k) { return k.id === x.client_id; })[0] || {};
    var brand = (window.ATE && window.ATE.brand) || "Agile Tech Expert";
    var w = window.open("", "_blank");
    if (!w) return;
    w.document.write("<!doctype html><meta charset=utf-8><title>" + esc(x.number) + "</title><style>body{font-family:system-ui,sans-serif;max-width:720px;margin:32px auto;padding:0 20px;color:#10303a}" +
      "h1{margin:0;color:#0b6f6a}table{width:100%;border-collapse:collapse;margin:20px 0}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}.r{text-align:right}.top{display:flex;justify-content:space-between}</style>" +
      '<div class="top"><div><h1>' + esc(brand) + "</h1><p>Tax invoice</p></div><div style=\"text-align:right\"><b>" + esc(x.number) + "</b><br>Issued " + day(x.issued_at) + "<br>Due " + day(x.due_at) + "</div></div>" +
      "<p><b>Bill to</b><br>" + esc(c.company || x.company || "") + "<br>" + esc(c.contact_name || "") + "<br>" + esc(c.email || "") + " " + esc(c.phone || "") + "</p>" +
      "<table><tr><th>Description</th><th>Period</th><th class=r>Amount</th></tr><tr><td>" + esc(x.description) + "</td><td>" + esc(x.period) + "</td><td class=r>" + inr(x.amount) + "</td></tr>" +
      "<tr><td colspan=2 class=r>GST " + x.gst_pct + "%</td><td class=r>" + inr(x.total - x.amount) + "</td></tr><tr><th colspan=2 class=r>Total</th><th class=r>" + inr(x.total) + "</th></tr></table>" +
      "<p>Status: <b>" + esc(x.status) + "</b></p>" + (x.notes ? "<p>" + esc(x.notes) + "</p>" : "") + "<script>window.onload=function(){window.print()}<\/script>");
    w.document.close();
  }

  VIEWS.activity = function () {
    loading();
    get("/admin/audit?limit=200").then(function (d) {
      var h = head("Activity log", "Who changed what: accounts, invoices and lead updates.") + '<div class="tblw"><table class="tbl"><thead><tr><th>When</th><th>Who</th><th>Action</th><th>Detail</th></tr></thead><tbody>';
      if (!d.items.length) h += '<tr><td colspan="4" class="empty">Nothing yet.</td></tr>';
      d.items.forEach(function (x) { h += "<tr><td>" + when(x.at) + "</td><td>" + esc(x.actor) + "</td><td>" + esc(x.action) + "</td><td>" + esc(x.detail) + "</td></tr>"; });
      main.innerHTML = h + "</tbody></table></div>";
    }).catch(fail);
  };

  // ---------- start
  get("/me").then(function (d) {
    if (!d || !d.employee) { location.replace(LOGIN); return; }
    ME = d.employee;
    buildNav();
    window.addEventListener("hashchange", route);
    route();
  }).catch(function () { location.replace(LOGIN); });
})();
