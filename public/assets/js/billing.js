/* Agile Tech Expert - Billing & inventory (loaded by the staff portal; admin + accounts roles).
   The server recalculates every amount; the totals shown while typing are only a preview. */
(function () {
  "use strict";
  var K, S = { sub: "invoices", settings: null, parties: [], items: [] };
  var SUBS = [
    { id: "invoices", label: "Invoices" }, { id: "new", label: "+ New invoice" }, { id: "receipts", label: "Receipts" },
    { id: "accounts", label: "Accounts & ledger" }, { id: "inventory", label: "Inventory" }, { id: "reports", label: "Reports" },
    { id: "settings", label: "Company settings", admin: true }
  ];
  var CATS = { hardware: "Hardware (HW)", software: "Software (SW)", service: "Service (SV)" };
  var GST_RATES = [0, 5, 12, 18, 28];

  function $(id) { return document.getElementById(id); }
  function r2(n) { return Math.round((Number(n) + Number.EPSILON) * 100) / 100; }
  function opt(v, label, sel) { return '<option value="' + K.esc(v) + '"' + (sel ? " selected" : "") + ">" + K.esc(label) + "</option>"; }
  function pdf(path) { return K.api + path; }
  function statusPill(s) {
    var m = { paid: "good", partial: "warn", unpaid: "warn", cancelled: "off", ok: "good" };
    return '<span class="pill ' + (m[s] || "") + '">' + K.esc(s === "ok" ? "valid" : s) + "</span>";
  }
  function sameState(p) {
    var me = S.settings || {};
    if (!p) return true;
    if (p.state_code && me.state_code) return p.state_code === me.state_code;
    if (!p.state) return true;
    return p.state.trim().toLowerCase() === String(me.state || "").trim().toLowerCase();
  }
  function fyList() {
    var d = new Date(), y = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1, out = [];
    for (var i = 0; i < 6; i++) { var s = y - i; out.push(s + "-" + String((s + 1) % 100).padStart(2, "0")); }
    return out;
  }

  function load() {
    return Promise.all([K.get("/billing/settings"), K.get("/billing/parties"), K.get("/billing/items")]).then(function (r) {
      S.settings = r[0].settings; S.today = r[0].today; S.fy = r[0].fy;
      S.parties = r[1].items; S.items = r[2].items;
    });
  }

  function shell(inner) {
    var tabs = SUBS.filter(function (t) { return !t.admin || K.me.role === "admin"; }).map(function (t) {
      return '<button type="button" class="abtn ' + (t.id === S.sub ? "" : "g") + '" data-sub="' + t.id + '">' + K.esc(t.label) + "</button>";
    }).join("");
    K.main.innerHTML = K.head("Billing & inventory", "GST invoices, receipts, account ledgers, stock and reports. Every entry is saved with who made it.") +
      '<div class="bar bsubs">' + tabs + "</div>" + inner;
  }

  function go(sub, arg) {
    S.sub = sub; S.arg = arg;
    K.main.onclick = K.main.onchange = K.main.oninput = null;
    K.loading();
    load().then(function () { VIEW[sub](arg); }).catch(K.fail);
  }

  function bindSubs() {
    var prev = K.main.onclick;
    K.main.onclick = function (e) {
      var b = e.target.closest("[data-sub]");
      if (b) { go(b.getAttribute("data-sub")); return; }
      if (prev) prev(e);
    };
  }

  var VIEW = {};

  // ------------------------------------------------------------- invoices list
  VIEW.invoices = function () {
    K.get("/billing/invoices").then(function (d) {
      var inv = d.items, due = 0, open = 0;
      inv.forEach(function (x) { if (x.status === "unpaid" || x.status === "partial") { due += x.total - x.paid; open++; } });
      var h = '<div class="kpis">' + K.kpi("Outstanding", K.inr(due), K.num(open) + " invoices not fully paid", due ? "warn" : "good") +
        K.kpi("Invoices", K.num(inv.length)) + K.kpi("Accounts", K.num(S.parties.length)) + K.kpi("Items in inventory", K.num(S.items.length)) + "</div>";
      h += '<div class="bar"><input type="search" id="bq" placeholder="Search invoice number or account"><select id="bst">' +
        opt("", "All statuses") + opt("unpaid", "Unpaid") + opt("partial", "Partly paid") + opt("paid", "Paid") + opt("cancelled", "Cancelled") + "</select></div>";
      h += '<div class="tblw"><table class="tbl"><thead><tr><th>Invoice</th><th>Date</th><th>Account</th><th class="num">Taxable</th><th class="num">GST</th><th class="num">Total</th><th class="num">Received</th><th>Status</th><th></th></tr></thead><tbody id="btb"></tbody></table></div><p class="msg" id="bim"></p>';
      shell(h);
      function draw() {
        var q = $("bq").value.trim().toLowerCase(), st = $("bst").value;
        var rows = inv.filter(function (x) { return (!st || x.status === st) && (!q || (x.number + " " + x.party + " " + x.party_code).toLowerCase().indexOf(q) >= 0); });
        $("btb").innerHTML = rows.length ? rows.map(function (x) {
          return "<tr><td><b>" + K.esc(x.number) + "</b></td><td>" + K.esc(x.inv_date) + "</td><td>" + K.esc(x.party) + ' <span class="muted2">' + K.esc(x.party_code) +
            '</span></td><td class="num">' + K.inr(x.subtotal) + '</td><td class="num">' + K.inr(x.cgst + x.sgst + x.igst) + '</td><td class="num"><b>' + K.inr(x.total) +
            '</b></td><td class="num">' + K.inr(x.paid) + "</td><td>" + statusPill(x.status) + '</td><td class="acts">' +
            '<a class="abtn sm g" target="_blank" rel="noopener" href="' + pdf("/billing/invoices/" + x.id + "/pdf") + '">PDF</a> ' +
            (x.status === "unpaid" || x.status === "partial" ? '<button class="abtn sm" type="button" data-pay="' + x.id + '">Receive</button> ' : "") +
            (x.status !== "cancelled" && !x.paid ? '<button class="abtn sm r" type="button" data-cancel="' + x.id + '">Cancel</button>' : "") + "</td></tr>";
        }).join("") : '<tr><td colspan="9" class="empty">No invoices yet. Click <b>+ New invoice</b>.</td></tr>';
      }
      draw();
      $("bq").oninput = draw; $("bst").onchange = draw;
      K.main.onclick = function (e) {
        var t = e.target;
        if (t.getAttribute("data-pay")) { var x = inv.filter(function (i) { return String(i.id) === t.getAttribute("data-pay"); })[0]; go("receipts", { party_id: x.party_id, invoice_id: x.id, amount: r2(x.total - x.paid) }); return; }
        if (t.getAttribute("data-cancel")) {
          if (!confirm("Cancel this invoice? It stays in the records as cancelled and stock is returned.")) return;
          K.call("POST", "/billing/invoices/" + t.getAttribute("data-cancel") + "/cancel").then(function () { go("invoices"); })
            .catch(function (er) { K.say($("bim"), false, er.message); });
        }
      };
      bindSubs();
    }).catch(K.fail);
  };

  // ------------------------------------------------------------- new invoice
  function lineRow(i) {
    var items = S.items.filter(function (x) { return x.active; });
    return '<tr data-line="' + i + '"><td><select data-f="item_id" aria-label="Item"><option value="">Manual entry</option>' +
      items.map(function (x) { return opt(x.id, x.code + " · " + x.name + (x.track_stock ? " (stock " + x.stock + ")" : "")); }).join("") + "</select>" +
      '<input data-f="name" placeholder="Item / description" aria-label="Description">' +
      '<label class="chk addinv"><input type="checkbox" data-f="add_to_inventory"> Add to inventory as <select data-f="category">' +
      Object.keys(CATS).map(function (c) { return opt(c, CATS[c]); }).join("") + "</select></label></td>" +
      '<td><input data-f="hsn" placeholder="HSN/SAC" size="7"></td>' +
      '<td><input data-f="qty" type="number" min="0.01" step="any" value="1" class="w70"></td>' +
      '<td><input data-f="rate" type="number" min="0" step="0.01" placeholder="0.00" class="w100"></td>' +
      '<td><select data-f="gst_rate">' + GST_RATES.map(function (g) { return opt(g, g + "%", g === 18); }).join("") + "</select></td>" +
      '<td class="num" data-out="taxable">0.00</td><td class="num" data-out="tax">0.00</td><td class="num" data-out="total"><b>0.00</b></td>' +
      '<td><button type="button" class="abtn sm r" data-del="' + i + '" aria-label="Remove line">✕</button></td></tr>';
  }

  VIEW.new = function () {
    if (!S.parties.length) {
      shell('<div class="note">Create an account (customer) first. Every invoice belongs to an account so its full history stays in one ledger.</div>' + partyForm());
      bindPartyForm(function () { go("new"); }); bindSubs(); return;
    }
    var h = '<div class="card"><h3>New GST invoice</h3><form id="nf" class="frm">' +
      '<label>Account<select name="party_id" id="nparty" required>' + S.parties.filter(function (p) { return p.active; }).map(function (p) {
        return opt(p.id, p.code + " · " + p.name + (p.state ? " (" + p.state + ")" : ""));
      }).join("") + "</select></label>" +
      '<label>Invoice date<input type="date" name="inv_date" value="' + S.today + '" required></label>' +
      '<label>Due in days<input type="number" name="due_days" min="0" max="365" value="15"></label>' +
      '<label>Place of supply<input name="place_of_supply" id="npos" placeholder="State"></label>' +
      '<div class="wide taxbox"><b>GST to apply</b> <span class="muted2" id="ntaxhint"></span><br>' +
      '<label class="chk"><input type="checkbox" id="ncg"> CGST</label><label class="chk"><input type="checkbox" id="nsg"> SGST</label>' +
      '<label class="chk"><input type="checkbox" id="nig"> IGST</label></div></form>' +
      '<div class="tblw" style="margin-top:12px"><table class="tbl lines"><thead><tr><th>Item (pick from inventory or type)</th><th>HSN/SAC</th><th>Qty</th><th>Rate ₹</th><th>GST</th><th class="num">Taxable</th><th class="num">Tax</th><th class="num">Amount</th><th></th></tr></thead><tbody id="nlines">' +
      lineRow(0) + '</tbody></table></div><button type="button" class="abtn g" id="nadd" style="margin-top:8px">+ Add line</button>' +
      '<div class="totals" id="ntot"></div>' +
      '<label class="frm-one">Notes (printed on invoice)<input id="nnotes" maxlength="1000" placeholder="optional"></label>' +
      '<div class="bar" style="margin-top:12px"><button type="button" class="abtn" id="nsave">Save invoice</button><span class="muted2">Totals are checked again on the server before saving.</span></div><p class="msg" id="nmsg"></p></div>';
    shell(h);
    var n = 1;
    function party() { var id = $("nparty").value; return S.parties.filter(function (p) { return String(p.id) === id; })[0]; }
    function autoTax() {
      var p = party(), same = sameState(p);
      $("ncg").checked = same; $("nsg").checked = same; $("nig").checked = !same;
      $("npos").value = (p && p.state) || S.settings.state || "";
      $("ntaxhint").textContent = same ? "(same state as us: CGST + SGST pre-ticked — change if needed)" : "(other state: IGST pre-ticked — change if needed)";
      calc();
    }
    function rowData(tr) {
      var g = function (f) { return tr.querySelector('[data-f="' + f + '"]'); };
      return { item_id: g("item_id").value ? Number(g("item_id").value) : null, name: g("name").value.trim(), hsn: g("hsn").value.trim(),
        qty: Number(g("qty").value || 0), rate: Number(g("rate").value || 0), gst_rate: Number(g("gst_rate").value),
        add_to_inventory: !g("item_id").value && g("add_to_inventory").checked, category: g("category").value };
    }
    function calc() {
      var cg = $("ncg").checked, sg = $("nsg").checked, ig = $("nig").checked, T = { sub: 0, c: 0, s: 0, i: 0 };
      K.main.querySelectorAll("#nlines tr").forEach(function (tr) {
        var d = rowData(tr), tx = r2(d.qty * d.rate);
        var c = cg ? r2(tx * d.gst_rate / 200) : 0, s = sg ? r2(tx * d.gst_rate / 200) : 0, i = ig ? r2(tx * d.gst_rate / 100) : 0;
        tr.querySelector('[data-out="taxable"]').textContent = tx.toFixed(2);
        tr.querySelector('[data-out="tax"]').textContent = (c + s + i).toFixed(2);
        tr.querySelector('[data-out="total"]').innerHTML = "<b>" + (tx + c + s + i).toFixed(2) + "</b>";
        tr.querySelector(".addinv").hidden = !!d.item_id;
        T.sub += tx; T.c += c; T.s += s; T.i += i;
      });
      var gross = r2(T.sub + T.c + T.s + T.i), round = S.settings.round_off === "1" ? r2(Math.round(gross) - gross) : 0;
      $("ntot").innerHTML = "<div><span>Taxable value</span><b>" + K.inr(T.sub) + "</b></div>" +
        "<div" + (cg ? "" : ' class="off"') + "><span>CGST</span><b>" + K.inr(T.c) + "</b></div>" +
        "<div" + (sg ? "" : ' class="off"') + "><span>SGST</span><b>" + K.inr(T.s) + "</b></div>" +
        "<div" + (ig ? "" : ' class="off"') + "><span>IGST</span><b>" + K.inr(T.i) + "</b></div>" +
        (round ? "<div><span>Round off</span><b>" + K.inr(round) + "</b></div>" : "") +
        '<div class="grand"><span>Total</span><b>' + K.inr(gross + round) + "</b></div>";
    }
    $("nparty").onchange = autoTax;
    ["ncg", "nsg", "nig"].forEach(function (id) { $(id).onchange = calc; });
    K.main.oninput = function (e) { if (e.target.closest("#nlines")) calc(); };
    K.main.onchange = function (e) {
      var t = e.target;
      if (t.getAttribute("data-f") === "item_id") {
        var tr = t.closest("tr"), it = S.items.filter(function (x) { return String(x.id) === t.value; })[0];
        if (it) {
          tr.querySelector('[data-f="name"]').value = it.name;
          tr.querySelector('[data-f="hsn"]').value = it.hsn || "";
          tr.querySelector('[data-f="rate"]').value = it.price;
          var g = tr.querySelector('[data-f="gst_rate"]');
          if (!Array.prototype.some.call(g.options, function (o) { return Number(o.value) === it.gst_rate; })) g.insertAdjacentHTML("beforeend", opt(it.gst_rate, it.gst_rate + "%"));
          g.value = String(it.gst_rate);
        }
      }
      calc();
    };
    $("nadd").onclick = function () { $("nlines").insertAdjacentHTML("beforeend", lineRow(n++)); calc(); };
    K.main.onclick = function (e) {
      var del = e.target.getAttribute("data-del");
      if (del != null) { if ($("nlines").children.length > 1) e.target.closest("tr").remove(); calc(); return; }
      var b = e.target.closest("[data-sub]"); if (b) go(b.getAttribute("data-sub"));
    };
    $("nsave").onclick = function () {
      var f = $("nf"), lines = [];
      K.main.querySelectorAll("#nlines tr").forEach(function (tr) { var d = rowData(tr); if (d.item_id || d.name) lines.push(d); });
      if (!lines.length) { K.say($("nmsg"), false, "Add at least one line."); return; }
      if (lines.some(function (l) { return !(l.qty > 0); })) { K.say($("nmsg"), false, "Quantity must be more than 0."); return; }
      var body = { party_id: Number(f.party_id.value), inv_date: f.inv_date.value, due_days: Number(f.due_days.value || 0),
        place_of_supply: f.place_of_supply.value.trim(), apply_cgst: $("ncg").checked, apply_sgst: $("nsg").checked, apply_igst: $("nig").checked,
        notes: $("nnotes").value.trim(), lines: lines };
      $("nsave").disabled = true;
      K.call("POST", "/billing/invoices", body).then(function (r) {
        K.say($("nmsg"), true, "Saved " + r.number + " · " + K.inr(r.total) + (r.new_items.length ? " · added to inventory: " + r.new_items.join(", ") : ""));
        window.open(pdf("/billing/invoices/" + r.id + "/pdf"), "_blank", "noopener");
        setTimeout(function () { go("invoices"); }, 1200);
      }).catch(function (er) { $("nsave").disabled = false; K.say($("nmsg"), false, er.message); });
    };
    autoTax();
  };

  // ------------------------------------------------------------- receipts
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
            "</b></td><td>" + statusPill(x.status) + '</td><td class="acts"><a class="abtn sm g" target="_blank" rel="noopener" href="' + pdf("/billing/receipts/" + x.id + "/pdf") + '">PDF</a> ' +
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
      $("rparty").onchange = function () { pre = {}; fillInv(); };
      $("rf").onsubmit = function (e) {
        e.preventDefault();
        var f = e.target, body = { party_id: Number(f.party_id.value), invoice_id: f.invoice_id.value ? Number(f.invoice_id.value) : null,
          amount: Number(f.amount.value), rcp_date: f.rcp_date.value, mode: f.mode.value, reference: f.reference.value.trim(), notes: f.notes.value.trim() };
        K.call("POST", "/billing/receipts", body).then(function (r) {
          K.say($("rmsg"), true, "Saved " + r.number);
          window.open(pdf("/billing/receipts/" + r.id + "/pdf"), "_blank", "noopener");
          setTimeout(function () { go("receipts"); }, 1000);
        }).catch(function (er) { K.say($("rmsg"), false, er.message); });
      };
      K.main.onclick = function (e) {
        var id = e.target.getAttribute("data-rc");
        if (id && confirm("Cancel this receipt? It stays in the records as cancelled.")) {
          K.call("POST", "/billing/receipts/" + id + "/cancel").then(function () { go("receipts"); }).catch(function (er) { K.say($("rmsg"), false, er.message); });
        }
      };
      bindSubs();
    }).catch(K.fail);
  };

  // ------------------------------------------------------------- accounts + ledger
  function partyForm(p) {
    p = p || {};
    return '<div class="card"><h3>' + (p.id ? "Edit account " + K.esc(p.code) : "New account (customer)") + '</h3><form id="pf" class="frm" data-id="' + (p.id || "") + '">' +
      '<label>Name / company<input name="name" required maxlength="160" value="' + K.esc(p.name) + '"></label>' +
      '<label>GSTIN<input name="gstin" maxlength="15" value="' + K.esc(p.gstin) + '" placeholder="optional" style="text-transform:uppercase"></label>' +
      '<label>State<input name="state" maxlength="60" value="' + K.esc(p.state) + '" placeholder="e.g. Uttar Pradesh"></label>' +
      '<label>State code<input name="state_code" maxlength="2" value="' + K.esc(p.state_code) + '" placeholder="e.g. 09"></label>' +
      '<label>Phone<input name="phone" maxlength="25" value="' + K.esc(p.phone) + '"></label>' +
      '<label>Email<input name="email" type="email" maxlength="160" value="' + K.esc(p.email) + '"></label>' +
      '<label>Opening balance ₹<input name="opening_balance" type="number" step="0.01" value="' + (p.opening_balance || 0) + '"></label>' +
      '<label class="wide">Address<input name="address" maxlength="400" value="' + K.esc(p.address) + '"></label>' +
      '<button class="abtn" type="submit">' + (p.id ? "Save changes" : "Create account") + '</button></form><p class="msg" id="pmsg"></p></div>';
  }
  function bindPartyForm(after) {
    $("pf").onsubmit = function (e) {
      e.preventDefault();
      var f = e.target, id = f.getAttribute("data-id"), body = {};
      ["name", "gstin", "state", "state_code", "phone", "email", "address"].forEach(function (k) { body[k] = f[k].value.trim(); });
      body.opening_balance = Number(f.opening_balance.value || 0);
      if (body.gstin && !/^[0-9]{2}[A-Z0-9]{13}$/i.test(body.gstin)) { K.say($("pmsg"), false, "GSTIN should be 15 characters (starts with the 2-digit state code)."); return; }
      if (body.gstin && !body.state_code) body.state_code = body.gstin.slice(0, 2);
      K.call(id ? "PATCH" : "POST", "/billing/parties" + (id ? "/" + id : ""), body).then(function (r) {
        K.say($("pmsg"), true, id ? "Saved." : "Created " + r.code); setTimeout(after, 700);
      }).catch(function (er) { K.say($("pmsg"), false, er.message); });
    };
  }

  VIEW.accounts = function (editId) {
    var editing = S.parties.filter(function (p) { return p.id === editId; })[0];
    var h = partyForm(editing) + '<div class="tblw"><table class="tbl"><thead><tr><th>Code</th><th>Account</th><th>GSTIN</th><th>State</th><th class="num">Balance</th><th></th></tr></thead><tbody>' +
      (S.parties.length ? S.parties.map(function (p) {
        return "<tr><td><b>" + K.esc(p.code) + "</b></td><td>" + K.esc(p.name) + (p.phone ? '<br><span class="muted2">' + K.esc(p.phone) + "</span>" : "") + "</td><td>" + K.esc(p.gstin || "—") +
          "</td><td>" + K.esc(p.state || "—") + '</td><td class="num"><b>' + K.inr(p.balance) + '</b></td><td class="acts"><button class="abtn sm" type="button" data-led="' + p.id + '">Ledger</button> ' +
          '<button class="abtn sm g" type="button" data-edit="' + p.id + '">Edit</button></td></tr>';
      }).join("") : '<tr><td colspan="6" class="empty">No accounts yet.</td></tr>') + '</tbody></table></div><div id="ledger"></div>';
    shell(h);
    bindPartyForm(function () { go("accounts"); });
    K.main.onclick = function (e) {
      var t = e.target;
      if (t.getAttribute("data-edit")) { go("accounts", Number(t.getAttribute("data-edit"))); return; }
      if (t.getAttribute("data-led")) { showLedger(Number(t.getAttribute("data-led"))); return; }
      if (t.id === "lgo") { showLedger(Number(t.getAttribute("data-p")), $("lfrom").value, $("lto").value); return; }
      var b = t.closest("[data-sub]"); if (b) go(b.getAttribute("data-sub"));
    };
  };

  function showLedger(pid, from, to) {
    var qs = "?dfrom=" + encodeURIComponent(from || "") + "&dto=" + encodeURIComponent(to || "");
    K.get("/billing/parties/" + pid + "/ledger" + qs).then(function (d) {
      var p = d.party, h = '<div class="card" style="margin-top:16px"><h3>Ledger · ' + K.esc(p.name) + " (" + K.esc(p.code) + ")</h3>" +
        '<div class="bar"><label class="muted2">From <input type="date" id="lfrom" value="' + K.esc(from || "") + '"></label><label class="muted2">To <input type="date" id="lto" value="' + K.esc(to || "") + '"></label>' +
        '<button class="abtn sm" type="button" id="lgo" data-p="' + pid + '">Show</button>' +
        '<a class="abtn sm g" target="_blank" rel="noopener" href="' + pdf("/billing/parties/" + pid + "/ledger.pdf" + qs) + '">PDF</a>' +
        '<a class="abtn sm g" href="' + pdf("/billing/parties/" + pid + "/ledger.csv" + qs) + '">CSV</a></div>' +
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

  // ------------------------------------------------------------- inventory
  VIEW.inventory = function (editId) {
    var it = S.items.filter(function (x) { return x.id === editId; })[0] || {};
    var h = '<div class="card"><h3>' + (it.id ? "Edit " + K.esc(it.code) : "Add product / service") + '</h3><form id="if" class="frm" data-id="' + (it.id || "") + '">' +
      '<label>Name<input name="name" required maxlength="160" value="' + K.esc(it.name) + '"></label>' +
      '<label>Category<select name="category"' + (it.id ? " disabled" : "") + ">" + Object.keys(CATS).map(function (c) { return opt(c, CATS[c], c === it.category); }).join("") + "</select></label>" +
      '<label>HSN / SAC<input name="hsn" maxlength="10" value="' + K.esc(it.hsn) + '"></label>' +
      '<label>Unit<input name="unit" maxlength="20" value="' + K.esc(it.unit || "pcs") + '"></label>' +
      '<label>Sale rate ₹ (before GST)<input name="price" type="number" min="0" step="0.01" value="' + (it.price != null ? it.price : "") + '" required></label>' +
      '<label>GST %<input name="gst_rate" type="number" min="0" max="28" step="0.01" value="' + (it.gst_rate != null ? it.gst_rate : 18) + '"></label>' +
      (it.id ? "" : '<label>Opening stock<input name="stock" type="number" step="any" value="0"></label>') +
      '<label class="chk"><input type="checkbox" name="track_stock"' + (it.track_stock || !it.id ? " checked" : "") + "> Track stock</label>" +
      '<button class="abtn" type="submit">' + (it.id ? "Save" : "Add item") + '</button></form><p class="muted2">Code is given automatically: HW-0001 hardware, SW-0001 software, SV-0001 services.</p><p class="msg" id="imsg"></p></div>';
    h += '<div class="bar"><input type="search" id="iq" placeholder="Search code or name"></div><div class="tblw"><table class="tbl"><thead><tr><th>Code</th><th>Name</th><th>HSN/SAC</th><th class="num">Rate</th><th class="num">GST</th><th class="num">Stock</th><th></th></tr></thead><tbody id="itb"></tbody></table></div><div id="moves"></div>';
    shell(h);
    function draw() {
      var q = $("iq").value.trim().toLowerCase();
      var rows = S.items.filter(function (x) { return !q || (x.code + " " + x.name).toLowerCase().indexOf(q) >= 0; });
      $("itb").innerHTML = rows.length ? rows.map(function (x) {
        return "<tr><td><b>" + K.esc(x.code) + "</b></td><td>" + K.esc(x.name) + "</td><td>" + K.esc(x.hsn || "—") + '</td><td class="num">' + K.inr(x.price) + '</td><td class="num">' + x.gst_rate +
          '%</td><td class="num">' + (x.track_stock ? '<b class="' + (x.stock <= 0 ? "neg" : "") + '">' + x.stock + "</b> " + K.esc(x.unit) : '<span class="muted2">not tracked</span>') +
          '</td><td class="acts"><button class="abtn sm" type="button" data-stk="' + x.id + '">Stock +/-</button> <button class="abtn sm g" type="button" data-ied="' + x.id + '">Edit</button> <button class="abtn sm g" type="button" data-mv="' + x.id + '">History</button></td></tr>';
      }).join("") : '<tr><td colspan="7" class="empty">No items yet.</td></tr>';
    }
    draw(); $("iq").oninput = draw;
    $("if").onsubmit = function (e) {
      e.preventDefault();
      var f = e.target, id = f.getAttribute("data-id");
      var body = { name: f.name.value.trim(), category: f.category.value, hsn: f.hsn.value.trim(), unit: f.unit.value.trim() || "pcs",
        price: Number(f.price.value || 0), gst_rate: Number(f.gst_rate.value || 0), track_stock: f.track_stock.checked, stock: f.stock ? Number(f.stock.value || 0) : 0 };
      K.call(id ? "PATCH" : "POST", "/billing/items" + (id ? "/" + id : ""), body).then(function (r) {
        K.say($("imsg"), true, id ? "Saved." : "Added " + r.code); setTimeout(function () { go("inventory"); }, 700);
      }).catch(function (er) { K.say($("imsg"), false, er.message); });
    };
    K.main.onclick = function (e) {
      var t = e.target;
      if (t.getAttribute("data-ied")) { go("inventory", Number(t.getAttribute("data-ied"))); return; }
      if (t.getAttribute("data-stk")) {
        var q = prompt("Stock change (use minus for out, e.g. 10 or -2):");
        if (q === null || q.trim() === "" || isNaN(Number(q))) return;
        var why = prompt("Reason (purchase, return, damage, correction):", Number(q) > 0 ? "purchase" : "correction") || "correction";
        K.call("POST", "/billing/items/" + t.getAttribute("data-stk") + "/stock", { qty: Number(q), reason: why.slice(0, 40) }).then(function () { go("inventory"); })
          .catch(function (er) { K.say($("imsg"), false, er.message); });
        return;
      }
      if (t.getAttribute("data-mv")) {
        K.get("/billing/items/" + t.getAttribute("data-mv") + "/moves").then(function (d) {
          $("moves").innerHTML = '<div class="card" style="margin-top:14px"><h3>Stock history</h3><div class="tblw"><table class="tbl"><thead><tr><th>When</th><th class="num">Qty</th><th>Reason</th><th>Ref</th><th>By</th></tr></thead><tbody>' +
            (d.items.length ? d.items.map(function (m) { return "<tr><td>" + K.esc((m.at || "").replace("T", " ").slice(0, 16)) + '</td><td class="num">' + (m.qty > 0 ? "+" : "") + m.qty + "</td><td>" + K.esc(m.reason) + "</td><td>" + K.esc(m.ref) + "</td><td>" + K.esc(m.by_user) + "</td></tr>"; }).join("")
              : '<tr><td colspan="5" class="empty">No stock movement.</td></tr>') + "</tbody></table></div></div>";
          $("moves").scrollIntoView({ behavior: "smooth" });
        });
        return;
      }
      var b = t.closest("[data-sub]"); if (b) go(b.getAttribute("data-sub"));
    };
  };

  // ------------------------------------------------------------- reports
  VIEW.reports = function (sel) {
    sel = sel || { fy: S.fy, period: "FY" };
    var periods = { Q1: "Q1 (Apr–Jun)", Q2: "Q2 (Jul–Sep)", Q3: "Q3 (Oct–Dec)", Q4: "Q4 (Jan–Mar)", H1: "Half year 1 (Apr–Sep)", H2: "Half year 2 (Oct–Mar)", FY: "Full year" };
    K.get("/billing/report?fy=" + sel.fy + "&period=" + sel.period).then(function (r) {
      var qs = "?fy=" + sel.fy + "&period=" + sel.period, t = r.totals;
      var h = '<div class="bar"><select id="rfy">' + fyList().map(function (f) { return opt(f, "FY " + f, f === sel.fy); }).join("") + "</select>" +
        '<select id="rper">' + Object.keys(periods).map(function (k) { return opt(k, periods[k], k === sel.period); }).join("") + "</select>" +
        '<a class="abtn sm g" target="_blank" rel="noopener" href="' + pdf("/billing/report.pdf" + qs) + '">PDF</a>' +
        '<a class="abtn sm g" href="' + pdf("/billing/report.csv" + qs) + '">CSV (invoice register)</a><span class="muted2">' + K.esc(r.from) + " to " + K.esc(r.to) + "</span></div>";
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
      function re() { go("reports", { fy: $("rfy").value, period: $("rper").value }); }
      $("rfy").onchange = re; $("rper").onchange = re;
      bindSubs();
    }).catch(K.fail);
  };

  // ------------------------------------------------------------- settings
  VIEW.settings = function () {
    var s = S.settings, F = [["company_name", "Company name"], ["gstin", "GSTIN"], ["pan", "PAN"], ["state", "State"], ["state_code", "State code"],
      ["phone", "Phone"], ["email", "Email"], ["bank_name", "Bank name"], ["bank_account", "Account number"], ["bank_ifsc", "IFSC"], ["upi", "UPI ID"],
      ["invoice_prefix", "Invoice prefix"], ["receipt_prefix", "Receipt prefix"]];
    var h = '<div class="card"><h3>Printed on every invoice and receipt</h3><form id="sf" class="frm">' +
      F.map(function (f) { return "<label>" + f[1] + '<input name="' + f[0] + '" value="' + K.esc(s[f[0]]) + '" maxlength="200"></label>'; }).join("") +
      '<label class="wide">Address<input name="address" value="' + K.esc(s.address) + '" maxlength="400"></label>' +
      '<label class="wide">Terms<input name="terms" value="' + K.esc(s.terms) + '" maxlength="600"></label>' +
      '<label class="chk"><input type="checkbox" name="round_off"' + (s.round_off === "1" ? " checked" : "") + "> Round total to nearest rupee</label>" +
      '<button class="abtn" type="submit">Save settings</button></form><p class="muted2">Changing the prefix only affects new numbers. Numbers restart every financial year (April).</p><p class="msg" id="smsg"></p></div>';
    shell(h);
    $("sf").onsubmit = function (e) {
      e.preventDefault();
      var f = e.target, v = {};
      F.concat([["address"], ["terms"]]).forEach(function (x) { v[x[0]] = f[x[0]].value.trim(); });
      v.round_off = f.round_off.checked ? "1" : "0";
      K.call("PUT", "/billing/settings", { values: v }).then(function () { K.say($("smsg"), true, "Saved."); }).catch(function (er) { K.say($("smsg"), false, er.message); });
    };
    bindSubs();
  };

  window.ATE_BILLING = function (kit) {
    K = kit;
    go(S.sub || "invoices");
  };
})();
