/* Agile Tech Expert - Billing & inventory (loaded by the staff portal; admin + accounts roles).
   The server recalculates every amount; totals shown while typing are a preview. */
(function () {
  "use strict";
  var K, S = { sub: "invoices" };
  var SUBS = [
    { id: "invoices", label: "Invoices" }, { id: "new", label: "+ New invoice" }, { id: "receipts", label: "Receipts" },
    { id: "accounts", label: "Accounts & ledger" }, { id: "inventory", label: "Inventory & stock" }, { id: "reports", label: "Reports" },
    { id: "settings", label: "Company settings", admin: true }
  ];
  var CATS = { hardware: "Hardware (HW)", software: "Software (SW)", service: "Service (SV)" };
  var GST_RATES = [0, 5, 12, 18, 28];
  var UNITS = ["pcs", "nos", "set", "box", "mtr", "kg", "job", "hrs", "month", "year", "license", "user"];
  var META = [["delivery_note", "Delivery Note"], ["payment_terms", "Mode/Terms of Payment"], ["supplier_ref", "Supplier's Ref."],
    ["other_ref", "Other Reference(s)"], ["buyer_order_no", "Buyer's Order No."], ["buyer_order_date", "Buyer's Order Date", "date"],
    ["despatch_doc_no", "Despatch Document No."], ["delivery_note_date", "Delivery Note Date", "date"],
    ["despatched_through", "Despatched through"], ["destination", "Destination"], ["terms_of_delivery", "Terms of Delivery"]];

  function $(id) { return document.getElementById(id); }
  // "5000*4", "2 x 3", "1500+250" -> number; plain numbers pass through
  function calcNum(v) {
    var t = String(v == null ? "" : v).replace(/,/g, "").replace(/[x×]/gi, "*").trim();
    if (!t) return 0;
    if (!/^[\d.\s+\-*/()]+$/.test(t)) return NaN;
    try { var n = Function('"use strict";return (' + t + ")")(); return isFinite(n) ? n : NaN; } catch (e) { return NaN; }
  }
  function r2(n) { return Math.round((Number(n) + Number.EPSILON) * 100) / 100; }
  function opt(v, label, sel) { return '<option value="' + K.esc(v) + '"' + (sel ? " selected" : "") + ">" + K.esc(label) + "</option>"; }
  function api(path) { return K.api + path; }
  function statusPill(s) {
    var m = { paid: "good", partial: "warn", unpaid: "warn", cancelled: "off", ok: "good" };
    return '<span class="pill ' + (m[s] || "") + '">' + K.esc(s === "ok" ? "valid" : s) + "</span>";
  }
  function stateOptions(sel) {
    return opt("", "— select state —") + Object.keys(S.states).map(function (c) { return opt(S.states[c], c + " · " + S.states[c], S.states[c] === sel); }).join("");
  }
  function itemLabel(it) { return it.code + " · " + it.name; }
  function findItem(text) {
    var t = String(text || "").trim().toLowerCase();
    if (!t) return null;
    return S.items.filter(function (it) {
      return it.active && (itemLabel(it).toLowerCase() === t || it.code.toLowerCase() === t || it.name.toLowerCase() === t);
    })[0] || null;
  }
  function sameState(p) {
    var me = S.settings || {};
    if (!p) return true;
    var pc = p.state_code || (p.gstin || "").slice(0, 2);
    if (pc && me.state_code) return pc === me.state_code;
    return !p.state || p.state.trim().toLowerCase() === String(me.state || "").trim().toLowerCase();
  }
  function fyList() {
    var d = new Date(), y = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1, out = [];
    for (var i = 0; i < 6; i++) { var s = y - i; out.push(s + "-" + String((s + 1) % 100).padStart(2, "0")); }
    return out;
  }
  // open a tab first (so the browser doesn't block it), then point it at the PDF
  function pdfTab() { try { return window.open("about:blank", "_blank"); } catch (e) { return null; } }
  function showPdf(w, url) { if (w && !w.closed) w.location.href = url; else window.open(url, "_blank", "noopener"); }

  function load() {
    return Promise.all([K.get("/billing/settings"), K.get("/billing/parties"), K.get("/billing/items")]).then(function (r) {
      S.settings = r[0].settings; S.today = r[0].today; S.fy = r[0].fy; S.states = r[0].states; S.formats = r[0].formats;
      S.nextInvoice = r[0].next_invoice; S.parties = r[1].items; S.items = r[2].items;
    });
  }

  function shell(inner) {
    var tabs = SUBS.filter(function (t) { return !t.admin || K.me.role === "admin"; }).map(function (t) {
      return '<button type="button" class="abtn ' + (t.id === S.sub ? "" : "g") + '" data-sub="' + t.id + '">' + K.esc(t.label) + "</button>";
    }).join("");
    K.main.innerHTML = K.head("Billing & inventory", "Tax invoices, receipts, account ledgers, stock with serial numbers, and GST reports. Every entry is saved with who made it.") +
      '<div class="bar bsubs">' + tabs + "</div>" + inner;
  }

  function go(sub, arg) {
    S.sub = sub; S.click = S.change = S.input = S.keydown = null;
    K.main.onclick = function (e) {
      var b = e.target.closest("[data-sub]");
      if (b) { go(b.getAttribute("data-sub")); return; }
      if (S.click) S.click(e);
    };
    K.main.onchange = function (e) { if (S.change) S.change(e); };
    K.main.oninput = function (e) { if (S.input) S.input(e); };
    K.main.onkeydown = function (e) { if (S.keydown) S.keydown(e); };
    K.loading();
    load().then(function () { VIEW[sub](arg); }).catch(K.fail);
  }

  var VIEW = {};

  // ============================================================= invoices list
  VIEW.invoices = function () {
    K.get("/billing/invoices").then(function (d) {
      var inv = d.items, due = 0, open = 0;
      inv.forEach(function (x) { if (x.status === "unpaid" || x.status === "partial") { due += x.total - x.paid; open++; } });
      var h = '<div class="kpis">' + K.kpi("Outstanding", K.inr(due), K.num(open) + " invoices not fully paid", due ? "warn" : "good") +
        K.kpi("Invoices", K.num(inv.length), "next no. " + K.esc(S.nextInvoice)) + K.kpi("Accounts", K.num(S.parties.length)) + K.kpi("Items in inventory", K.num(S.items.length)) + "</div>";
      h += '<div class="bar"><input type="search" id="bq" placeholder="Search invoice number or account"><select id="bst">' +
        opt("", "All statuses") + opt("unpaid", "Unpaid") + opt("partial", "Partly paid") + opt("paid", "Paid") + opt("cancelled", "Cancelled") + "</select></div>";
      h += '<div class="tblw"><table class="tbl"><thead><tr><th>Invoice</th><th>Date</th><th>Account</th><th class="num">Taxable</th><th class="num">GST</th><th class="num">Total</th><th class="num">Received</th><th>Status</th><th></th></tr></thead><tbody id="btb"></tbody></table></div><p class="msg" id="bim"></p>';
      shell(h);
      function draw() {
        var q = $("bq").value.trim().toLowerCase(), st = $("bst").value;
        var rows = inv.filter(function (x) { return (!st || x.status === st) && (!q || (x.number + " " + x.party + " " + x.party_code).toLowerCase().indexOf(q) >= 0); });
        $("btb").innerHTML = rows.length ? rows.map(function (x) {
          return "<tr><td><b>" + K.esc(x.number) + "</b>" + (x.updated_at ? '<br><span class="muted2">edited</span>' : "") + "</td><td>" + K.esc(x.inv_date) + "</td><td>" + K.esc(x.party) + ' <span class="muted2">' + K.esc(x.party_code) +
            '</span></td><td class="num">' + K.inr(x.subtotal) + '</td><td class="num">' + K.inr(x.cgst + x.sgst + x.igst) + '</td><td class="num"><b>' + K.inr(x.total) +
            '</b></td><td class="num">' + K.inr(x.paid) + "</td><td>" + statusPill(x.status) + '</td><td class="acts">' +
            '<a class="abtn sm g" target="_blank" rel="noopener" href="' + api("/billing/invoices/" + x.id + "/pdf") + '">PDF</a> ' +
            (x.status !== "cancelled" ? '<button class="abtn sm g" type="button" data-edit="' + x.id + '">Edit</button> ' : "") +
            (x.status === "unpaid" || x.status === "partial" ? '<button class="abtn sm" type="button" data-pay="' + x.id + '">Receive</button> ' : "") +
            (x.status !== "cancelled" && !x.paid ? '<button class="abtn sm r" type="button" data-cancel="' + x.id + '">Cancel</button>' : "") + "</td></tr>";
        }).join("") : '<tr><td colspan="9" class="empty">No invoices yet. Click <b>+ New invoice</b>.</td></tr>';
      }
      draw();
      S.input = S.change = function (e) { if (e.target.id === "bq" || e.target.id === "bst") draw(); };
      S.click = function (e) {
        var t = e.target;
        if (t.getAttribute("data-edit")) { go("new", { edit: Number(t.getAttribute("data-edit")) }); return; }
        if (t.getAttribute("data-pay")) { var x = inv.filter(function (i) { return String(i.id) === t.getAttribute("data-pay"); })[0]; go("receipts", { party_id: x.party_id, invoice_id: x.id, amount: r2(x.total - x.paid) }); return; }
        if (t.getAttribute("data-cancel")) {
          if (!confirm("Cancel this invoice? It stays in the records as CANCELLED, and its stock and serial numbers are returned.")) return;
          K.call("POST", "/billing/invoices/" + t.getAttribute("data-cancel") + "/cancel").then(function () { go("invoices"); })
            .catch(function (er) { K.say($("bim"), false, er.message); });
        }
      };
    }).catch(K.fail);
  };

  // ============================================================= new / edit invoice
  function lineRow(ln) {
    ln = ln || {};
    var it = ln.item_id ? S.items.filter(function (x) { return x.id === ln.item_id; })[0] : null;
    var unit = ln.unit || "pcs", gst = ln.gst_rate != null ? Number(ln.gst_rate) : 18;
    var gstOpts = GST_RATES.indexOf(gst) < 0 ? GST_RATES.concat([gst]) : GST_RATES;
    var unitOpts = UNITS.indexOf(unit) < 0 ? UNITS.concat([unit]) : UNITS;
    return '<tr class="ln" data-item="' + (it ? it.id : "") + '">' +
      '<td class="sl"></td>' +
      '<td class="itemcell"><input data-f="pick" list="dlItems" placeholder="Type item code or name…" autocomplete="off" value="' + K.esc(it ? itemLabel(it) : (ln.name || "")) + '">' +
      '<div class="linfo"></div>' +
      '<textarea data-f="description" rows="2" placeholder="Details printed under the item (model, specs, warranty)…">' + K.esc(ln.description || "") + "</textarea>" +
      '<input data-f="serials" placeholder="Serial No(s) — separate with commas" value="' + K.esc(ln.serials || "") + '"><div class="chips"></div>' +
      '<label class="chk addinv" hidden><input type="checkbox" data-f="add_to_inventory"> Add to inventory as <select data-f="category">' +
      Object.keys(CATS).map(function (c) { return opt(c, CATS[c]); }).join("") + "</select></label></td>" +
      '<td><input data-f="hsn" placeholder="HSN/SAC" value="' + K.esc(ln.hsn || "") + '"></td>' +
      '<td><select data-f="gst_rate">' + gstOpts.map(function (g) { return opt(g, g + "%", g === gst); }).join("") + "</select></td>" +
      '<td><input data-f="qty" class="calc" inputmode="decimal" autocomplete="off" value="' + (ln.qty != null ? ln.qty : 1) + '"></td>' +
      '<td><select data-f="unit">' + unitOpts.map(function (u) { return opt(u, u.toUpperCase(), u === unit); }).join("") + "</select></td>" +
      '<td><input data-f="rate" class="calc" inputmode="decimal" autocomplete="off" placeholder="e.g. 5000 or 5000*4" value="' + (ln.rate != null ? ln.rate : "") + '"></td>' +
      '<td><input data-f="discount_pct" class="calc" inputmode="decimal" autocomplete="off" placeholder="0" value="' + (ln.discount_pct ? ln.discount_pct : "") + '"></td>' +
      '<td class="num amtcell"><b data-out="amount">0.00</b><div data-out="calc" class="calcline"></div><div data-out="tax" class="taxlines"></div></td>' +
      '<td><button type="button" class="abtn sm r" data-del aria-label="Remove item">✕</button></td></tr>';
  }

  VIEW.new = function (arg) {
    arg = arg || {};
    if (!S.parties.length) {
      shell('<div class="note">Create an account (customer) first. Every invoice belongs to an account so its full history stays in one ledger.</div>' + partyForm());
      bindPartyForm(function () { go("new"); }); return;
    }
    if (arg.edit) {
      K.get("/billing/invoices/" + arg.edit).then(function (d) { invoiceForm(d); }).catch(K.fail);
    } else invoiceForm(null);
  };

  function invoiceForm(ed) {
    var inv = ed ? ed.invoice : {}, meta = inv.meta || {};
    var dueDays = ed && inv.due_date ? Math.round((new Date(inv.due_date) - new Date(inv.inv_date)) / 864e5) : 15;
    var parties = S.parties.filter(function (p) { return p.active || p.id === inv.party_id; });
    var h = '<div class="card inv-card"><div class="inv-top"><h3>' + (ed ? "Edit tax invoice " + K.esc(inv.number) : "New tax invoice") + "</h3>" +
      '<span class="invno">Invoice No. <b id="nno">' + K.esc(ed ? inv.number : S.nextInvoice) + "</b></span></div>" +
      (ed && inv.paid ? '<div class="note">Already received ' + K.inr(inv.paid) + " against this invoice — the new total cannot be lower than that.</div>" : "") +
      '<div class="frm"><label>Account (buyer)<select id="nparty">' + parties.map(function (p) {
        return opt(p.id, p.code + " · " + p.name + (p.state ? " (" + p.state + ")" : ""), p.id === inv.party_id);
      }).join("") + '</select><a href="#" data-sub="accounts" class="mini">+ new account</a></label>' +
      '<label>Invoice date<input type="date" id="ndate" value="' + K.esc(inv.inv_date || S.today) + '"></label>' +
      '<label>Due in days<input type="number" id="ndue" min="0" max="365" value="' + dueDays + '"></label>' +
      '<label>Place of supply<select id="npos">' + stateOptions(inv.place_of_supply) + "</select></label></div>" +
      '<div class="taxbox"><b>GST to apply</b> <span class="muted2" id="ntaxhint"></span><br>' +
      '<label class="chk"><input type="checkbox" id="ncg"> CGST</label><label class="chk"><input type="checkbox" id="nsg"> SGST</label>' +
      '<label class="chk"><input type="checkbox" id="nig"> IGST</label></div>' +
      '<details class="more"' + (Object.keys(meta).length || inv.ship_to ? " open" : "") + '><summary>Order &amp; delivery details (optional — printed in the invoice header)</summary><div class="frm">' +
      META.map(function (m) { return "<label>" + K.esc(m[1]) + '<input data-meta="' + m[0] + '" type="' + (m[2] || "text") + '" maxlength="120" value="' + K.esc(meta[m[0]] || "") + '"></label>'; }).join("") +
      '<label class="wide">Consignee (Ship to) — only if different from the buyer<textarea id="nship" rows="2" maxlength="600">' + K.esc(inv.ship_to || "") + "</textarea></label></div></details>" +
      '<h4 class="sech">Items</h4><div class="tblw"><table class="tbl lines"><thead><tr><th>#</th><th>Item &amp; details</th><th>HSN/SAC</th><th>GST</th><th>Qty</th><th>Unit</th><th>Rate ₹</th><th>Disc %</th><th class="num">Amount</th><th></th></tr></thead><tbody id="nlines">' +
      (ed ? ed.lines.map(lineRow).join("") : lineRow()) + "</tbody></table></div>" +
      '<datalist id="dlItems">' + S.items.filter(function (x) { return x.active; }).map(function (x) { return '<option value="' + K.esc(itemLabel(x)) + '">'; }).join("") + "</datalist>" +
      '<div class="addrow"><button type="button" class="abtn" id="nadd">+ Add another item</button><span class="muted2">Tip: press Enter in the Rate box to add the next item.</span></div>' +
      '<div class="inv-bottom"><label class="frm-one">Remarks (printed on invoice)<textarea id="nnotes" rows="3" maxlength="1000">' + K.esc(inv.notes || "") + '</textarea></label><div class="totals" id="ntot"></div></div>' +
      '<div class="bar" style="margin-top:14px"><button type="button" class="abtn g" id="nprev">Preview PDF</button><button type="button" class="abtn" id="nsave">' + (ed ? "Save changes" : "Save invoice") + "</button>" +
      (ed ? '<button type="button" class="abtn g" data-sub="invoices">Back</button>' : "") + '<span class="muted2">Amounts are checked again on the server before saving.</span></div><p class="msg" id="nmsg"></p></div>';
    shell(h);

    function party() { var id = $("nparty").value; return S.parties.filter(function (p) { return String(p.id) === id; })[0]; }
    function autoTax(keepPos) {
      var p = party(), same = sameState(p);
      $("ncg").checked = same; $("nsg").checked = same; $("nig").checked = !same;
      if (!keepPos) $("npos").value = (p && p.state) || S.settings.state || "";
      $("ntaxhint").textContent = same ? "(buyer in our state → CGST + SGST pre-ticked; change if needed)" : "(buyer in another state → IGST pre-ticked; change if needed)";
      calc();
    }
    function rowItem(tr) { var id = tr.getAttribute("data-item"); return id ? S.items.filter(function (x) { return String(x.id) === id; })[0] : null; }
    function g(tr, f) { return tr.querySelector('[data-f="' + f + '"]'); }
    function rowData(tr) {
      var it = rowItem(tr), pick = g(tr, "pick").value.trim();
      return { item_id: it ? it.id : null, name: it ? it.name : pick, description: g(tr, "description").value.trim(), serials: g(tr, "serials").value.trim(),
        hsn: g(tr, "hsn").value.trim(), unit: g(tr, "unit").value, qty: calcNum(g(tr, "qty").value), rate: calcNum(g(tr, "rate").value),
        discount_pct: calcNum(g(tr, "discount_pct").value), gst_rate: Number(g(tr, "gst_rate").value),
        add_to_inventory: !it && g(tr, "add_to_inventory").checked, category: g(tr, "category").value };
    }
    function rowInfo(tr) {
      var it = rowItem(tr), info = tr.querySelector(".linfo"), pick = g(tr, "pick").value.trim();
      tr.querySelector(".addinv").hidden = !!it || !pick;
      if (it) {
        info.innerHTML = '<span class="pill">' + K.esc(it.code) + "</span> " + (it.track_stock ? (it.track_serial ? K.num(it.serials_in_stock) + " serials in stock" : "stock " + it.stock + " " + K.esc(it.unit)) : "stock not tracked") +
          (it.track_serial ? ' · <b>serial no. required</b>' : "");
      } else info.innerHTML = pick ? '<span class="pill warn">not in inventory</span>' : "";
      var chips = tr.querySelector(".chips");
      chips.innerHTML = "";
      if (it && it.track_stock) {
        K.get("/billing/items/" + it.id + "/serials?status=in_stock").then(function (r) {
          var have = g(tr, "serials").value.toLowerCase();
          chips.innerHTML = r.items.slice(0, 40).map(function (s) {
            return '<button type="button" class="chip' + (have.indexOf(s.serial.toLowerCase()) >= 0 ? " on" : "") + '" data-ser="' + K.esc(s.serial) + '">' + K.esc(s.serial) + "</button>";
          }).join("");
        }).catch(function () {});
      }
    }
    function pickItem(tr) {
      var it = findItem(g(tr, "pick").value);
      tr.setAttribute("data-item", it ? it.id : "");
      if (it) {
        g(tr, "pick").value = itemLabel(it);
        g(tr, "hsn").value = it.hsn || "";
        g(tr, "rate").value = it.price;
        if (!g(tr, "description").value.trim()) g(tr, "description").value = it.description || "";
        var gs = g(tr, "gst_rate");
        if (!Array.prototype.some.call(gs.options, function (o) { return Number(o.value) === it.gst_rate; })) gs.insertAdjacentHTML("beforeend", opt(it.gst_rate, it.gst_rate + "%"));
        gs.value = String(it.gst_rate);
        var us = g(tr, "unit"), u = (it.unit || "pcs").toLowerCase();
        if (!Array.prototype.some.call(us.options, function (o) { return o.value === u; })) us.insertAdjacentHTML("beforeend", opt(u, u.toUpperCase()));
        us.value = u;
      }
      rowInfo(tr); calc();
    }
    function calc() {
      var cg = $("ncg").checked, sg = $("nsg").checked, ig = $("nig").checked, T = { sub: 0, c: 0, s: 0, i: 0 }, n = 0;
      K.main.querySelectorAll("#nlines tr.ln").forEach(function (tr) {
        tr.querySelector(".sl").textContent = ++n;
        var d = rowData(tr), bad = isNaN(d.qty) || isNaN(d.rate) || isNaN(d.discount_pct);
        tr.classList.toggle("badnum", bad);
        if (bad) { d.qty = d.qty || 0; d.rate = d.rate || 0; d.discount_pct = d.discount_pct || 0; }
        var gross = r2(d.qty * d.rate), disc = r2(gross * d.discount_pct / 100), tx = r2(gross - disc), half = d.gst_rate / 2;
        var c = cg ? r2(tx * d.gst_rate / 200) : 0, s = sg ? r2(tx * d.gst_rate / 200) : 0, i = ig ? r2(tx * d.gst_rate / 100) : 0;
        var money = function (v) { return K.inr(v).replace("₹", ""); };
        tr.querySelector('[data-out="amount"]').textContent = money(tx);
        tr.querySelector('[data-out="calc"]').innerHTML = bad ? '<span class="neg">check the number</span>' :
          K.esc(String(+d.qty.toFixed(3))) + " × " + money(d.rate) + (disc ? " − " + d.discount_pct + "%" : "") + " = " + money(tx);
        tr.querySelector('[data-out="tax"]').innerHTML = (cg ? "<span>CGST " + half + "%: " + money(c) + "</span>" : "") +
          (sg ? "<span>SGST " + half + "%: " + money(s) + "</span>" : "") + (ig ? "<span>IGST " + d.gst_rate + "%: " + money(i) + "</span>" : "") +
          ((c + s + i) ? "<span><b>Item total: " + money(tx + c + s + i) + "</b></span>" : "");
        T.sub += tx; T.c += c; T.s += s; T.i += i;
      });
      var gross = r2(T.sub + T.c + T.s + T.i), round = S.settings.round_off === "1" ? r2(Math.round(gross) - gross) : 0;
      $("ntot").innerHTML = "<div><span>Taxable value</span><b>" + K.inr(T.sub) + "</b></div>" +
        (cg ? "<div><span>CGST</span><b>" + K.inr(T.c) + "</b></div>" : "") + (sg ? "<div><span>SGST</span><b>" + K.inr(T.s) + "</b></div>" : "") +
        (ig ? "<div><span>IGST</span><b>" + K.inr(T.i) + "</b></div>" : "") +
        (round ? "<div><span>Round off</span><b>" + K.inr(round) + "</b></div>" : "") +
        '<div class="grand"><span>Total</span><b>' + K.inr(gross + round) + "</b></div>";
    }
    function addRow(focus) {
      $("nlines").insertAdjacentHTML("beforeend", lineRow());
      var tr = $("nlines").lastElementChild;
      calc();
      if (focus) g(tr, "pick").focus();
    }
    function body() {
      var lines = [];
      K.main.querySelectorAll("#nlines tr.ln").forEach(function (tr) { var d = rowData(tr); if (d.item_id || d.name) lines.push(d); });
      var meta = {};
      K.main.querySelectorAll("[data-meta]").forEach(function (el) { if (el.value.trim()) meta[el.getAttribute("data-meta")] = el.value.trim(); });
      return { party_id: Number($("nparty").value), inv_date: $("ndate").value, due_days: Number($("ndue").value || 0), place_of_supply: $("npos").value,
        apply_cgst: $("ncg").checked, apply_sgst: $("nsg").checked, apply_igst: $("nig").checked, notes: $("nnotes").value.trim(),
        ship_to: $("nship").value.trim(), meta: meta, lines: lines };
    }
    function check(b) {
      if (!b.lines.length) return "Add at least one item.";
      for (var i = 0; i < b.lines.length; i++) {
        if (isNaN(b.lines[i].qty) || isNaN(b.lines[i].rate) || isNaN(b.lines[i].discount_pct)) return "Item " + (i + 1) + ": quantity, rate or discount is not a valid number.";
        if (!(b.lines[i].qty > 0)) return "Item " + (i + 1) + ": quantity must be more than 0.";
      }
      return "";
    }

    S.change = function (e) {
      var t = e.target;
      if (t.id === "nparty") { autoTax(false); return; }
      if (t.id === "ndate" && !ed) { K.get("/billing/next-number?inv_date=" + encodeURIComponent(t.value)).then(function (r) { $("nno").textContent = r.number; }).catch(function () {}); return; }
      if (t.getAttribute("data-f") === "pick") { pickItem(t.closest("tr")); return; }
      if (t.classList.contains("calc") && /[*x×+\/()-]/i.test(t.value.replace(/^-/, ""))) {
        var v = calcNum(t.value); if (!isNaN(v)) t.value = String(r2(v));
      }
      calc();
    };
    S.input = function (e) {
      var t = e.target;
      if (t.getAttribute("data-f") === "pick") {
        var tr = t.closest("tr");
        if (findItem(t.value)) pickItem(tr); else { tr.setAttribute("data-item", ""); rowInfo(tr); }
      }
      if (t.closest("#nlines")) calc();
    };
    S.keydown = function (e) {
      if (e.key === "Enter" && e.target.getAttribute("data-f") === "rate") {
        e.preventDefault();
        var tr = e.target.closest("tr");
        if (!tr.nextElementSibling) addRow(true); else g(tr.nextElementSibling, "pick").focus();
      }
    };
    S.click = function (e) {
      var t = e.target;
      if (t.hasAttribute("data-del")) { if (K.main.querySelectorAll("#nlines tr.ln").length > 1) t.closest("tr").remove(); calc(); return; }
      if (t.getAttribute("data-ser")) {
        var inp = t.closest("td").querySelector('[data-f="serials"]'), s = t.getAttribute("data-ser");
        var list = inp.value.split(/[,\n;]+/).map(function (x) { return x.trim(); }).filter(Boolean);
        var i = list.map(function (x) { return x.toLowerCase(); }).indexOf(s.toLowerCase());
        if (i >= 0) list.splice(i, 1); else list.push(s);
        inp.value = list.join(", "); t.classList.toggle("on", i < 0);
        var tr = t.closest("tr"), q = g(tr, "qty"); if (list.length && rowItem(tr) && rowItem(tr).track_serial) q.value = list.length;
        calc(); return;
      }
      if (t.id === "nadd") { addRow(true); return; }
      if (t.id === "nprev") {
        var b = body(), err = check(b); if (err) { K.say($("nmsg"), false, err); return; }
        var w = pdfTab();
        fetch(api("/billing/invoices/preview" + (ed ? "?invoice_id=" + inv.id : "")), { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) })
          .then(function (r) { if (!r.ok) return r.json().then(function (x) { throw new Error(x.detail || "Preview failed"); }); return r.blob(); })
          .then(function (bl) { showPdf(w, URL.createObjectURL(bl)); K.say($("nmsg"), true, "Preview opened in a new tab (not saved)."); })
          .catch(function (er) { if (w) w.close(); K.say($("nmsg"), false, er.message); });
        return;
      }
      if (t.id === "nsave") {
        var b2 = body(), err2 = check(b2); if (err2) { K.say($("nmsg"), false, err2); return; }
        t.disabled = true;
        var w2 = pdfTab();
        K.call(ed ? "PUT" : "POST", "/billing/invoices" + (ed ? "/" + inv.id : ""), b2).then(function (r) {
          K.say($("nmsg"), true, (ed ? "Updated " : "Saved ") + r.number + " · " + K.inr(r.total) + (r.new_items.length ? " · added to inventory: " + r.new_items.join(", ") : ""));
          showPdf(w2, api("/billing/invoices/" + r.id + "/pdf"));
          setTimeout(function () { go("invoices"); }, 1300);
        }).catch(function (er) { if (w2) w2.close(); t.disabled = false; K.say($("nmsg"), false, er.message); });
      }
    };
    if (ed) {
      $("ncg").checked = !!inv.apply_cgst; $("nsg").checked = !!inv.apply_sgst; $("nig").checked = !!inv.apply_igst;
      $("ntaxhint").textContent = "";
      K.main.querySelectorAll("#nlines tr.ln").forEach(rowInfo);
      calc();
    } else autoTax(false);
  }

  // ============================================================= receipts
  VIEW.receipts = function (pre) {
    pre = pre || {};
    K.get("/billing/receipts").then(function (d) {
      var h = '<div class="card"><h3>Record a payment received</h3><form id="rf" class="frm">' +
        '<label>Account<select name="party_id" id="rparty" required>' + S.parties.map(function (p) { return opt(p.id, p.code + " · " + p.name, p.id === pre.party_id); }).join("") + "</select></label>" +
        '<label>Against invoice<select name="invoice_id" id="rinv"></select></label>' +
        '<label>Amount ₹<input name="amount" type="number" min="0.01" step="0.01" required value="' + (pre.amount || "") + '"></label>' +
        '<label>Date<input name="rcp_date" type="date" value="' + S.today + '"></label>' +
        '<label>Mode<select name="mode">' + ["bank", "upi", "cash", "cheque", "card", "other"].map(function (m) { return opt(m, m.toUpperCase()); }).join("") + "</select></label>" +
        '<label>Reference (UTR / cheque no)<input name="reference" maxlength="80"></label>' +
        '<label class="wide">Notes<input name="notes" maxlength="500"></label>' +
        '<button class="abtn" type="submit"' + (S.parties.length ? "" : " disabled") + '>Save receipt</button></form><p class="msg" id="rmsg"></p></div>';
      h += '<div class="tblw"><table class="tbl"><thead><tr><th>Receipt</th><th>Date</th><th>Account</th><th>Invoice</th><th>Mode</th><th class="num">Amount</th><th>Status</th><th></th></tr></thead><tbody>' +
        (d.items.length ? d.items.map(function (x) {
          return "<tr><td><b>" + K.esc(x.number) + "</b></td><td>" + K.esc(x.rcp_date) + "</td><td>" + K.esc(x.party) + "</td><td>" + K.esc(x.invoice_number || "On account") +
            "</td><td>" + K.esc((x.mode || "").toUpperCase()) + (x.reference ? '<br><span class="muted2">' + K.esc(x.reference) + "</span>" : "") + '</td><td class="num"><b>' + K.inr(x.amount) +
            "</b></td><td>" + statusPill(x.status) + '</td><td class="acts"><a class="abtn sm g" target="_blank" rel="noopener" href="' + api("/billing/receipts/" + x.id + "/pdf") + '">PDF</a> ' +
            (x.status === "ok" ? '<button class="abtn sm r" type="button" data-rc="' + x.id + '">Cancel</button>' : "") + "</td></tr>";
        }).join("") : '<tr><td colspan="8" class="empty">No receipts yet.</td></tr>') + "</tbody></table></div>";
      shell(h);
      function fillInv() {
        K.get("/billing/invoices?party_id=" + $("rparty").value).then(function (r) {
          var open = r.items.filter(function (x) { return x.status === "unpaid" || x.status === "partial"; });
          $("rinv").innerHTML = opt("", "On account (no invoice)") + open.map(function (x) {
            return opt(x.id, x.number + " · due " + K.inr(x.total - x.paid), x.id === pre.invoice_id);
          }).join("");
        });
      }
      if (S.parties.length) fillInv();
      S.change = function (e) { if (e.target.id === "rparty") { pre = {}; fillInv(); } };
      $("rf").onsubmit = function (e) {
        e.preventDefault();
        var f = e.target, b = { party_id: Number(f.party_id.value), invoice_id: f.invoice_id.value ? Number(f.invoice_id.value) : null,
          amount: Number(f.amount.value), rcp_date: f.rcp_date.value, mode: f.mode.value, reference: f.reference.value.trim(), notes: f.notes.value.trim() };
        var w = pdfTab();
        K.call("POST", "/billing/receipts", b).then(function (r) {
          K.say($("rmsg"), true, "Saved " + r.number);
          showPdf(w, api("/billing/receipts/" + r.id + "/pdf"));
          setTimeout(function () { go("receipts"); }, 1000);
        }).catch(function (er) { if (w) w.close(); K.say($("rmsg"), false, er.message); });
      };
      S.click = function (e) {
        var id = e.target.getAttribute("data-rc");
        if (id && confirm("Cancel this receipt? It stays in the records as cancelled.")) {
          K.call("POST", "/billing/receipts/" + id + "/cancel").then(function () { go("receipts"); }).catch(function (er) { K.say($("rmsg"), false, er.message); });
        }
      };
    }).catch(K.fail);
  };

  // ============================================================= accounts + ledger
  function partyForm(p) {
    p = p || {};
    return '<div class="card"><h3>' + (p.id ? "Edit account " + K.esc(p.code) : "New account (customer)") + '</h3><form id="pf" class="frm" data-id="' + (p.id || "") + '">' +
      '<label>Name / company<input name="name" required maxlength="160" value="' + K.esc(p.name) + '"></label>' +
      '<label>GSTIN<input name="gstin" id="pgstin" maxlength="15" value="' + K.esc(p.gstin) + '" placeholder="Leave blank if unregistered" style="text-transform:uppercase"></label>' +
      '<label>State<select name="state" id="pstate">' + stateOptions(p.state) + "</select></label>" +
      '<label>Phone<input name="phone" maxlength="25" value="' + K.esc(p.phone) + '"></label>' +
      '<label>Email<input name="email" type="email" maxlength="160" value="' + K.esc(p.email) + '"></label>' +
      '<label>Opening balance ₹<input name="opening_balance" type="number" step="0.01" value="' + (p.opening_balance || 0) + '"></label>' +
      '<label class="wide">Billing address (printed on the invoice)<textarea name="address" rows="3" maxlength="600">' + K.esc(p.address) + "</textarea></label>" +
      '<button class="abtn" type="submit">' + (p.id ? "Save changes" : "Create account") + "</button>" +
      (p.id ? '<button class="abtn g" type="button" data-sub="accounts">Cancel</button>' : "") + '</form><p class="msg" id="pmsg"></p></div>';
  }
  function bindPartyForm(after) {
    var gi = $("pgstin");
    gi.oninput = function () {
      var c = gi.value.trim().slice(0, 2);
      if (/^\d\d$/.test(c) && S.states[c]) $("pstate").value = S.states[c];
    };
    $("pf").onsubmit = function (e) {
      e.preventDefault();
      var f = e.target, id = f.getAttribute("data-id"), b = {};
      ["name", "gstin", "state", "phone", "email", "address"].forEach(function (k) { b[k] = f[k].value.trim(); });
      b.gstin = b.gstin.toUpperCase();
      var code = Object.keys(S.states).filter(function (c) { return S.states[c] === b.state; })[0] || "";
      b.state_code = b.gstin ? b.gstin.slice(0, 2) : code;
      b.opening_balance = Number(f.opening_balance.value || 0);
      if (b.gstin && !/^[0-9]{2}[A-Z0-9]{13}$/.test(b.gstin)) { K.say($("pmsg"), false, "GSTIN should be 15 characters (starts with the 2-digit state code)."); return; }
      K.call(id ? "PATCH" : "POST", "/billing/parties" + (id ? "/" + id : ""), b).then(function (r) {
        K.say($("pmsg"), true, id ? "Saved." : "Created " + r.code); setTimeout(after, 700);
      }).catch(function (er) { K.say($("pmsg"), false, er.message); });
    };
  }

  VIEW.accounts = function (editId) {
    var editing = S.parties.filter(function (p) { return p.id === editId; })[0];
    var h = partyForm(editing) + '<div class="tblw"><table class="tbl"><thead><tr><th>Code</th><th>Account</th><th>GSTIN</th><th>State</th><th class="num">Balance</th><th></th></tr></thead><tbody>' +
      (S.parties.length ? S.parties.map(function (p) {
        return "<tr><td><b>" + K.esc(p.code) + "</b></td><td>" + K.esc(p.name) + (p.phone ? '<br><span class="muted2">' + K.esc(p.phone) + "</span>" : "") + "</td><td>" + K.esc(p.gstin || "Unregistered") +
          "</td><td>" + K.esc(p.state || "—") + '</td><td class="num"><b>' + K.inr(p.balance) + '</b></td><td class="acts"><button class="abtn sm" type="button" data-led="' + p.id + '">Ledger</button> ' +
          '<button class="abtn sm g" type="button" data-pedit="' + p.id + '">Edit</button></td></tr>';
      }).join("") : '<tr><td colspan="6" class="empty">No accounts yet.</td></tr>') + '</tbody></table></div><div id="ledger"></div>';
    shell(h);
    bindPartyForm(function () { go("accounts"); });
    S.click = function (e) {
      var t = e.target;
      if (t.getAttribute("data-pedit")) { go("accounts", Number(t.getAttribute("data-pedit"))); return; }
      if (t.getAttribute("data-led")) { showLedger(Number(t.getAttribute("data-led"))); return; }
      if (t.id === "lgo") showLedger(Number(t.getAttribute("data-p")), $("lfrom").value, $("lto").value);
    };
    if (editing) $("pf").scrollIntoView({ block: "start" });
  };

  function showLedger(pid, from, to) {
    var qs = "?dfrom=" + encodeURIComponent(from || "") + "&dto=" + encodeURIComponent(to || "");
    K.get("/billing/parties/" + pid + "/ledger" + qs).then(function (d) {
      var p = d.party, h = '<div class="card" style="margin-top:16px"><h3>Ledger · ' + K.esc(p.name) + " (" + K.esc(p.code) + ")</h3>" +
        '<div class="bar"><label class="muted2">From <input type="date" id="lfrom" value="' + K.esc(from || "") + '"></label><label class="muted2">To <input type="date" id="lto" value="' + K.esc(to || "") + '"></label>' +
        '<button class="abtn sm" type="button" id="lgo" data-p="' + pid + '">Show</button>' +
        '<a class="abtn sm g" target="_blank" rel="noopener" href="' + api("/billing/parties/" + pid + "/ledger.pdf" + qs) + '">PDF</a>' +
        '<a class="abtn sm g" href="' + api("/billing/parties/" + pid + "/ledger.csv" + qs) + '">CSV</a></div>' +
        '<div class="tblw"><table class="tbl"><thead><tr><th>Date</th><th>Particulars</th><th>Ref</th><th class="num">Debit</th><th class="num">Credit</th><th class="num">Balance</th></tr></thead><tbody>' +
        '<tr><td></td><td><i>Opening balance</i></td><td></td><td></td><td></td><td class="num">' + K.inr(d.opening) + "</td></tr>" +
        d.rows.map(function (r) {
          return "<tr><td>" + K.esc(r.date) + "</td><td>" + K.esc(r.particulars) + "</td><td>" + K.esc(r.ref) + '</td><td class="num">' + (r.debit ? K.inr(r.debit) : "") +
            '</td><td class="num">' + (r.credit ? K.inr(r.credit) : "") + '</td><td class="num">' + K.inr(r.balance) + "</td></tr>";
        }).join("") + '<tr><td></td><td><b>Closing balance</b></td><td></td><td></td><td></td><td class="num"><b>' + K.inr(d.closing) + "</b></td></tr></tbody></table></div>" +
        '<p class="muted2">Debit = invoiced, Credit = received. Positive balance = the customer owes us.</p></div>';
      $("ledger").innerHTML = h;
      $("ledger").scrollIntoView({ behavior: "smooth", block: "start" });
    }).catch(function (er) { $("ledger").innerHTML = '<p class="msg err">' + K.esc(er.message) + "</p>"; });
  }

  // ============================================================= inventory + stock
  var STOCK_REASONS = [["purchase", "Purchase (stock in)"], ["return", "Customer return (in)"], ["opening", "Opening stock (in)"],
    ["correction", "Correction (in)"], ["damage", "Damaged / scrapped (out)"], ["correction-out", "Correction (out)"], ["used", "Used internally (out)"]];
  var OUT = ["damage", "correction-out", "used", "lost"];

  VIEW.inventory = function (editId) {
    var it = S.items.filter(function (x) { return x.id === editId; })[0] || {};
    var h = '<div class="inv-grid"><div class="card"><h3>' + (it.id ? "Edit " + K.esc(it.code) : "Add product / service") + '</h3><form id="if" class="frm" data-id="' + (it.id || "") + '">' +
      '<label>Name (printed on invoice)<input name="name" required maxlength="160" value="' + K.esc(it.name) + '" placeholder="e.g. DESKTOP"></label>' +
      '<label>Category<select name="category"' + (it.id ? " disabled" : "") + ">" + Object.keys(CATS).map(function (c) { return opt(c, CATS[c], c === it.category); }).join("") + "</select></label>" +
      '<label>HSN / SAC<input name="hsn" maxlength="10" value="' + K.esc(it.hsn) + '"></label>' +
      '<label>Unit<select name="unit">' + UNITS.map(function (u) { return opt(u, u.toUpperCase(), u === (it.unit || "pcs")); }).join("") + "</select></label>" +
      '<label>Sale rate ₹ (before GST)<input name="price" type="number" min="0" step="0.01" value="' + (it.price != null ? it.price : "") + '" required></label>' +
      '<label>GST %<input name="gst_rate" type="number" min="0" max="28" step="0.01" value="' + (it.gst_rate != null ? it.gst_rate : 18) + '"></label>' +
      '<label class="wide">Details (model, specs, warranty — printed under the name)<textarea name="description" rows="2" maxlength="600" placeholder="HP 280 G9&#10;i5 14th Gen, 8 GB, 512 GB SSD, Win 11 Pro, 3 Year warranty">' + K.esc(it.description) + "</textarea></label>" +
      '<label class="chk"><input type="checkbox" name="track_stock"' + (it.track_stock || !it.id ? " checked" : "") + "> Track stock</label>" +
      '<label class="chk"><input type="checkbox" name="track_serial"' + (it.track_serial ? " checked" : "") + "> Track serial numbers (one per piece)</label>" +
      (it.id ? "" : '<label>Opening stock (if no serials)<input name="stock" type="number" step="any" value="0"></label>') +
      '<button class="abtn" type="submit">' + (it.id ? "Save" : "Add item") + "</button>" + (it.id ? '<button class="abtn g" type="button" data-sub="inventory">Cancel</button>' : "") +
      '</form><p class="muted2">Code is given automatically: HW-0001 hardware, SW-0001 software, SV-0001 services.</p><p class="msg" id="imsg"></p></div>';
    h += '<div class="card" id="stockCard"><h3>Stock in / out</h3><form id="sf" class="frm">' +
      '<label>Item<select name="item">' + S.items.map(function (x) { return opt(x.id, itemLabel(x) + (x.track_serial ? " (serials)" : "")); }).join("") + "</select></label>" +
      '<label>Type<select name="reason">' + STOCK_REASONS.map(function (r) { return opt(r[0], r[1]); }).join("") + "</select></label>" +
      '<label>Quantity<input name="qty" type="number" step="any" min="0" placeholder="auto from serials"></label>' +
      '<label>Purchase rate ₹<input name="rate" type="number" step="0.01" min="0"></label>' +
      '<label>Supplier<input name="supplier" maxlength="120"></label><label>Bill / ref no.<input name="ref" maxlength="80"></label>' +
      '<label class="wide">Serial numbers — one per line (a barcode scanner adds one line per scan)<textarea name="serials" rows="4"></textarea></label>' +
      '<button class="abtn" type="submit"' + (S.items.length ? "" : " disabled") + '>Save stock entry</button></form><p class="msg" id="smsg"></p></div></div>';
    h += '<div class="bar"><input type="search" id="iq" placeholder="Search code, name or details"></div><div class="tblw"><table class="tbl"><thead><tr><th>Code</th><th>Name &amp; details</th><th>HSN/SAC</th><th class="num">Rate</th><th class="num">GST</th><th class="num">Stock</th><th></th></tr></thead><tbody id="itb"></tbody></table></div><div id="moves"></div>';
    shell(h);
    function draw() {
      var q = $("iq").value.trim().toLowerCase();
      var rows = S.items.filter(function (x) { return !q || (x.code + " " + x.name + " " + (x.description || "")).toLowerCase().indexOf(q) >= 0; });
      $("itb").innerHTML = rows.length ? rows.map(function (x) {
        return "<tr><td><b>" + K.esc(x.code) + "</b></td><td><b>" + K.esc(x.name) + "</b>" + (x.description ? '<br><span class="muted2">' + K.esc(x.description).replace(/\n/g, "<br>") + "</span>" : "") +
          "</td><td>" + K.esc(x.hsn || "—") + '</td><td class="num">' + K.inr(x.price) + '</td><td class="num">' + x.gst_rate +
          '%</td><td class="num">' + (x.track_stock ? '<b class="' + (x.stock <= 0 ? "neg" : "") + '">' + x.stock + "</b> " + K.esc(x.unit) + (x.track_serial ? '<br><span class="pill">S/N</span>' : "") : '<span class="muted2">not tracked</span>') +
          '</td><td class="acts"><button class="abtn sm" type="button" data-stk="' + x.id + '">Stock in/out</button> <button class="abtn sm g" type="button" data-ied="' + x.id + '">Edit</button> <button class="abtn sm g" type="button" data-mv="' + x.id + '">History</button></td></tr>';
      }).join("") : '<tr><td colspan="7" class="empty">No items yet.</td></tr>';
    }
    draw();
    S.input = function (e) { if (e.target.id === "iq") draw(); };
    $("if").onsubmit = function (e) {
      e.preventDefault();
      var f = e.target, id = f.getAttribute("data-id");
      var b = { name: f.name.value.trim(), category: f.category.value, hsn: f.hsn.value.trim(), unit: f.unit.value, description: f.description.value.trim(),
        price: Number(f.price.value || 0), gst_rate: Number(f.gst_rate.value || 0), track_stock: f.track_stock.checked, track_serial: f.track_serial.checked,
        stock: f.stock ? Number(f.stock.value || 0) : 0 };
      K.call(id ? "PATCH" : "POST", "/billing/items" + (id ? "/" + id : ""), b).then(function (r) {
        K.say($("imsg"), true, id ? "Saved." : "Added " + r.code); setTimeout(function () { go("inventory"); }, 700);
      }).catch(function (er) { K.say($("imsg"), false, er.message); });
    };
    $("sf").onsubmit = function (e) {
      e.preventDefault();
      var f = e.target, reason = f.reason.value, q = Number(f.qty.value || 0);
      if (OUT.indexOf(reason) >= 0) q = -Math.abs(q);
      var b = { qty: q, reason: reason, rate: f.rate.value ? Number(f.rate.value) : null, supplier: f.supplier.value.trim(), ref: f.ref.value.trim(), serials: f.serials.value };
      K.call("POST", "/billing/items/" + f.item.value + "/stock", b).then(function (r) {
        K.say($("smsg"), true, "Saved. Stock now " + r.stock + "."); setTimeout(function () { go("inventory"); }, 900);
      }).catch(function (er) { K.say($("smsg"), false, er.message); });
    };
    S.click = function (e) {
      var t = e.target;
      if (t.getAttribute("data-ied")) { go("inventory", Number(t.getAttribute("data-ied"))); return; }
      if (t.getAttribute("data-stk")) { $("sf").item.value = t.getAttribute("data-stk"); $("stockCard").scrollIntoView({ behavior: "smooth" }); $("sf").qty.focus(); return; }
      if (t.getAttribute("data-mv")) {
        var id = t.getAttribute("data-mv");
        Promise.all([K.get("/billing/items/" + id + "/moves"), K.get("/billing/items/" + id + "/serials")]).then(function (r) {
          var mv = r[0].items, sn = r[1].items;
          $("moves").innerHTML = '<div class="card" style="margin-top:14px"><h3>Stock history</h3><div class="tblw"><table class="tbl"><thead><tr><th>When</th><th class="num">Qty</th><th>Type</th><th>Ref / serials</th><th>Supplier</th><th>By</th></tr></thead><tbody>' +
            (mv.length ? mv.map(function (m) { return "<tr><td>" + K.esc((m.at || "").replace("T", " ").slice(0, 16)) + '</td><td class="num">' + (m.qty > 0 ? "+" : "") + m.qty + "</td><td>" + K.esc(m.reason) + "</td><td>" + K.esc(m.ref) + "</td><td>" + K.esc(m.supplier || "") + "</td><td>" + K.esc(m.by_user) + "</td></tr>"; }).join("")
              : '<tr><td colspan="6" class="empty">No stock movement.</td></tr>') + "</tbody></table></div>" +
            (sn.length ? '<h3 style="margin-top:14px">Serial numbers</h3><div class="tblw"><table class="tbl"><thead><tr><th>Serial</th><th>Status</th><th>Invoice</th></tr></thead><tbody>' +
              sn.map(function (s) { return "<tr><td><b>" + K.esc(s.serial) + "</b></td><td>" + statusPill(s.status === "in_stock" ? "in stock" : s.status) + "</td><td>" + K.esc(s.invoice || "") + "</td></tr>"; }).join("") + "</tbody></table></div>" : "") + "</div>";
          $("moves").scrollIntoView({ behavior: "smooth" });
        });
      }
    };
    if (it.id) $("if").scrollIntoView({ block: "start" });
  };

  // ============================================================= reports
  VIEW.reports = function (sel) {
    sel = sel || { fy: S.fy, period: "FY" };
    var periods = { Q1: "Q1 (Apr–Jun)", Q2: "Q2 (Jul–Sep)", Q3: "Q3 (Oct–Dec)", Q4: "Q4 (Jan–Mar)", H1: "Half year 1 (Apr–Sep)", H2: "Half year 2 (Oct–Mar)", FY: "Full year" };
    K.get("/billing/report?fy=" + sel.fy + "&period=" + sel.period).then(function (r) {
      var qs = "?fy=" + sel.fy + "&period=" + sel.period, t = r.totals;
      var h = '<div class="bar"><select id="rfy">' + fyList().map(function (f) { return opt(f, "FY " + f, f === sel.fy); }).join("") + "</select>" +
        '<select id="rper">' + Object.keys(periods).map(function (k) { return opt(k, periods[k], k === sel.period); }).join("") + "</select>" +
        '<a class="abtn sm g" target="_blank" rel="noopener" href="' + api("/billing/report.pdf" + qs) + '">PDF</a>' +
        '<a class="abtn sm g" href="' + api("/billing/report.csv" + qs) + '">CSV (invoice register)</a><span class="muted2">' + K.esc(r.from) + " to " + K.esc(r.to) + "</span></div>";
      h += '<div class="kpis">' + K.kpi("Invoiced (total)", K.inr(t.total), K.num(r.invoices) + " invoices" + (r.cancelled ? " · " + r.cancelled + " cancelled" : "")) +
        K.kpi("Taxable value", K.inr(t.subtotal)) + K.kpi("GST collected", K.inr(t.cgst + t.sgst + t.igst), "CGST " + K.inr(t.cgst) + " · SGST " + K.inr(t.sgst) + " · IGST " + K.inr(t.igst)) +
        K.kpi("Received", K.inr(r.received), Object.keys(r.received_by_mode).map(function (m) { return m.toUpperCase() + " " + K.inr(r.received_by_mode[m]); }).join(" · "), "good") +
        K.kpi("Outstanding today", K.inr(r.outstanding_now), "all accounts", r.outstanding_now > 0 ? "warn" : "good") + "</div>";
      var months = Object.keys(r.months);
      h += '<div class="tblw"><table class="tbl"><thead><tr><th>Month</th><th class="num">Invoices</th><th class="num">Taxable</th><th class="num">GST</th><th class="num">Total</th><th class="num">Received</th></tr></thead><tbody>' +
        (months.length ? months.map(function (m) { var v = r.months[m]; return "<tr><td>" + K.esc(m) + '</td><td class="num">' + v.invoices + '</td><td class="num">' + K.inr(v.taxable) + '</td><td class="num">' + K.inr(v.tax) + '</td><td class="num"><b>' + K.inr(v.total) + '</b></td><td class="num">' + K.inr(v.received) + "</td></tr>"; }).join("")
          : '<tr><td colspan="6" class="empty">Nothing in this period.</td></tr>') + "</tbody></table></div>";
      var cats = Object.keys(r.by_category);
      if (cats.length) h += '<p class="muted2" style="margin-top:10px">Taxable value by category: ' + cats.map(function (c) { return K.esc(c) + " " + K.inr(r.by_category[c]); }).join(" · ") + "</p>";
      shell(h);
      S.change = function (e) { if (e.target.id === "rfy" || e.target.id === "rper") go("reports", { fy: $("rfy").value, period: $("rper").value }); };
    }).catch(K.fail);
  };

  // ============================================================= settings
  VIEW.settings = function () {
    var s = S.settings;
    var F = [["company_name", "Company name (as on GST certificate)"], ["gstin", "GSTIN"], ["pan", "PAN"], ["cin", "CIN (optional)"],
      ["phone", "Phone"], ["email", "Email"], ["bank_name", "Bank name"], ["bank_account", "Account number"], ["bank_ifsc", "IFSC"],
      ["bank_branch", "Branch"], ["bank_address", "Branch address"], ["upi", "UPI ID"], ["invoice_prefix", "Invoice prefix"], ["receipt_prefix", "Receipt prefix"]];
    var h = '<div class="card"><h3>Printed on every invoice and receipt</h3><form id="cf" class="frm">' +
      F.map(function (f) { return "<label>" + f[1] + '<input name="' + f[0] + '" value="' + K.esc(s[f[0]]) + '" maxlength="200"></label>'; }).join("") +
      '<label>State<select name="state">' + stateOptions(s.state) + "</select></label>" +
      '<label>Invoice number format<select name="invoice_format">' + S.formats.map(function (f) { return opt(f.value, f.example, f.value === s.invoice_format); }).join("") + "</select></label>" +
      '<label>Start numbering from<input name="invoice_start" type="number" min="1" value="' + K.esc(s.invoice_start || "1") + '"></label>' +
      '<label class="wide">Registered address<textarea name="address" rows="3" maxlength="600">' + K.esc(s.address) + "</textarea></label>" +
      '<label class="wide">Declaration<textarea name="declaration" rows="2" maxlength="600">' + K.esc(s.declaration) + "</textarea></label>" +
      '<label class="wide">Terms (printed under the declaration)<input name="terms" value="' + K.esc(s.terms) + '" maxlength="600"></label>' +
      '<label class="chk"><input type="checkbox" name="round_off"' + (s.round_off === "1" ? " checked" : "") + "> Round total to nearest rupee</label>" +
      '<label class="chk"><input type="checkbox" name="upi_qr"' + (s.upi_qr !== "0" ? " checked" : "") + "> Print UPI pay QR (with amount) on invoices</label>" +
      '<div class="wide stampbox"><b>Company stamp / signature</b> <span class="muted2">PNG or JPG, printed above "Authorised Signatory". Transparent PNG looks best.</span><br>' +
      '<img id="stampImg" alt="" ' + (s.stamp ? 'src="' + K.esc(s.stamp) + '"' : "hidden") + '><input type="file" id="stampFile" accept="image/png,image/jpeg"> ' +
      '<button type="button" class="abtn sm r" id="stampDel"' + (s.stamp ? "" : " hidden") + ">Remove</button></div>" +
      '<button class="abtn" type="submit">Save settings</button></form><p class="muted2">Next invoice number: <b>' + K.esc(S.nextInvoice) + "</b>. Numbers restart every financial year (April). Changing the format affects new invoices only.</p><p class=\"msg\" id=\"cmsg\"></p></div>";
    shell(h);
    var stamp = s.stamp || "";
    $("stampFile").onchange = function () {
      var file = this.files[0]; if (!file) return;
      var rd = new FileReader();
      rd.onload = function () {
        var img = new Image();
        img.onload = function () {
          var k = Math.min(1, 400 / Math.max(img.width, img.height)), c = document.createElement("canvas");
          c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
          c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
          stamp = c.toDataURL("image/png");
          $("stampImg").src = stamp; $("stampImg").hidden = false; $("stampDel").hidden = false;
        };
        img.src = rd.result;
      };
      rd.readAsDataURL(file);
    };
    S.click = function (e) { if (e.target.id === "stampDel") { stamp = ""; $("stampImg").hidden = true; e.target.hidden = true; } };
    $("cf").onsubmit = function (e) {
      e.preventDefault();
      var f = e.target, v = {};
      F.forEach(function (x) { v[x[0]] = f[x[0]].value.trim(); });
      ["address", "declaration", "terms", "invoice_format", "invoice_start", "state"].forEach(function (k) { v[k] = f[k].value.trim(); });
      v.state_code = Object.keys(S.states).filter(function (c) { return S.states[c] === v.state; })[0] || s.state_code;
      v.round_off = f.round_off.checked ? "1" : "0";
      v.upi_qr = f.upi_qr.checked ? "1" : "0";
      v.stamp = stamp;
      K.call("PUT", "/billing/settings", { values: v }).then(function () { K.say($("cmsg"), true, "Saved."); setTimeout(function () { go("settings"); }, 700); })
        .catch(function (er) { K.say($("cmsg"), false, er.message); });
    };
  };

  window.ATE_BILLING = function (kit) {
    K = kit;
    go(S.sub || "invoices");
  };
})();
