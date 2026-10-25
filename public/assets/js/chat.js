/* Agile Tech Expert - chat + voice assistant
   Answers from site content in the browser today. When the AI voice engine is live,
   set ATE.assistantEndpoint (e.g. "/api/assistant") and replies come from the server instead. */
(function () {
  "use strict";
  var CFG = window.ATE || {};
  var API = window.ATE_API;
  var ROOT = window.ATE_ROOT || "/";
  var SERVICES = CFG.services || [];
  var fab, panel, log, input, micBtn, opened = false, lang = "en-IN";

  var ICON_MIC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" fill="currentColor"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>';
  var ICON_SEND = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';
  var RINGS = '<div class="spin"><div class="ring"></div><div class="ring"></div><div class="ring"></div><div class="ring"></div><div class="ring"></div><div class="ring"></div></div>';

  function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function url(path) { return ROOT + path; }

  function build() {
    fab = el("button", "chat-fab");
    fab.type = "button";
    fab.setAttribute("aria-label", "Open chat and voice assistant");
    fab.innerHTML = '<span class="mic" aria-hidden="true">' + ICON_MIC + '</span><span>Ask Agile</span>';
    fab.addEventListener("click", function () { open({}); });
    document.body.appendChild(fab);

    panel = el("section", "chat");
    panel.hidden = true;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Agile assistant");
    panel.innerHTML =
      '<div class="chat-top"><div class="mini-orb" aria-hidden="true">' + RINGS + '</div>' +
      '<div><b>Agile Assistant</b><small id="chatSub">Chat or speak · Hindi + English</small></div>' +
      '<button type="button" class="x" aria-label="Close assistant">×</button></div>' +
      '<div class="chat-log" aria-live="polite"></div>' +
      '<form class="chat-input" autocomplete="off"><label class="sr-only" for="chatText">Type your question</label>' +
      '<input id="chatText" name="q" placeholder="Ask about IVR, WhatsApp, AI calling..." maxlength="400">' +
      '<button type="button" class="mic" aria-label="Speak your question" aria-pressed="false">' + ICON_MIC + '</button>' +
      '<button type="submit" class="send" aria-label="Send">' + ICON_SEND + '</button></form>';
    document.body.appendChild(panel);
    log = panel.querySelector(".chat-log");
    input = panel.querySelector("#chatText");
    micBtn = panel.querySelector(".chat-input .mic");
    panel.querySelector(".x").addEventListener("click", close);
    panel.querySelector(".chat-input").addEventListener("submit", function (e) {
      e.preventDefault();
      var q = input.value.trim();
      if (!q) return;
      input.value = "";
      ask(q, false);
    });
    micBtn.addEventListener("click", toggleListen);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && opened) close(); });
  }

  function open(opts) {
    opts = opts || {};
    panel.hidden = false; fab.hidden = true; opened = true;
    if (!log.children.length) greet();
    if (opts.topic) {
      var s = findService(opts.topic);
      if (s) say(serviceAnswer(s), quickFor(s));
      else if (opts.topic === "lead") leadForm(opts.service || "");
    }
    if (opts.voice) startListen(); else input.focus();
  }
  function close() { panel.hidden = true; fab.hidden = false; opened = false; stopListen(); fab.focus(); }

  function add(text, who, isHtml) {
    var m = el("div", "msg " + who);
    if (isHtml) m.innerHTML = text; else m.textContent = text;
    log.appendChild(m);
    log.scrollTop = log.scrollHeight;
    return m;
  }
  function quick(items) {
    var wrap = el("div", "quick");
    items.forEach(function (it) {
      var b = el("button", "", esc(it.label));
      b.type = "button";
      b.addEventListener("click", function () { wrap.remove(); it.run ? it.run() : ask(it.label, false); });
      wrap.appendChild(b);
    });
    log.appendChild(wrap);
    log.scrollTop = log.scrollHeight;
  }
  function say(ans, chips, spoken) {
    var t = el("div", "msg bot", '<span class="typing"><i></i><i></i><i></i></span>');
    log.appendChild(t); log.scrollTop = log.scrollHeight;
    setTimeout(function () {
      t.innerHTML = ans.html;
      log.scrollTop = log.scrollHeight;
      if (chips && chips.length) quick(chips);
      if (spoken) speak(ans.speech || ans.html.replace(/<[^>]+>/g, ""));
    }, 450);
  }

  var MENU = [
    { label: "What services do you offer?" },
    { label: "On-premise or managed?" },
    { label: "Book a demo", run: function () { leadForm(""); } },
    { label: "Talk on WhatsApp", run: function () { window.open(API.waLink("Hi, I'd like to know more about your services."), "_blank", "noopener"); } }
  ];
  function greet() {
    say({ html: "Namaste! I'm the Agile assistant. Ask me about AI calling, IVR, voice broadcast, WhatsApp, SMS, RCS, CRM or HRMS, or tap an option below. You can also press the mic and speak in Hindi or English." }, MENU);
  }

  /* ---------- Intent matching on site content ---------- */
  var KW = {
    "ai-calling": ["ai call", "ai voice", "voice agent", "voicebot", "voice bot", "bot call", "ai agent", "robot call", "एआई", "ai calling"],
    "ivr": ["ivr", "menu", "press 1", "call flow", "auto attendant", "आईवीआर"],
    "voice-broadcast": ["broadcast", "obd", "bulk call", "bulk voice", "voice message", "reseller", "white label", "white-label", "cps"],
    "cloud-calling": ["cloud call", "call center", "call centre", "dialer", "dialler", "predictive", "virtual number", "telecalling", "queue", "recording"],
    "webrtc-calling": ["webrtc", "click to call", "click-to-call", "browser call", "softphone", "website call", "video kyc", "in-app"],
    "voice-calling": ["pbx", "epabx", "sip trunk", "pri", "gsm gateway", "ip phone", "extension", "landline", "office phone"],
    "whatsapp-business": ["whatsapp", "whats app", "वॉट्सऐप", "व्हाट्सएप", "green tick", "wa api"],
    "bulk-sms": ["sms", "otp", "dlt", "text message", "एसएमएस", "sender id"],
    "rcs-messaging": ["rcs", "rich message", "rich card", "carousel"],
    "missed-call-service": ["missed call", "miss call", "मिस्ड कॉल", "missed-call"],
    "crm": ["crm", "lead management", "pipeline", "follow up", "follow-up", "sales tracking"],
    "hrms": ["hrms", "hr ", "attendance", "payroll", "leave", "employee management", "biometric", "हाजिरी"]
  };
  function findService(q) {
    q = (" " + q.toLowerCase() + " ");
    for (var i = 0; i < SERVICES.length; i++) {
      var s = SERVICES[i];
      if (q.indexOf(s.slug) > -1) return s;
      var k = KW[s.slug] || [];
      for (var j = 0; j < k.length; j++) if (q.indexOf(k[j]) > -1) return s;
    }
    return null;
  }
  function has(q, words) { for (var i = 0; i < words.length; i++) if (q.indexOf(words[i]) > -1) return true; return false; }
  function word(q, words) { return new RegExp("(^|[^a-z])(" + words.join("|") + ")([^a-z]|$)").test(q); }
  function serviceAnswer(s) {
    return {
      html: "<b>" + esc(s.name) + "</b>\n" + esc(s.short) + "\n\nWe can set it up on your premises or run it for you as a managed service. <a href=\"" + url(s.url) + "\">Read more</a>",
      speech: s.name + ". " + s.short + " We can set it up in your office, or run it for you as a managed service."
    };
  }
  function quickFor(s) {
    return [
      { label: "Book a " + s.name + " demo", run: function () { leadForm(s.name); } },
      { label: "Other services" }
    ];
  }
  function localAnswer(q) {
    var l = q.toLowerCase();
    var s = findService(l);
    if (has(l, ["price", "pricing", "cost", "rate", "plan", "charges", "kitna", "kitne", "कितना", "कीमत", "quotation", "quote"])) {
      return { a: { html: "Pricing depends on what you need: number of channels or users, message volumes, and whether it runs on your premises or ours. Share a few details and our team will send a quote, usually the same working day." }, then: function () { leadForm(s ? s.name : ""); } };
    }
    if (s) return { a: serviceAnswer(s), chips: quickFor(s) };
    if (has(l, ["premise", "on-prem", "onprem", "own server", "our server", "hosted", "managed", "apne office", "office me", "khud", "cloud or", "both"])) {
      return { a: { html: "We offer both:\n\n<b>On-Premise Setup</b>: we install and license the platform on your servers in your office or data center. Your data stays in your network and you can brand it as your own.\n\n<b>Managed Service</b>: we host, run and monitor everything; you just use it.\n\n<a href=\"" + url(CFG.pages.services) + "#delivery\">Compare the two</a>", speech: "We offer both. On-premise setup, where we install the platform on your own servers, or a managed service, where we host and run everything for you." }, chips: [{ label: "Book a demo", run: function () { leadForm(""); } }] };
    }
    if (has(l, ["service", "offer", "what do you", "kya karte", "kya kya", "सेवा", "products", "solutions"])) {
      var by = {};
      SERVICES.forEach(function (x) { (by[x.category_name] = by[x.category_name] || []).push('<a href="' + url(x.url) + '">' + esc(x.name) + "</a>"); });
      var h = Object.keys(by).map(function (k) { return "<b>" + esc(k) + "</b>\n" + by[k].join(" · "); }).join("\n\n");
      return { a: { html: h, speech: "We offer AI voice calling, IVR, voice broadcast, cloud calling, WebRTC calling, business PBX, WhatsApp Business API, bulk SMS, RCS, missed call service, CRM and HRMS." }, chips: [{ label: "On-premise or managed?" }, { label: "Book a demo", run: function () { leadForm(""); } }] };
    }
    if (has(l, ["address", "location", "where are", "office kaha", "kahan", "कहाँ", "visit"])) {
      return { a: { html: "Our office: " + esc(CFG.address) + '\n<a href="' + esc(CFG.mapsUrl) + '" target="_blank" rel="noopener">Open in Google Maps</a>' } };
    }
    if (has(l, ["call me", "callback", "call back", "human", "person", "sales", "contact", "phone", "number", "baat", "बात"])) {
      return { a: { html: "Leave your number and our team will call you back. You can also call " + esc((CFG.phones || [])[0] || "") + " or <a href=\"" + API.waLink("Hi, please call me back.") + "\" target=\"_blank\" rel=\"noopener\">message us on WhatsApp</a>." }, then: function () { leadForm(""); } };
    }
    if (word(l, ["demo", "trial", "try it"])) return { a: { html: "Happy to show you a live demo. Tell us where to reach you." }, then: function () { leadForm(""); } };
    if (has(l, ["login", "portal", "employee", "client panel", "sign in"])) {
      return { a: { html: 'Employees sign in at the <a href="' + url(CFG.pages.employee) + '">staff portal</a>. Customers use the <a href="' + url(CFG.pages.client) + '">client portal</a>.' } };
    }
    if (word(l, ["hello", "hi", "hey", "namaste", "hii"]) || l.indexOf("नमस्ते") > -1) return { a: { html: "Hello! What would you like to know?" }, chips: MENU };
    if (has(l, ["thank", "thanks", "dhanyavad", "धन्यवाद", "shukriya"])) return { a: { html: "You're welcome. Anything else I can help with?" } };
    return { a: { html: "I don't have a ready answer for that, but our team does. Leave your details and we'll get back to you, or pick a topic below." }, chips: MENU };
  }

  function ask(q, spoken) {
    add(q, "me");
    if (CFG.assistantEndpoint) {
      API.post(CFG.assistantEndpoint.replace(CFG.apiBase || "/api", ""), { message: q, lang: lang, page: location.pathname }).then(function (res) {
        if (res.ok && res.data && res.data.reply) say({ html: esc(res.data.reply) }, null, spoken);
        else respondLocal(q, spoken);
      });
      return;
    }
    respondLocal(q, spoken);
  }
  function respondLocal(q, spoken) {
    var r = localAnswer(q);
    say(r.a, r.chips, spoken);
    if (r.then) setTimeout(r.then, 700);
  }
  // Shared "brain": returns a Promise<{html, speech}> used by chat and hero voice.
  function getReply(q) {
    return new Promise(function (resolve) {
      if (CFG.assistantEndpoint) {
        API.post(CFG.assistantEndpoint.replace(CFG.apiBase || "/api", ""), { message: q, lang: lang, page: location.pathname }).then(function (res) {
          if (res.ok && res.data && res.data.reply) resolve({ html: esc(res.data.reply), speech: res.data.reply });
          else resolve(localAnswer(q).a);
        });
      } else {
        resolve(localAnswer(q).a);
      }
    });
  }

  /* ---------- Lead capture inside chat ---------- */
  function leadForm(service) {
    var opts = SERVICES.map(function (s) { return '<option' + (s.name === service ? " selected" : "") + ">" + esc(s.name) + "</option>"; }).join("");
    var f = el("form", "chat-form");
    f.noValidate = true;
    var uid = "c" + Date.now();
    f.innerHTML =
      '<label class="sr-only" for="' + uid + 'n">Name</label><input id="' + uid + 'n" name="name" placeholder="Your name" autocomplete="name" required>' +
      '<label class="sr-only" for="' + uid + 'p">Phone</label><input id="' + uid + 'p" name="phone" placeholder="Phone / WhatsApp number" inputmode="tel" autocomplete="tel" required>' +
      '<label class="sr-only" for="' + uid + 'c">Company</label><input id="' + uid + 'c" name="company" placeholder="Company (optional)" autocomplete="organization">' +
      '<label class="sr-only" for="' + uid + 's">Service</label><select id="' + uid + 's" name="service"><option value="">Service you need</option>' + opts + "</select>" +
      '<label class="sr-only" for="' + uid + 'm">Setup</label><select id="' + uid + 'm" name="mode"><option value="">On-premise or managed?</option><option>On-premise setup</option><option>Managed service</option><option>Not sure yet</option></select>' +
      '<label class="sr-only" for="' + uid + 't">Message</label><textarea id="' + uid + 't" name="message" placeholder="Anything else? (optional)"></textarea>' +
      '<button class="btn btn-p btn-sm" type="submit">Request a callback</button>';
    log.appendChild(f);
    log.scrollTop = log.scrollHeight;
    f.querySelector("input").focus();
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      var d = {};
      new FormData(f).forEach(function (v, k) { d[k] = String(v).trim(); });
      if (!d.name || !API.validPhone(d.phone)) { say({ html: "Please add your name and a valid phone number." }); return; }
      d.source = "chat"; d.page = location.pathname;
      f.querySelectorAll("input,select,textarea,button").forEach(function (x) { x.disabled = true; });
      API.post("/leads", d).then(function (res) {
        if (res.ok) say({ html: "Thank you, " + esc(d.name.split(" ")[0]) + ". Our team will call you on " + esc(d.phone) + " shortly." });
        else say({ html: 'Our server isn\'t reachable right now. <a href="' + API.waLink(API.leadText(d)) + '" target="_blank" rel="noopener">Send these details on WhatsApp</a> and we\'ll reply there.' });
      });
    });
  }

  /* ---------- Voice: browser speech recognition + speech synthesis ---------- */
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var rec = null, listening = false;
  function setLive(on) {
    listening = on;
    window.ATE_VOICE_ACTIVE = on;
    if (on && window.ATE_WAVE) window.ATE_WAVE.kick();
    micBtn.classList.toggle("live", on);
    micBtn.setAttribute("aria-pressed", String(on));
    document.querySelectorAll(".demo").forEach(function (d) { d.classList.toggle("listening", on); });
    panel.querySelector("#chatSub").textContent = on ? "Listening..." : "Chat or speak · Hindi + English";
  }
  function startListen() {
    if (!SR) { say({ html: "Voice input isn't supported in this browser. Please type your question, or use Chrome or Edge to speak." }); return; }
    if (listening) return;
    rec = new SR();
    rec.lang = lang; rec.interimResults = false; rec.maxAlternatives = 1;
    rec.onresult = function (e) {
      var t = e.results[0][0].transcript;
      if (/[ऀ-ॿ]/.test(t)) lang = "hi-IN";
      ask(t, true);
    };
    rec.onerror = function (e) {
      setLive(false);
      if (e.error === "not-allowed" || e.error === "service-not-allowed") say({ html: "Microphone access is blocked. Allow the microphone for this site in your browser settings, or type your question." });
    };
    rec.onend = function () { setLive(false); };
    try { rec.start(); setLive(true); } catch (err) { setLive(false); }
  }
  function stopListen() { if (rec && listening) { try { rec.stop(); } catch (e) {} } setLive(false); }
  function toggleListen() { listening ? stopListen() : startListen(); }
  function speak(text) {
    if (!("speechSynthesis" in window)) return;
    try {
      window.speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(text);
      u.lang = lang;
      var v = window.speechSynthesis.getVoices().filter(function (x) { return x.lang && x.lang.replace("_", "-").indexOf(lang.slice(0, 2)) === 0; });
      if (v.length) u.voice = v[0];
      u.rate = 1;
      window.ATE_VOICE_ACTIVE = true;
      if (window.ATE_WAVE) window.ATE_WAVE.kick();
      u.onend = function () { window.ATE_VOICE_ACTIVE = listening || heroListening; };
      window.speechSynthesis.speak(u);
    } catch (e) {}
  }

  /* ---------- Hero in-place voice demo (home page) ---------- */
  var heroDemo = document.querySelector(".hero .demo");
  var heroVO, heroQ, heroA, heroRec = null, heroListening = false;
  if (heroDemo) {
    heroVO = el("div", "vo");
    heroVO.hidden = true;
    heroVO.setAttribute("aria-live", "polite");
    heroVO.innerHTML =
      '<p class="vo-row vo-q"><span class="vo-tag">You</span><span class="vo-txt" id="heroQ"></span></p>' +
      '<p class="vo-row vo-a"><span class="vo-tag">Agile</span><span class="vo-txt" id="heroA"></span></p>';
    heroDemo.appendChild(heroVO);
    heroQ = heroVO.querySelector("#heroQ");
    heroA = heroVO.querySelector("#heroA");
  }
  function heroSetLive(on) {
    heroListening = on;
    window.ATE_VOICE_ACTIVE = on;
    if (on && window.ATE_WAVE) window.ATE_WAVE.kick();
    if (!heroDemo) return;
    heroDemo.classList.toggle("listening", on);
    var m = heroDemo.querySelector(".mic");
    if (m) { m.classList.toggle("live", on); m.setAttribute("aria-pressed", String(on)); }
  }
  function heroShow(q, a) {
    if (!heroVO) return;
    heroVO.hidden = false;
    if (q != null) heroQ.textContent = q;
    if (a != null) heroA.textContent = a;
  }
  function heroStart() {
    if (!heroDemo) { if (window.ATE_CHAT) open({ voice: true }); return; }
    if (heroListening) { heroStop(); return; }
    if (!SR) { heroShow("", "Voice needs Chrome or Edge. Tap “Ask Agile” to type instead."); return; }
    heroRec = new SR();
    heroRec.lang = lang; heroRec.interimResults = false; heroRec.maxAlternatives = 1;
    heroShow("", "Listening…");
    heroRec.onresult = function (e) {
      var t = e.results[0][0].transcript;
      if (/[ऀ-ॿ]/.test(t)) lang = "hi-IN";
      heroShow(t, "…");
      getReply(t).then(function (ans) {
        var txt = (ans.html || "").replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
        heroShow(null, txt);
        speak(ans.speech || txt);
      });
    };
    heroRec.onerror = function (e) {
      heroSetLive(false);
      if (e.error === "not-allowed" || e.error === "service-not-allowed")
        heroShow("", "Microphone is blocked. Allow it for this site, or tap “Ask Agile” to type.");
    };
    heroRec.onend = function () { heroSetLive(false); };
    try { heroRec.start(); heroSetLive(true); } catch (err) { heroSetLive(false); }
  }
  function heroStop() { if (heroRec && heroListening) { try { heroRec.stop(); } catch (e) {} } heroSetLive(false); }

  build();
  window.ATE_CHAT = { open: open, close: close };
  window.ATE_HERO = { start: heroStart };
})();
