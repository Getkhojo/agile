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
      u.onend = function () { window.ATE_VOICE_ACTIVE = listening || convoActive; };
      window.speechSynthesis.speak(u);
    } catch (e) {}
  }

  function speakThen(text, cb) {
    if (!("speechSynthesis" in window) || !text) { if (cb) cb(); return; }
    try {
      window.speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(text);
      u.lang = lang;
      var v = window.speechSynthesis.getVoices().filter(function (x) { return x.lang && x.lang.replace("_", "-").indexOf(lang.slice(0, 2)) === 0; });
      if (v.length) u.voice = v[0];
      u.rate = 1;
      u.onend = function () { if (cb) cb(); };
      u.onerror = function () { if (cb) cb(); };
      window.speechSynthesis.speak(u);
    } catch (e) { if (cb) cb(); }
  }

  /* ---------- Hero in-place voice CONVERSATION (home page) ---------- */
  var heroSection = document.querySelector(".hero");
  var heroDemo = document.querySelector(".hero .demo");
  var heroRec = null, convoActive = false;
  var heroMics = heroSection ? heroSection.querySelectorAll(".mic") : [];
  var heroVO, heroQ, heroA;
  if (heroDemo) {
    heroVO = el("div", "vo");
    heroVO.hidden = true;
    heroVO.setAttribute("aria-live", "polite");
    heroVO.innerHTML =
      '<div class="vo-lines">' +
        '<p class="vo-row vo-q"><span class="vo-tag">You</span><span class="vo-txt" id="heroQ"></span></p>' +
        '<p class="vo-row vo-a"><span class="vo-tag">Agile</span><span class="vo-txt" id="heroA"></span>' +
          '<span class="vo-echo" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span></p>' +
      '</div>' +
      '<button class="vo-end" type="button" aria-label="End conversation">Stop</button>';
    heroDemo.appendChild(heroVO);
    heroQ = heroVO.querySelector("#heroQ");
    heroA = heroVO.querySelector("#heroA");
    heroVO.querySelector(".vo-end").addEventListener("click", heroEnd);
  }
  // Phone screen targets (the conversation shows inside the phone on desktop)
  var phoneQ = document.getElementById("phoneQ"), phoneA = document.getElementById("phoneA");
  var phRest = document.querySelector(".phone .ph-rest"), phLive = document.querySelector(".phone .ph-live");
  var phStop = document.getElementById("phoneStop"), phState = document.getElementById("phoneState");
  if (phStop) phStop.addEventListener("click", heroEnd);
  function setT(node, v) { if (node && v != null) node.textContent = v; }
  function heroShow(q, a) {
    if (heroVO) heroVO.hidden = false;
    if (phRest) phRest.hidden = true;
    if (phLive) phLive.hidden = false;
    if (q != null) { setT(heroQ, q); setT(phoneQ, q); }
    if (a != null) { setT(heroA, a); setT(phoneA, a); }
  }
  function heroPhase(p) {
    if (heroSection) {
      heroSection.classList.toggle("listening", p === "listening");
      heroSection.classList.toggle("thinking", p === "thinking");
      heroSection.classList.toggle("speaking", p === "speaking");
    }
    setT(phState, p === "speaking" ? "Speaking…" : p === "thinking" ? "…" : p === "listening" ? "Listening…" : "Tap to talk");
  }
  function beginUI() {
    convoActive = true;
    window.ATE_VOICE_ACTIVE = true;              // keep the waveform moving for the whole conversation
    if (window.ATE_WAVE) window.ATE_WAVE.kick();
    heroSection.classList.add("convo");
    heroMics.forEach(function (m) { m.classList.add("live"); });
    if (phStop) phStop.hidden = false;
  }
  function heroStart() {
    if (!heroSection) { if (window.ATE_CHAT) open({ voice: true }); return; }
    if (convoActive) { heroEnd(); return; }
    if (liveSupported()) { liveStart(); return; }
    browserStart();
  }
  // Free fallback: browser speech recognition + device voice
  function browserStart() {
    if (!SR) { heroShow("", "Voice needs Chrome or Edge. Tap “Ask Agile” to type instead."); heroEnd(); return; }
    beginUI();
    heroShow("", "Listening…");
    listenTurn();
  }

  /* ---------- Real-time voice: mic -> /api/voice -> Gemini Live -> speaker ---------- */
  var GKEY = "ate_voice_gender", live = null;
  var BARGE_RMS = CFG.bargeRms || 0.06;          // minimum mic level that can count as the visitor talking over Agile
  var END_MSG = {
    time_limit: "Demo time is over. Tap the mic to talk again, or leave your number and we'll call you.",
    idle: "Ended because it went quiet. Tap the mic to talk again.",
    error: "The call dropped. Tap the mic to try again.",
    closed: "Call ended.", provider_closed: "Call ended.", provider_goaway: "Call ended."
  };
  // Mic worklet: resample to 16 kHz PCM16, 40 ms frames, with the frame's RMS level
  var MIC_WORKLET = "class M extends AudioWorkletProcessor{constructor(){super();this.r=sampleRate/16000;this.p=0;" +
    "this.o=new Int16Array(640);this.n=0;this.s=0;this.c=0}process(i){var ch=i[0]&&i[0][0];if(!ch)return true;" +
    "for(var k=0;k<ch.length;k++){this.s+=ch[k]*ch[k];this.c++}while(this.p<ch.length){var j=this.p|0,f=this.p-j," +
    "a=ch[j],b=j+1<ch.length?ch[j+1]:a,v=a+(b-a)*f;v=v<-1?-1:v>1?1:v;this.o[this.n++]=v<0?v*32768:v*32767;" +
    "if(this.n===640){this.port.postMessage({pcm:this.o.buffer.slice(0),rms:Math.sqrt(this.s/this.c)});" +
    "this.n=0;this.s=0;this.c=0}this.p+=this.r}this.p-=ch.length;return true}}registerProcessor('ate-mic',M);";
  // Player worklet: one continuous 24 kHz stream in a ring buffer, resampled smoothly to the device rate.
  // Starts after a jitter buffer (grows if the network stutters), always plays the tail of a reply,
  // fades volume for ducking, reports state ~10x a second.
  var PLAYER_WORKLET = "class P extends AudioWorkletProcessor{constructor(){super();this.N=24000*60;this.q=new Float32Array(this.N);" +
    "this.w=0;this.r=0;this.st=24000/sampleRate;this.on=false;this.end=false;this.pre=8400;this.g=1;this.tg=1;this.u=0;this.pl=0;this.k=0;" +
    "this.port.onmessage=e=>{var d=e.data;if(d.c==='push'){var b=d.b;for(var i=0;i<b.length;i++){this.q[this.w%this.N]=b[i];this.w++}}" +
    "else if(d.c==='end'){this.end=true}else if(d.c==='clear'){this.r=this.w;this.on=false;this.end=false}" +
    "else if(d.c==='gain'){this.tg=d.v}}}" +
    "process(i,o){var out=o[0][0],N=this.N;for(var n=0;n<out.length;n++){var ri=Math.floor(this.r),av=this.w-ri;" +
    "if(!this.on){if(av>=this.pre||(this.end&&av>1))this.on=true;else{out[n]=0;continue}}" +
    "if(av<2){this.on=false;if(this.end){this.end=false}else{this.u++;this.pre=Math.min(14400,this.pre+1200)}out[n]=0;continue}" +
    "var a=this.q[ri%N],b=this.q[(ri+1)%N],f=this.r-ri;this.g+=(this.tg-this.g)*0.003;out[n]=(a+(b-a)*f)*this.g;this.r+=this.st;this.pl+=this.st}" +
    "for(var c=1;c<o[0].length;c++)o[0][c].set(out);if(++this.k%37===0)this.port.postMessage({buf:(this.w-Math.floor(this.r))/24000," +
    "on:this.on,u:this.u,pl:this.pl|0});return true}}registerProcessor('ate-player',P);";

  function getGender() { try { return localStorage.getItem(GKEY) || CFG.voiceDefault || "female"; } catch (e) { return CFG.voiceDefault || "female"; } }
  function setGender(g) {
    try { localStorage.setItem(GKEY, g); } catch (e) {}
    document.querySelectorAll(".vg button").forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-g") === g)); });
  }
  document.querySelectorAll(".vg button").forEach(function (b) {
    b.addEventListener("click", function () {
      var g = b.getAttribute("data-g");
      if (g === getGender()) return;
      setGender(g);
      if (live) { heroEnd(); heroStart(); }      // switch voice right away
    });
  });
  setGender(getGender());

  function liveSupported() {
    return !!(CFG.voiceEndpoint && window.WebSocket && (window.AudioContext || window.webkitAudioContext) &&
      window.AudioWorkletNode && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }
  function blobUrl(src) { return URL.createObjectURL(new Blob([src], { type: "application/javascript" })); }
  function liveStart() {
    var AC = window.AudioContext || window.webkitAudioContext;
    var ctx = new AC({ latencyHint: "interactive" });   // created inside the click so audio may play
    if (ctx.resume) ctx.resume();
    var L = live = { ctx: ctx, hot: 0, cold: 0, pre: [], barge: false, base: 0, spk: false, buf: 0,
                     you: "", agile: "", who: "", ready: false, timer: null, ends: 0, stats: {} };
    window.ATE_VOICE_DEBUG = L.stats;
    beginUI();
    heroShow("", "Connecting…");
    heroPhase("thinking");
    navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } })
      .then(function (stream) {
        if (live !== L) { stream.getTracks().forEach(function (t) { t.stop(); }); return; }
        L.stream = stream;
        return Promise.all([ctx.audioWorklet.addModule(blobUrl(MIC_WORKLET)), ctx.audioWorklet.addModule(blobUrl(PLAYER_WORKLET))]).then(function () {
          if (live !== L) return;
          L.player = new AudioWorkletNode(ctx, "ate-player", { numberOfInputs: 0, outputChannelCount: [2] });
          L.player.connect(ctx.destination);
          L.player.port.onmessage = function (e) {
            var s = e.data; L.buf = s.buf; L.spk = s.on || s.buf > 0.02;
            L.stats.underruns = s.u; L.stats.played = s.pl;
          };
          L.src = ctx.createMediaStreamSource(stream);
          L.mic = new AudioWorkletNode(ctx, "ate-mic");
          var mute = ctx.createGain(); mute.gain.value = 0;   // keeps the mic worklet running, silent
          L.src.connect(L.mic); L.mic.connect(mute); mute.connect(ctx.destination);
          L.mic.port.onmessage = function (e) { onMic(L, e.data); };
          openSocket(L);
        });
      })
      .catch(function (err) {
        if (live !== L) return;
        liveCleanup(L);
        heroEnd();
        heroShow("", err && err.name === "NotAllowedError"
          ? "Microphone is blocked. Allow it for this site, or tap “Ask Agile” to type."
          : "Couldn't start the microphone. Tap “Ask Agile” to type instead.");
      });
  }
  function openSocket(L) {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var ws = L.ws = new WebSocket(proto + "//" + location.host + CFG.voiceEndpoint + "?gender=" + encodeURIComponent(getGender()));
    ws.binaryType = "arraybuffer";
    ws.onmessage = function (e) {
      if (live !== L) return;
      if (typeof e.data !== "string") { playChunk(L, e.data); return; }
      var d; try { d = JSON.parse(e.data); } catch (x) { return; }
      if (d.type === "ready") {
        L.ready = true; L.ends = Date.now() + (d.max_seconds || 180) * 1000;
        heroShow("", ""); L.timer = setInterval(function () { tick(L); }, 250);
      } else if (d.type === "you") {
        if (L.who !== "you") { L.you = ""; L.who = "you"; }
        L.you += d.text; heroShow(L.you.trim(), null);
      } else if (d.type === "agile") {
        if (L.who !== "agile") { L.agile = ""; L.who = "agile"; }
        L.agile += d.text; heroShow(null, L.agile.trim());
      } else if (d.type === "interrupted") {          // Gemini confirmed the visitor is talking: stop Agile now
        L.player.port.postMessage({ c: "clear" }); setDuck(L, false); L.spk = false;
        L.stats.interrupts = (L.stats.interrupts || 0) + 1;
      } else if (d.type === "turn_done") {
        L.player.port.postMessage({ c: "end" });     // play out the last words, never cut the tail
      } else if (d.type === "end") {
        onLiveEnd(L, d.reason);
      }
    };
    ws.onclose = function () { if (live === L) onLiveEnd(L, L.ready ? "closed" : "unavailable"); };
  }
  function setDuck(L, on) {
    if (L.barge === on) return;
    L.barge = on;
    L.player.port.postMessage({ c: "gain", v: on ? 0.3 : 1 });
  }
  function onMic(L, m) {
    if (!L.ready || !L.ws || L.ws.readyState !== 1) return;
    if (!L.spk) {                                  // Agile is quiet: stream everything, Gemini detects turns
      L.hot = 0; L.pre = []; L.sf = 0; setDuck(L, false);
      L.ws.send(m.pcm); return;
    }
    // Agile is speaking. First 320 ms: just learn how loud the echo is on this device.
    if ((L.sf = (L.sf || 0) + 1) <= 8) {
      L.base = Math.max(L.base * 0.85, m.rms);
      L.pre.push(m.pcm); if (L.pre.length > 6) L.pre.shift();
      return;
    }
    // Then only clearly louder, sustained sound counts as the visitor.
    var thr = Math.max(BARGE_RMS, L.base * 2.5);
    if (m.rms > thr) { L.hot++; L.cold = 0; } else { L.cold++; L.hot = 0; if (!L.barge) L.base = L.base * 0.9 + m.rms * 0.1; }
    if (!L.barge) {
      L.pre.push(m.pcm); if (L.pre.length > 6) L.pre.shift();
      if (L.hot >= 5) {                            // ~200 ms of real speech: duck Agile, let Gemini hear the visitor
        setDuck(L, true); L.stats.barges = (L.stats.barges || 0) + 1;
        L.pre.forEach(function (p) { L.ws.send(p); }); L.pre = [];
      }
      return;
    }
    L.ws.send(m.pcm);                              // ducked: keep streaming until Gemini interrupts
    if (L.cold >= 20) setDuck(L, false);           // 800 ms quiet: it was noise, Agile carries on at full volume
  }
  function playChunk(L, buf) {
    if (!L.player || !buf || buf.byteLength < 2) return;
    var pcm = new Int16Array(buf.byteLength % 2 ? buf.slice(0, buf.byteLength - 1) : buf), n = pcm.length;
    var f = new Float32Array(n);
    for (var i = 0; i < n; i++) f[i] = pcm[i] / 32768;
    L.player.port.postMessage({ c: "push", b: f }, [f.buffer]);
    L.spk = true;
  }
  function tick(L) {
    heroPhase(L.spk ? "speaking" : "listening");
    var left = Math.max(0, Math.round((L.ends - Date.now()) / 1000));
    setT(phState, (L.spk ? "Speaking…" : "Listening…") + " " + Math.floor(left / 60) + ":" + ("0" + left % 60).slice(-2));
    window.ATE_VOICE_ACTIVE = true;
  }
  function liveCleanup(L) {
    if (live === L) live = null;
    clearInterval(L.timer);
    try { if (L.ws && L.ws.readyState === 1) L.ws.send(JSON.stringify({ type: "stop" })); } catch (e) {}
    try { if (L.ws) L.ws.close(); } catch (e) {}
    if (L.stream) L.stream.getTracks().forEach(function (t) { t.stop(); });
    try { if (L.mic) L.mic.disconnect(); if (L.player) L.player.disconnect(); } catch (e) {}
    try { L.ctx.close(); } catch (e) {}
  }
  function onLiveEnd(L, reason) {
    if (live !== L) return;
    var wasReady = L.ready;
    liveCleanup(L);
    if (!wasReady && convoActive) { browserStart(); return; }   // limit reached or server down: free browser voice
    heroEnd();
    if (END_MSG[reason]) heroShow(null, END_MSG[reason]);
  }

  function listenTurn() {
    if (!convoActive) return;
    heroPhase("listening");
    heroRec = new SR();
    heroRec.lang = lang; heroRec.interimResults = true; heroRec.maxAlternatives = 1;
    var finalText = "";
    heroRec.onresult = function (e) {
      var interim = "", fin = "";
      for (var i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) fin += e.results[i][0].transcript;
        else interim += e.results[i][0].transcript;
      }
      var shown = fin || interim;
      if (shown && /[ऀ-ॿ]/.test(shown)) lang = "hi-IN";
      if (shown) heroShow(shown, finalText ? null : "");   // live transcript in the You line
      if (fin) finalText += fin;
    };
    heroRec.onerror = function (e) {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        heroShow("", "Microphone is blocked. Allow it for this site, or tap “Ask Agile” to type.");
        heroEnd();
      }
    };
    heroRec.onend = function () {
      if (!convoActive) return;
      if (finalText.trim()) heroRespond(finalText.trim());
      else setTimeout(listenTurn, 300);           // nothing heard, keep listening
    };
    try { heroRec.start(); } catch (err) { setTimeout(listenTurn, 400); }
  }
  function heroRespond(q) {
    heroShow(q, "…");
    heroPhase("thinking");
    getReply(q).then(function (ans) {
      if (!convoActive) return;
      var txt = (ans.html || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
      heroShow(null, txt);
      heroPhase("speaking");
      speakThen(ans.speech || txt, function () {
        if (convoActive) setTimeout(listenTurn, 250);   // continuous: listen again after Agile speaks
      });
    });
  }
  function heroEnd() {
    if (live) liveCleanup(live);
    convoActive = false;
    window.ATE_VOICE_ACTIVE = false;
    if (heroRec) { try { heroRec.stop(); } catch (e) {} }
    try { if ("speechSynthesis" in window) window.speechSynthesis.cancel(); } catch (e) {}
    heroPhase("");
    if (heroSection) heroSection.classList.remove("convo");
    heroMics.forEach(function (m) { m.classList.remove("live"); });
    if (phStop) phStop.hidden = true;
  }

  build();
  window.ATE_CHAT = { open: open, close: close };
  window.ATE_HERO = { start: heroStart, end: heroEnd };
})();
