/* Agile Tech Expert - Quotations, letters and letterheads (staff portal: admin, accounts, staff).
   Every document is saved as a numbered record: what was made, for whom, by whom and when. */
(function () {
  "use strict";
  var K, M = null, S = { sub: "register" };
  var SUBS = [{ id: "register", label: "All documents" }, { id: "quote", label: "+ New quotation" },
    { id: "letter", label: "+ New letter" }, { id: "blank", label: "Blank letterhead" }];
  var UNITS = ["pcs", "nos", "set", "box", "job", "hrs", "month", "year", "user", "license", "min", "sms", "mtr"];
  var KIND = { quote: "Quotation", letter: "Letter", blank: "Blank letterhead" };

  function $(id) { return document.getElementById(id); }
  function opt(v, l, sel) { return '<option value="' + K.esc(v) + '"' + (sel ? " selected" : "") + ">" + K.esc(l) + "</option>"; }
  function r2(n) { return Math.round((Number(n) + Number.EPSILON) * 100) / 100; }
  function calcNum(v) {
    var t = String(v == null ? "" : v).replace(/,/g, "").replace(/[x×]/gi, "*").trim();
    if (!t) return 0;
    if (!/^[\d.\s+\-*/()]+$/.test(t)) return NaN;
    try { var n = Function('"use strict";return (' + t + ")")(); return isFinite(n) ? n : NaN; } catch (e) { return NaN; }
  }
  function money(v) { return K.inr(v).replace("₹", ""); }
  function api(p) { return K.api + p; }
  function pdfTab() { try { return window.open("about:blank", "_blank"); } catch (e) { return null; } }
  function showUrl(w, url) { if (w && !w.closed) w.location.href = url; else window.open(url, "_blank", "noopener"); }
  function postPdf(path, body, w, msgEl) {
    return fetch(api(path), { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { if (!r.ok) return r.json().then(function (x) { throw new Error(typeof x.detail === "string" ? x.detail : "Please check the form."); }); return r.blob(); })
      .then(function (b) { showUrl(w, URL.createObjectURL(b)); K.say(msgEl, true, "Preview opened in a new tab (not saved)."); })
      .catch(function (er) { if (w) w.close(); K.say(msgEl, false, er.message); });
  }
  function placeholders(text) { var m = String(text).match(/\[[^\]]{2,40}\]/g); return m ? m.filter(function (x, i, a) { return a.indexOf(x) === i; }) : []; }

  function shell(inner) {
    var tabs = SUBS.map(function (t) { return '<button type="button" class="abtn ' + (t.id === S.sub ? "" : "g") + '" data-dsub="' + t.id + '">' + K.esc(t.label) + "</button>"; }).join("");
    K.main.innerHTML = K.head("Quotations & letters", "Quotations and letters on the company letterhead, and blank letterheads. Every document gets a number and is recorded with who made it, for whom and why.") +
      '<div class="bar bsubs">' + tabs + "</div>" + inner;
  }
  function go(sub, arg) {
    S.sub = sub; S.click = S.change = S.input = null;
    K.main.onclick = function (e) { var b = e.target.closest("[data-dsub]"); if (b) { go(b.getAttribute("data-dsub")); return; } if (S.click) S.click(e); };
    K.main.onchange = function (e) { if (S.change) S.change(e); };
    K.main.oninput = function (e) { if (S.input) S.input(e); };
    K.main.onkeydown = null;
    K.loading();
    (M ? Promise.resolve() : K.get("/docs/meta").then(function (m) { M = m; })).then(function () { VIEW[sub](arg); }).catch(K.fail);
  }
  var VIEW = {};

  // ---------------------------------------------------------------- register
  VIEW.register = function () {
    K.get("/docs").then(function (d) {
      var all = d.items, canBill = ["admin", "accounts"].indexOf(K.me.role) >= 0;
      var h = '<div class="bar"><select id="dk">' + opt("", "All types") + opt("quote", "Quotations") + opt("letter", "Letters") + opt("blank", "Blank letterheads") +
        '</select><input type="search" id="dq" placeholder="Search number, customer, subject or purpose"></div>' +
        '<div class="tblw"><table class="tbl"><thead><tr><th>Number</th><th>Type</th><th>Date</th><th>For</th><th>Subject / purpose</th><th class="num">Amount</th><th>Made by</th><th></th></tr></thead><tbody id="dtb"></tbody></table></div><p class="msg" id="dmsg"></p>';
      shell(h);
      function draw() {
        var k = $("dk").value, q = $("dq").value.trim().toLowerCase();
        var rows = all.filter(function (x) { return (!k || x.kind === k) && (!q || [x.number, x.recipient, x.subject, x.purpose].join(" ").toLowerCase().indexOf(q) >= 0); });
        $("dtb").innerHTML = rows.length ? rows.map(function (x) {
          var st = x.kind === "quote" ? '<select data-st="' + x.id + '">' + ["draft", "sent", "accepted", "rejected", "converted"].map(function (s) { return opt(s, s, s === x.status); }).join("") + "</select>" : "";
          return "<tr><td><b>" + K.esc(x.number) + "</b>" + (x.updated_at ? '<br><span class="muted2">edited</span>' : "") + "</td><td>" + KIND[x.kind] + (st ? "<br>" + st : "") +
            "</td><td>" + K.esc(x.doc_date) + "</td><td>" + K.esc(x.recipient || "—") + "</td><td>" + K.esc(x.subject || "") +
            (x.purpose ? '<br><span class="muted2">Why: ' + K.esc(x.purpose) + "</span>" : "") + '</td><td class="num">' + (x.total != null ? K.inr(x.total) : "") +
            "</td><td>" + K.esc(x.created_by) + '<br><span class="muted2">' + K.esc((x.created_at || "").slice(0, 10)) + '</span></td><td class="acts">' +
            '<a class="abtn sm g" target="_blank" rel="noopener" href="' + api("/docs/" + x.id + "/file") + '">' + (x.kind === "blank" && /DOCX/.test(x.subject) ? "Word" : "PDF") + "</a> " +
            (x.kind !== "blank" ? '<button class="abtn sm g" type="button" data-ed="' + x.id + '" data-k="' + x.kind + '">Edit</button> ' : "") +
            (x.kind === "quote" ? '<button class="abtn sm g" type="button" data-copy="' + x.id + '">Copy</button> ' : "") +
            (x.kind === "quote" && canBill && x.status !== "converted" ? '<button class="abtn sm" type="button" data-inv="' + x.id + '">Make invoice</button>' : "") + "</td></tr>";
        }).join("") : '<tr><td colspan="8" class="empty">Nothing yet. Start with <b>+ New quotation</b> or <b>+ New letter</b>.</td></tr>';
      }
      draw();
      S.input = function (e) { if (e.target.id === "dq") draw(); };
      S.change = function (e) {
        if (e.target.id === "dk") { draw(); return; }
        var id = e.target.getAttribute("data-st");
        if (id) K.call("POST", "/docs/" + id + "/status", { status: e.target.value }).then(function () { K.say($("dmsg"), true, "Status updated."); })
          .catch(function (er) { K.say($("dmsg"), false, er.message); });
      };
      S.click = function (e) {
        var t = e.target;
        if (t.getAttribute("data-ed")) { var id = Number(t.getAttribute("data-ed")); K.get("/docs/" + id).then(function (r) { go(t.getAttribute("data-k"), { edit: r }); }); return; }
        if (t.getAttribute("data-copy")) { K.get("/docs/" + t.getAttribute("data-copy")).then(function (r) { r.id = null; r.number = null; go("quote", { edit: r }); }); return; }
        if (t.getAttribute("data-inv")) { window.ATE_BILLING_PREFILL = { quote: Number(t.getAttribute("data-inv")) }; location.hash = "billing"; }
      };
    }).catch(K.fail);
  };

  // ---------------------------------------------------------------- quotation
  function qLine(l) {
    l = l || {};
    var unit = l.unit || "pcs", units = UNITS.indexOf(unit) < 0 ? UNITS.concat([unit]) : UNITS;
    return '<tr class="ln"><td class="sl"></td><td class="itemcell"><input data-f="name" list="dqItems" placeholder="Item / service name" value="' + K.esc(l.name || "") + '">' +
      '<textarea data-f="description" rows="2" placeholder="Details (model, specs, period)…">' + K.esc(l.description || "") + "</textarea></td>" +
      '<td><input data-f="hsn" value="' + K.esc(l.hsn || "") + '" placeholder="HSN/SAC"></td>' +
      '<td><input data-f="qty" class="calc" inputmode="decimal" value="' + (l.qty != null ? l.qty : 1) + '"></td>' +
      '<td><select data-f="unit">' + units.map(function (u) { return opt(u, u.toUpperCase(), u === unit); }).join("") + "</select></td>" +
      '<td><input data-f="rate" class="calc" inputmode="decimal" placeholder="0" value="' + (l.rate ? l.rate : "") + '"></td>' +
      '<td><input data-f="discount_pct" class="calc" inputmode="decimal" placeholder="0" value="' + (l.discount_pct ? l.discount_pct : "") + '"></td>' +
      '<td><select data-f="gst_rate">' + [0, 5, 12, 18, 28].map(function (g) { return opt(g, g + "%", g === Number(l.gst_rate != null ? l.gst_rate : 18)); }).join("") + "</select></td>" +
      '<td class="num amtcell"><b data-out="amount">0.00</b><div data-out="calc" class="calcline"></div><div data-out="tax" class="taxlines"></div></td>' +
      '<td><button type="button" class="abtn sm r" data-del>✕</button></td></tr>';
  }

  VIEW.quote = function (arg) {
    var ed = arg && arg.edit, d = ed ? ed.data : null, tpl = M.quote_templates[0];
    var h = '<div class="card inv-card"><div class="inv-top"><h3>' + (ed && ed.id ? "Edit quotation " + K.esc(ed.number) : "New quotation") + "</h3>" +
      (ed && ed.id ? "" : '<label class="muted2">Template <select id="qtpl">' + M.quote_templates.map(function (t) { return opt(t.key, t.name); }).join("") + "</select></label>") + "</div>" +
      '<div class="frm"><label>Customer (existing account)<select id="qparty">' + opt("", "— type a new customer below —") +
      M.parties.map(function (p) { return opt(p.id, p.code + " · " + p.name, d && d.party_id === p.id); }).join("") + "</select></label>" +
      '<label>Customer name<input id="qname" maxlength="160" value="' + K.esc(d ? d.to_name : "") + '"></label>' +
      '<label>Kind attention<input id="qattn" maxlength="120" placeholder="Mr. / Ms. Name, Designation" value="' + K.esc(d ? d.attention : "") + '"></label>' +
      '<label>GSTIN<input id="qgstin" maxlength="15" style="text-transform:uppercase" value="' + K.esc(d ? d.to_gstin : "") + '"></label>' +
      '<label>State<select id="qstate">' + opt("", "— select —") + Object.keys(M.states).map(function (c) { return opt(M.states[c], c + " · " + M.states[c], d && d.to_state === M.states[c]); }).join("") + "</select></label>" +
      '<label>Date<input type="date" id="qdate" value="' + K.esc(ed && ed.doc_date ? ed.doc_date : M.today) + '"></label>' +
      '<label>Valid for (days)<input type="number" id="qvalid" min="1" max="365" value="' + (d ? d.valid_days : 15) + '"></label>' +
      '<label class="wide">Customer address<textarea id="qaddr" rows="2" maxlength="600">' + K.esc(d ? d.to_address : "") + "</textarea></label>" +
      '<label class="wide">Subject<input id="qsubj" maxlength="200" value="' + K.esc(d ? d.subject : "") + '"></label>' +
      '<label class="wide">Opening paragraph<textarea id="qintro" rows="3" maxlength="3000">' + K.esc(d ? d.intro : "") + "</textarea></label></div>" +
      '<div class="taxbox"><b>GST</b> <span class="muted2" id="qhint"></span><br><label class="chk"><input type="checkbox" id="qcg"> CGST</label><label class="chk"><input type="checkbox" id="qsg"> SGST</label><label class="chk"><input type="checkbox" id="qig"> IGST</label></div>' +
      '<h4 class="sech">Items</h4><div class="tblw"><table class="tbl lines qlines"><thead><tr><th>#</th><th>Item &amp; details</th><th>HSN/SAC</th><th>Qty</th><th>Unit</th><th>Rate ₹</th><th>Disc %</th><th>GST</th><th class="num">Amount</th><th></th></tr></thead><tbody id="qlines"></tbody></table></div>' +
      '<datalist id="dqItems">' + M.items.map(function (x) { return '<option value="' + K.esc(x.name) + '">' + K.esc(x.code) + "</option>"; }).join("") + "</datalist>" +
      '<div class="addrow"><button type="button" class="abtn" id="qadd">+ Add another item</button><span class="muted2">Pick an inventory item by name to fill its rate, or type anything. Qty and Rate accept 5000*4.</span></div>' +
      '<div class="inv-bottom"><label class="frm-one">Terms &amp; conditions (one per line)<textarea id="qterms" rows="7" maxlength="5000">' + K.esc(d ? d.terms : "") + '</textarea></label><div class="totals" id="qtot"></div></div>' +
      '<div class="frm" style="margin-top:12px"><label>Signatory name &amp; designation<input id="qsign" maxlength="120" placeholder="e.g. Rahul Sharma, Sales Manager" value="' + K.esc(d ? d.signatory : (K.me.name || "")) + '"></label>' +
      '<label class="wide">Internal note — why / for whom (not printed)<input id="qpurpose" maxlength="200" placeholder="e.g. After demo on 28 Oct, 50 agents" value="' + K.esc(d ? d.purpose : "") + '"></label></div>' +
      '<div class="bar" style="margin-top:14px"><button type="button" class="abtn g" id="qprev">Preview PDF</button><button type="button" class="abtn" id="qsave">' + (ed && ed.id ? "Save changes" : "Save quotation") + '</button><button type="button" class="abtn g" data-dsub="register">Back</button></div><p class="msg" id="qmsg"></p></div>';
    shell(h);

    function applyTemplate(t) {
      $("qsubj").value = t.subject; $("qintro").value = t.intro; $("qterms").value = t.terms.join("\n");
      $("qlines").innerHTML = t.lines.map(qLine).join(""); calc();
    }
    function sameState() { var st = $("qstate").value, g = $("qgstin").value.trim().slice(0, 2); if (g && /^\d\d$/.test(g)) return g === M.company_state_code; return !st || st === M.company_state; }
    function autoTax() { var s = sameState(); $("qcg").checked = s; $("qsg").checked = s; $("qig").checked = !s; $("qhint").textContent = s ? "(customer in our state → CGST + SGST)" : "(customer in another state → IGST)"; calc(); }
    function g(tr, f) { return tr.querySelector('[data-f="' + f + '"]'); }
    function rows() {
      var out = [];
      K.main.querySelectorAll("#qlines tr.ln").forEach(function (tr) {
        out.push({ tr: tr, name: g(tr, "name").value.trim(), description: g(tr, "description").value.trim(), hsn: g(tr, "hsn").value.trim(),
          qty: calcNum(g(tr, "qty").value), unit: g(tr, "unit").value, rate: calcNum(g(tr, "rate").value), discount_pct: calcNum(g(tr, "discount_pct").value), gst_rate: Number(g(tr, "gst_rate").value) });
      });
      return out;
    }
    function calc() {
      var cg = $("qcg").checked, sg = $("qsg").checked, ig = $("qig").checked, T = { s: 0, c: 0, g: 0, i: 0 }, n = 0;
      rows().forEach(function (r) {
        r.tr.querySelector(".sl").textContent = ++n;
        var bad = isNaN(r.qty) || isNaN(r.rate) || isNaN(r.discount_pct); r.tr.classList.toggle("badnum", bad);
        var q = r.qty || 0, rt = r.rate || 0, dp = r.discount_pct || 0, gross = r2(q * rt), disc = r2(gross * dp / 100), tx = r2(gross - disc), half = r.gst_rate / 2;
        var c = cg ? r2(tx * r.gst_rate / 200) : 0, s = sg ? r2(tx * r.gst_rate / 200) : 0, i = ig ? r2(tx * r.gst_rate / 100) : 0;
        r.tr.querySelector('[data-out="amount"]').textContent = money(tx);
        r.tr.querySelector('[data-out="calc"]').innerHTML = bad ? '<span class="neg">check the number</span>' : (+q.toFixed(3)) + " × " + money(rt) + (disc ? " − " + dp + "%" : "") + " = " + money(tx);
        r.tr.querySelector('[data-out="tax"]').innerHTML = (cg ? "<span>CGST " + half + "%: " + money(c) + "</span>" : "") + (sg ? "<span>SGST " + half + "%: " + money(s) + "</span>" : "") +
          (ig ? "<span>IGST " + r.gst_rate + "%: " + money(i) + "</span>" : "") + ((c + s + i) ? "<span><b>Item total: " + money(tx + c + s + i) + "</b></span>" : "");
        T.s += tx; T.c += c; T.g += s; T.i += i;
      });
      var gross = r2(T.s + T.c + T.g + T.i), rnd = M.round_off === "1" ? r2(Math.round(gross) - gross) : 0;
      $("qtot").innerHTML = "<div><span>Taxable value</span><b>" + K.inr(T.s) + "</b></div>" + (cg ? "<div><span>CGST</span><b>" + K.inr(T.c) + "</b></div>" : "") +
        (sg ? "<div><span>SGST</span><b>" + K.inr(T.g) + "</b></div>" : "") + (ig ? "<div><span>IGST</span><b>" + K.inr(T.i) + "</b></div>" : "") +
        (rnd ? "<div><span>Round off</span><b>" + K.inr(rnd) + "</b></div>" : "") + '<div class="grand"><span>Grand total</span><b>' + K.inr(gross + rnd) + "</b></div>";
    }
    function body() {
      var ls = rows().filter(function (r) { return r.name; }).map(function (r) { return { name: r.name, description: r.description, hsn: r.hsn, qty: r.qty, unit: r.unit, rate: r.rate, discount_pct: r.discount_pct, gst_rate: r.gst_rate }; });
      return { party_id: $("qparty").value ? Number($("qparty").value) : null, to_name: $("qname").value.trim(), attention: $("qattn").value.trim(),
        to_address: $("qaddr").value.trim(), to_gstin: $("qgstin").value.trim().toUpperCase(), to_state: $("qstate").value, qt_date: $("qdate").value,
        valid_days: Number($("qvalid").value || 15), subject: $("qsubj").value.trim(), intro: $("qintro").value.trim(), terms: $("qterms").value.trim(),
        apply_cgst: $("qcg").checked, apply_sgst: $("qsg").checked, apply_igst: $("qig").checked, lines: ls, purpose: $("qpurpose").value.trim(),
        template: $("qtpl") ? $("qtpl").value : (d && d.template) || "", signatory: $("qsign").value.trim() };
    }
    function check(b) {
      if (!b.to_name) return "Enter the customer name.";
      if (!b.lines.length) return "Add at least one item.";
      for (var i = 0; i < b.lines.length; i++) if (isNaN(b.lines[i].qty) || isNaN(b.lines[i].rate) || !(b.lines[i].qty > 0)) return "Item " + (i + 1) + ": check quantity and rate.";
      if (b.lines.some(function (l) { return !l.rate; }) && !confirm("Some items have rate 0. Continue?")) return "stop";
      return "";
    }
    S.change = function (e) {
      var t = e.target;
      if (t.id === "qtpl") { var tp = M.quote_templates.filter(function (x) { return x.key === t.value; })[0]; if (tp) applyTemplate(tp); return; }
      if (t.id === "qparty") {
        var p = M.parties.filter(function (x) { return String(x.id) === t.value; })[0];
        if (p) { $("qname").value = p.name; $("qaddr").value = p.address || ""; $("qgstin").value = p.gstin || ""; $("qstate").value = p.state || ""; }
        autoTax(); return;
      }
      if (t.id === "qstate" || t.id === "qgstin") { autoTax(); return; }
      if (t.getAttribute("data-f") === "name") {
        var it = M.items.filter(function (x) { return x.name.toLowerCase() === t.value.trim().toLowerCase(); })[0], tr = t.closest("tr");
        if (it) { g(tr, "hsn").value = it.hsn || ""; g(tr, "rate").value = it.price; if (!g(tr, "description").value.trim()) g(tr, "description").value = it.description || ""; g(tr, "gst_rate").value = String(it.gst_rate);
          var u = (it.unit || "pcs").toLowerCase(); if (!Array.prototype.some.call(g(tr, "unit").options, function (o) { return o.value === u; })) g(tr, "unit").insertAdjacentHTML("beforeend", opt(u, u.toUpperCase())); g(tr, "unit").value = u; }
      }
      if (t.classList.contains("calc") && /[*x×+\/()-]/i.test(t.value.replace(/^-/, ""))) { var v = calcNum(t.value); if (!isNaN(v)) t.value = String(r2(v)); }
      calc();
    };
    S.input = function (e) { if (e.target.closest("#qlines")) calc(); if (e.target.id === "qgstin" && /^\d\d/.test(e.target.value)) { var sc = e.target.value.slice(0, 2); if (M.states[sc]) $("qstate").value = M.states[sc]; autoTax(); } };
    S.click = function (e) {
      var t = e.target;
      if (t.hasAttribute("data-del")) { if (K.main.querySelectorAll("#qlines tr.ln").length > 1) t.closest("tr").remove(); calc(); return; }
      if (t.id === "qadd") { $("qlines").insertAdjacentHTML("beforeend", qLine()); calc(); $("qlines").lastElementChild.querySelector('[data-f="name"]').focus(); return; }
      if (t.id === "qprev") { var b = body(), err = check(b); if (err) { if (err !== "stop") K.say($("qmsg"), false, err); return; } postPdf("/docs/quotes/preview", b, pdfTab(), $("qmsg")); return; }
      if (t.id === "qsave") {
        var b2 = body(), err2 = check(b2); if (err2) { if (err2 !== "stop") K.say($("qmsg"), false, err2); return; }
        var w = pdfTab(); t.disabled = true;
        K.call("POST", "/docs/quotes" + (ed && ed.id ? "?rid=" + ed.id : ""), b2).then(function (r) {
          K.say($("qmsg"), true, "Saved " + r.number + " · " + K.inr(r.total)); showUrl(w, api("/docs/" + r.id + "/file"));
          setTimeout(function () { go("register"); }, 1200);
        }).catch(function (er) { if (w) w.close(); t.disabled = false; K.say($("qmsg"), false, er.message); });
      }
    };
    if (d) {
      $("qlines").innerHTML = d.lines.map(qLine).join("");
      $("qcg").checked = !!d.apply_cgst; $("qsg").checked = !!d.apply_sgst; $("qig").checked = !!d.apply_igst; calc();
    } else { applyTemplate(tpl); autoTax(); }
  };

  // ---------------------------------------------------------------- letter
  VIEW.letter = function (arg) {
    var ed = arg && arg.edit, d = ed ? ed.data : null;
    var h = '<div class="card"><div class="inv-top"><h3>' + (ed ? "Edit letter " + K.esc(ed.number) : "New letter on letterhead") + "</h3>" +
      (ed ? "" : '<label class="muted2">Template <select id="ltpl">' + M.letter_templates.map(function (t) { return opt(t.key, t.name); }).join("") + "</select></label>") + "</div>" +
      '<div class="frm"><label>Date<input type="date" id="ldate" value="' + K.esc(ed ? ed.doc_date : M.today) + '"></label>' +
      '<label>Signatory name<input id="lsign" maxlength="120" value="' + K.esc(d ? d.signatory : (K.me.name || "")) + '"></label>' +
      '<label>Designation<input id="ldesig" maxlength="120" value="' + K.esc(d ? d.designation : "") + '"></label>' +
      '<label class="wide">To (name and address, one per line)<textarea id="lto" rows="3" maxlength="800">' + K.esc(d ? d.to_text : "") + "</textarea></label>" +
      '<label class="wide">Subject<input id="lsubj" maxlength="200" value="' + K.esc(d ? d.subject : "") + '"></label>' +
      '<label class="wide">Letter text — blank line = new paragraph, "- " = bullet, **bold**<textarea id="lbody" rows="16" maxlength="12000" class="lbody">' + K.esc(d ? d.body : "") + "</textarea></label>" +
      '<label class="wide">Why / for whom (required, not printed)<input id="lpurpose" maxlength="200" placeholder="e.g. KYC request to Sunrise Hospital" value="' + K.esc(d ? d.purpose : "") + '"></label></div>' +
      '<p class="note" id="lph" hidden></p>' +
      '<div class="bar" style="margin-top:12px"><button type="button" class="abtn g" id="lprev">Preview PDF</button><button type="button" class="abtn" id="lsave">' + (ed ? "Save changes" : "Save letter") + '</button><button type="button" class="abtn g" data-dsub="register">Back</button></div><p class="msg" id="lmsg"></p></div>';
    shell(h);
    function apply(t) { $("lsubj").value = t.subject; $("lbody").value = t.body; showPh(); }
    function body() { return { to_text: $("lto").value.trim(), subject: $("lsubj").value.trim(), body: $("lbody").value, letter_date: $("ldate").value,
      purpose: $("lpurpose").value.trim(), template: $("ltpl") ? $("ltpl").value : (d && d.template) || "", signatory: $("lsign").value.trim(), designation: $("ldesig").value.trim() }; }
    function showPh() {
      var ph = placeholders($("lbody").value + " " + $("lsubj").value + " " + $("lto").value);
      $("lph").hidden = !ph.length;
      $("lph").innerHTML = ph.length ? "Fill these before saving: <b>" + ph.map(K.esc).join(", ") + "</b>" : "";
    }
    S.change = function (e) { if (e.target.id === "ltpl") { var t = M.letter_templates.filter(function (x) { return x.key === e.target.value; })[0]; if (t) apply(t); } };
    S.input = function () { showPh(); };
    S.click = function (e) {
      var t = e.target, b = body();
      if (t.id !== "lprev" && t.id !== "lsave") return;
      if (b.purpose.length < 3) { K.say($("lmsg"), false, "Write why / for whom this letter is made (this keeps the record)."); return; }
      if (t.id === "lprev") { postPdf("/docs/letters/preview", b, pdfTab(), $("lmsg")); return; }
      if (placeholders(b.body + b.subject + b.to_text).length) { showPh(); K.say($("lmsg"), false, "Replace the [placeholders] first."); return; }
      var w = pdfTab(); t.disabled = true;
      K.call("POST", "/docs/letters" + (ed ? "?rid=" + ed.id : ""), b).then(function (r) {
        K.say($("lmsg"), true, "Saved " + r.number); showUrl(w, api("/docs/" + r.id + "/file")); setTimeout(function () { go("register"); }, 1200);
      }).catch(function (er) { if (w) w.close(); t.disabled = false; K.say($("lmsg"), false, er.message); });
    };
    if (!ed) apply(M.letter_templates[0]); else showPh();
  };

  // ---------------------------------------------------------------- blank letterhead
  VIEW.blank = function () {
    var h = '<div class="card"><h3>Blank letterhead</h3><p class="muted2">For printing and writing by hand, or typing in Word. Each download gets its own number (printed small at the bottom) and is recorded with your name and the reason, so every letterhead that leaves the office can be traced.</p>' +
      '<form id="bf" class="frm"><label class="wide">Why do you need it? (required)<input name="purpose" required minlength="3" maxlength="200" placeholder="e.g. Handwritten reply to bank, tender cover letter"></label>' +
      '<label>For whom / addressed to<input name="recipient" maxlength="160"></label>' +
      '<label>Format<select name="fmt">' + opt("pdf", "PDF (print)") + opt("docx", "Word (.docx, to type)") + "</select></label>" +
      '<label>Pages (PDF)<input name="copies" type="number" min="1" max="20" value="1"></label>' +
      '<button class="abtn" type="submit">Create &amp; download</button></form><p class="msg" id="bmsg"></p></div>';
    shell(h);
    $("bf").onsubmit = function (e) {
      e.preventDefault();
      var f = e.target, w = f.fmt.value === "pdf" ? pdfTab() : null;
      K.call("POST", "/docs/blank", { purpose: f.purpose.value.trim(), recipient: f.recipient.value.trim(), fmt: f.fmt.value, copies: Number(f.copies.value || 1) }).then(function (r) {
        K.say($("bmsg"), true, "Created " + r.number + " — recorded in All documents.");
        if (w) showUrl(w, api("/docs/" + r.id + "/file")); else location.href = api("/docs/" + r.id + "/file");
      }).catch(function (er) { if (w) w.close(); K.say($("bmsg"), false, er.message); });
    };
  };

  window.ATE_DOCS = function (kit) { K = kit; M = null; go(S.sub || "register"); };
})();
