(function () {
  "use strict";

  var scriptEl = document.currentScript;
  if (!scriptEl) return;

  var businessId = scriptEl.getAttribute("data-business-id");
  if (!businessId) {
    console.error("Night Guard AI widget: missing data-business-id on the <script> tag.");
    return;
  }

  var apiBase = new URL(scriptEl.src).origin;
  var configEndpoint = apiBase + "/api/v1/widget/" + encodeURIComponent(businessId) + "/config";
  var messagesEndpoint = apiBase + "/api/v1/widget/" + encodeURIComponent(businessId) + "/messages";
  var updatesEndpoint = apiBase + "/api/v1/widget/" + encodeURIComponent(businessId) + "/updates";
  var voiceMessageEndpoint = apiBase + "/api/v1/widget/" + encodeURIComponent(businessId) + "/voice-message";
  var storageKey = "nightguard_widget_session_" + businessId;
  var popupKey = "nightguard_widget_popup_seen_" + businessId;

  // Dashboard preview only: `data-preview-config` carries unsaved settings as JSON, used instead of the saved config,
  // and `data-open="true"` starts with the panel open. A normal embed never sets either.
  var previewConfig = null;
  try {
    var rawPreview = scriptEl.getAttribute("data-preview-config");
    previewConfig = rawPreview ? JSON.parse(rawPreview) : null;
  } catch (e) {
    previewConfig = null;
  }
  var startOpen = scriptEl.getAttribute("data-open") === "true";

  // Defaults used when a setting is blank, or when the config can't be fetched at all.
  var DEFAULT_COLOR = "#2563eb";
  var DEFAULT_NAME = "Chat with us";
  var DEFAULT_SUBTITLE = "We reply in seconds";
  var DEFAULT_WELCOME = "Hi there! How can we help you today?";
  var DEFAULT_PLACEHOLDER = "Type your message...";

  function getSessionToken() {
    try {
      return window.localStorage.getItem(storageKey);
    } catch (e) {
      return null;
    }
  }

  function setSessionToken(token) {
    try {
      window.localStorage.setItem(storageKey, token);
    } catch (e) {
      /* localStorage unavailable (private mode, etc.) — session just won't persist across reloads */
    }
  }

  // White or near-black text, whichever reads better on the brand colour.
  function readableOn(hex) {
    var m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
    if (!m) return "#ffffff";
    var n = parseInt(m[1], 16);
    var ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(function (c) {
      c /= 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });
    var lum = 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
    return lum > 0.45 ? "#111827" : "#ffffff";
  }

  // ---- styling: static rules in one injected <style>; per-business values (colour, text colour) are CSS custom
  // properties on the root, and position/theme are classes, so the config can be applied after first paint. ----

  var style = document.createElement("style");
  style.textContent =
    "#ng-widget-root{--ng-color:" + DEFAULT_COLOR + ";--ng-on-color:#fff;--ng-bg:#ffffff;--ng-surface:#f5f6fa;" +
    "--ng-bubble:#ffffff;--ng-text:#111827;--ng-muted:#6b7280;--ng-line:#e7e8ee;" +
    "position:fixed;bottom:20px;right:20px;z-index:999999;" +
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;-webkit-font-smoothing:antialiased;}" +
    "#ng-widget-root.ng-left{right:auto;left:20px;}" +
    "#ng-widget-root.ng-dark{--ng-bg:#17151f;--ng-surface:#1f1c2b;--ng-bubble:#2a2639;--ng-text:#f1eff7;--ng-muted:#a8a3b8;--ng-line:#2f2b40;}" +
    "#ng-widget-root.ng-loading{visibility:hidden;}" +
    "#ng-widget-root *{box-sizing:border-box;}" +
    "#ng-widget-launcher{display:flex;align-items:center;gap:10px;justify-content:flex-end;}" +
    "#ng-widget-root.ng-left #ng-widget-launcher{flex-direction:row-reverse;}" +
    "#ng-widget-label{background:var(--ng-bg);color:var(--ng-text);font-size:14px;font-weight:600;padding:9px 14px;border-radius:999px;" +
    "box-shadow:0 6px 20px rgba(0,0,0,.14);cursor:pointer;border:none;font-family:inherit;}" +
    "#ng-widget-bubble{position:relative;width:60px;height:60px;border-radius:50%;background:var(--ng-color);color:var(--ng-on-color);" +
    "display:flex;align-items:center;justify-content:center;cursor:pointer;border:none;overflow:hidden;" +
    "box-shadow:0 8px 24px rgba(0,0,0,.24);transition:transform .18s ease,box-shadow .18s ease;}" +
    "#ng-widget-bubble:hover{transform:scale(1.06);box-shadow:0 10px 28px rgba(0,0,0,.3);}" +
    "#ng-widget-bubble:focus-visible,#ng-widget-label:focus-visible,.ng-chip:focus-visible{outline:3px solid var(--ng-color);outline-offset:3px;}" +
    "#ng-widget-bubble svg{width:28px;height:28px;transition:opacity .15s ease,transform .15s ease;}" +
    "#ng-widget-bubble img{width:100%;height:100%;object-fit:cover;transition:opacity .15s ease;}" +
    "#ng-widget-bubble .ng-icon-close{position:absolute;opacity:0;transform:rotate(-90deg) scale(.6);}" +
    "#ng-widget-root.ng-open #ng-widget-bubble .ng-icon-open{opacity:0;transform:rotate(90deg) scale(.6);}" +
    "#ng-widget-root.ng-open #ng-widget-bubble .ng-icon-close{opacity:1;transform:rotate(0) scale(1);}" +
    "#ng-widget-root.ng-open #ng-widget-label,#ng-widget-root.ng-open #ng-widget-popup{display:none;}" +
    "#ng-widget-popup{position:absolute;bottom:76px;right:0;width:280px;background:var(--ng-bg);color:var(--ng-text);" +
    "border-radius:16px;padding:14px 34px 14px 16px;font-size:14px;line-height:1.45;box-shadow:0 12px 32px rgba(0,0,0,.18);" +
    "cursor:pointer;display:none;animation:ng-pop .3s ease;white-space:pre-wrap;}" +
    "#ng-widget-root.ng-left #ng-widget-popup{right:auto;left:0;}" +
    "#ng-widget-popup.ng-visible{display:block;}" +
    "#ng-widget-popup-close{position:absolute;top:6px;right:6px;border:none;background:none;color:var(--ng-muted);cursor:pointer;" +
    "font-size:18px;line-height:1;padding:4px 6px;}" +
    "@keyframes ng-pop{from{opacity:0;transform:translateY(8px) scale(.97);}to{opacity:1;transform:none;}}" +
    "#ng-widget-panel{position:absolute;bottom:76px;right:0;width:380px;height:600px;max-height:calc(100vh - 110px);" +
    "background:var(--ng-bg);color:var(--ng-text);border-radius:20px;box-shadow:0 18px 50px rgba(0,0,0,.24);display:flex;" +
    "flex-direction:column;overflow:hidden;opacity:0;transform:translateY(14px) scale(.98);transform-origin:bottom right;" +
    "pointer-events:none;visibility:hidden;transition:opacity .2s ease,transform .2s ease,visibility 0s linear .2s;}" +
    "#ng-widget-root.ng-left #ng-widget-panel{right:auto;left:0;transform-origin:bottom left;}" +
    "#ng-widget-root.ng-open #ng-widget-panel{opacity:1;transform:none;pointer-events:auto;visibility:visible;" +
    "transition:opacity .2s ease,transform .2s ease;}" +
    "#ng-widget-header{background:var(--ng-color);color:var(--ng-on-color);padding:16px 18px;display:flex;align-items:center;gap:12px;}" +
    ".ng-avatar{width:40px;height:40px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;" +
    "font-weight:700;font-size:15px;overflow:hidden;}" +
    ".ng-avatar img{width:100%;height:100%;object-fit:cover;}" +
    "#ng-widget-header .ng-avatar{background:rgba(255,255,255,.95);color:var(--ng-color);box-shadow:0 0 0 2px rgba(255,255,255,.35);}" +
    "#ng-widget-header-name{font-size:16px;font-weight:700;line-height:1.25;}" +
    "#ng-widget-header-status{font-size:12.5px;opacity:.9;display:flex;align-items:center;gap:6px;margin-top:2px;}" +
    "#ng-widget-header-status::before{content:'';width:8px;height:8px;border-radius:50%;background:#34d399;" +
    "box-shadow:0 0 0 2px rgba(255,255,255,.5);}" +
    "#ng-widget-messages{flex:1;overflow-y:auto;padding:16px;font-size:14.5px;background:var(--ng-surface);}" +
    ".ng-row{display:flex;align-items:flex-end;gap:8px;margin:6px 0;}" +
    ".ng-row .ng-avatar{width:28px;height:28px;font-size:11px;background:var(--ng-color);color:var(--ng-on-color);}" +
    ".ng-row-customer{justify-content:flex-end;}" +
    ".ng-msg{padding:10px 14px;border-radius:18px;max-width:78%;line-height:1.5;white-space:pre-wrap;word-wrap:break-word;" +
    "animation:ng-msg-in .18s ease;}" +
    ".ng-msg a{color:inherit;text-decoration:underline;}" +
    "@keyframes ng-msg-in{from{opacity:0;transform:translateY(4px);}to{opacity:1;transform:translateY(0);}}" +
    ".ng-msg-customer{background:var(--ng-color);color:var(--ng-on-color);border-bottom-right-radius:6px;}" +
    ".ng-msg-agent{background:var(--ng-bubble);color:var(--ng-text);border-bottom-left-radius:6px;box-shadow:0 1px 2px rgba(0,0,0,.08);}" +
    "#ng-widget-chips{display:flex;flex-wrap:wrap;gap:8px;padding:4px 16px 12px;background:var(--ng-surface);}" +
    "#ng-widget-chips:empty{display:none;}" +
    ".ng-chip{border:1.5px solid var(--ng-color);color:var(--ng-text);background:var(--ng-bg);border-radius:999px;" +
    "padding:8px 13px;font-size:13.5px;font-family:inherit;cursor:pointer;text-align:left;line-height:1.3;" +
    "transition:background .15s ease,color .15s ease;}" +
    ".ng-chip:hover{background:var(--ng-color);color:var(--ng-on-color);}" +
    "#ng-widget-typing{display:none;margin:6px 0 6px 36px;background:var(--ng-bubble);border-radius:18px;border-bottom-left-radius:6px;" +
    "padding:12px 14px;box-shadow:0 1px 2px rgba(0,0,0,.08);width:fit-content;}" +
    "#ng-widget-typing.ng-visible{display:block;}" +
    "#ng-widget-typing span{display:inline-block;width:7px;height:7px;margin:0 1.5px;border-radius:50%;" +
    "background:var(--ng-muted);animation:ng-typing 1.2s infinite;}" +
    "#ng-widget-typing span:nth-child(2){animation-delay:.15s;}" +
    "#ng-widget-typing span:nth-child(3){animation-delay:.3s;}" +
    "@keyframes ng-typing{0%,60%,100%{transform:translateY(0);opacity:.5;}30%{transform:translateY(-3px);opacity:1;}}" +
    "#ng-widget-form{display:flex;align-items:center;gap:4px;margin:10px 12px;padding:4px 6px 4px 4px;border:1.5px solid var(--ng-line);" +
    "border-radius:999px;background:var(--ng-bg);transition:border-color .15s ease;}" +
    "#ng-widget-form:focus-within{border-color:var(--ng-color);}" +
    "#ng-widget-input{flex:1;min-width:0;border:none;background:transparent;color:var(--ng-text);padding:10px 8px;font-size:15px;" +
    "outline:none;font-family:inherit;}" +
    "#ng-widget-input::placeholder{color:var(--ng-muted);}" +
    "#ng-widget-send{border:none;background:var(--ng-color);color:var(--ng-on-color);width:38px;height:38px;border-radius:50%;" +
    "display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;}" +
    "#ng-widget-send:disabled{opacity:.4;cursor:default;}" +
    "#ng-widget-send svg{width:18px;height:18px;}" +
    "#ng-widget-voice{border:none;background:none;color:var(--ng-muted);width:38px;height:38px;border-radius:50%;cursor:pointer;" +
    "display:flex;align-items:center;justify-content:center;flex-shrink:0;}" +
    "#ng-widget-voice:hover{color:var(--ng-color);}" +
    "#ng-widget-voice:disabled{opacity:.4;cursor:default;}" +
    "#ng-widget-voice svg{width:19px;height:19px;}" +
    "#ng-widget-voice.ng-recording{color:#ef4444;animation:ng-pulse 1.2s infinite;}" +
    "@keyframes ng-pulse{0%,100%{opacity:.4;}50%{opacity:1;}}" +
    "#ng-widget-branding{text-align:center;font-size:11px;color:var(--ng-muted);padding:0 0 10px;}" +
    "#ng-widget-branding[hidden]{display:none;}" +
    "@media (max-width:420px){#ng-widget-root.ng-open{inset:0;}" +
    "#ng-widget-root.ng-open #ng-widget-panel{position:fixed;inset:0;width:100%;height:100%;max-height:none;border-radius:0;}" +
    "#ng-widget-root.ng-open #ng-widget-launcher{display:none;}#ng-widget-close-mobile{display:flex !important;}}" +
    "#ng-widget-close-mobile{display:none;margin-left:auto;border:none;background:rgba(255,255,255,.2);color:var(--ng-on-color);" +
    "width:34px;height:34px;border-radius:50%;align-items:center;justify-content:center;cursor:pointer;}" +
    "@media (prefers-reduced-motion:reduce){#ng-widget-root *{animation:none !important;transition:none !important;}}";
  document.head.appendChild(style);

  var root = document.createElement("div");
  root.id = "ng-widget-root";
  root.className = "ng-loading";

  function svg(path) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
      'stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">' + path + "</svg>";
  }
  // Launcher icon choices (WidgetSettings.launcher_icon). "logo" shows the uploaded logo instead.
  var LAUNCHER_ICONS = {
    chat: '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
    sparkles: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    headset: '<path d="M4 14v-2a8 8 0 0 1 16 0v2"/><path d="M18 19a2 2 0 0 1-2 2h-3"/><rect x="2" y="14" width="4" height="6" rx="1.5"/><rect x="18" y="14" width="4" height="6" rx="1.5"/>',
    question: '<circle cx="12" cy="12" r="9"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
    calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/><path d="M9 15l2 2 4-4"/>',
  };
  var CLOSE_ICON = svg('<path d="M18 6 6 18M6 6l12 12"/>');
  var SEND_ICON = svg('<path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z"/>');
  var MIC_ICON = svg('<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v4M8 22h8"/>');

  // Static markup only (no business text): every piece of text below is filled in with textContent.
  root.innerHTML =
    '<div id="ng-widget-panel" role="dialog" aria-label="Chat">' +
    '<div id="ng-widget-header"><div class="ng-avatar" id="ng-widget-avatar"></div>' +
    '<div><div id="ng-widget-header-name"></div><div id="ng-widget-header-status"></div></div>' +
    '<button id="ng-widget-close-mobile" type="button" aria-label="Close chat">' + CLOSE_ICON + "</button></div>" +
    '<div id="ng-widget-messages" role="log" aria-live="polite">' +
    '<div id="ng-widget-typing"><span></span><span></span><span></span></div></div>' +
    '<div id="ng-widget-chips"></div>' +
    '<form id="ng-widget-form">' +
    '<input id="ng-widget-input" type="text" autocomplete="off" aria-label="Your message" />' +
    '<button id="ng-widget-voice" type="button" aria-label="Start voice message">' + MIC_ICON + "</button>" +
    '<button id="ng-widget-send" type="submit" aria-label="Send">' + SEND_ICON + "</button>" +
    "</form>" +
    '<div id="ng-widget-branding">Powered by Night Guard AI</div>' +
    "</div>" +
    '<div id="ng-widget-popup" role="status"><span id="ng-widget-popup-text"></span>' +
    '<button id="ng-widget-popup-close" type="button" aria-label="Dismiss">&times;</button></div>' +
    '<div id="ng-widget-launcher"><button id="ng-widget-label" type="button" hidden></button>' +
    '<button id="ng-widget-bubble" type="button" aria-label="Open chat"><span class="ng-icon-open" id="ng-widget-open-icon"></span>' +
    '<span class="ng-icon-close">' + CLOSE_ICON + "</span></button></div>";

  document.body.appendChild(root);

  var bubbleEl = root.querySelector("#ng-widget-bubble");
  var labelEl = root.querySelector("#ng-widget-label");
  var openIconEl = root.querySelector("#ng-widget-open-icon");
  var messagesEl = root.querySelector("#ng-widget-messages");
  var typingEl = root.querySelector("#ng-widget-typing");
  var chipsEl = root.querySelector("#ng-widget-chips");
  var formEl = root.querySelector("#ng-widget-form");
  var inputEl = root.querySelector("#ng-widget-input");
  var sendEl = root.querySelector("#ng-widget-send");
  var voiceBtn = root.querySelector("#ng-widget-voice");
  var headerNameEl = root.querySelector("#ng-widget-header-name");
  var headerStatusEl = root.querySelector("#ng-widget-header-status");
  var headerAvatarEl = root.querySelector("#ng-widget-avatar");
  var brandingEl = root.querySelector("#ng-widget-branding");
  var popupEl = root.querySelector("#ng-widget-popup");
  var popupTextEl = root.querySelector("#ng-widget-popup-text");

  var cfg = { name: DEFAULT_NAME, logo: null, welcome: DEFAULT_WELCOME, questions: [] };
  var welcomeShown = false;

  function setOpen(open) {
    root.classList.toggle("ng-open", open);
    bubbleEl.setAttribute("aria-label", open ? "Close chat" : "Open chat");
    if (open) {
      popupEl.classList.remove("ng-visible");
      showWelcome();
      inputEl.focus();
      pollUpdates();
    } else {
      stopPolling();
    }
  }

  bubbleEl.addEventListener("click", function () {
    setOpen(!root.classList.contains("ng-open"));
  });
  labelEl.addEventListener("click", function () {
    setOpen(true);
  });
  root.querySelector("#ng-widget-close-mobile").addEventListener("click", function () {
    setOpen(false);
  });
  popupEl.addEventListener("click", function (event) {
    if (event.target && event.target.id === "ng-widget-popup-close") {
      popupEl.classList.remove("ng-visible");
      return;
    }
    setOpen(true);
  });

  // Message text is inserted as DOM text nodes (never innerHTML). Only http(s) URLs become links, so a reply that
  // contains a QR-page link is tappable while nothing else in a message can ever inject markup or a javascript: URL.
  function fillWithLinks(el, text) {
    var re = /(https?:\/\/[^\s<>"']+)/g, last = 0, m;
    while ((m = re.exec(text)) !== null) {
      var url = m[1].replace(/[.,;:!?)]+$/, "");
      el.appendChild(document.createTextNode(text.slice(last, m.index)));
      var a = document.createElement("a");
      a.href = url; a.textContent = url; a.target = "_blank"; a.rel = "noopener noreferrer";
      el.appendChild(a);
      last = m.index + url.length;
      re.lastIndex = last;
    }
    el.appendChild(document.createTextNode(text.slice(last)));
  }

  function initials(name) {
    return (name || "").split(/\s+/).filter(Boolean).slice(0, 2).map(function (w) { return w.charAt(0).toUpperCase(); }).join("") || "?";
  }

  // The business's logo if it has one, otherwise its initials.
  function fillAvatar(el) {
    el.textContent = "";
    if (cfg.logo) {
      var img = document.createElement("img");
      img.src = cfg.logo; img.alt = "";
      el.appendChild(img);
    } else {
      el.textContent = initials(cfg.name);
    }
  }

  function appendMessage(text, sender) {
    var row = document.createElement("div");
    row.className = "ng-row " + (sender === "customer" ? "ng-row-customer" : "ng-row-agent");
    if (sender !== "customer") {
      var av = document.createElement("div");
      av.className = "ng-avatar";
      fillAvatar(av);
      row.appendChild(av);
    }
    var el = document.createElement("div");
    el.className = "ng-msg " + (sender === "customer" ? "ng-msg-customer" : "ng-msg-agent");
    fillWithLinks(el, text);
    row.appendChild(el);
    messagesEl.insertBefore(row, typingEl);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // The greeting and suggested questions, shown the first time the panel opens in this page view.
  function showWelcome() {
    if (welcomeShown) return;
    welcomeShown = true;
    if (cfg.welcome) appendMessage(cfg.welcome, "agent");
    renderChips();
  }

  function renderChips() {
    chipsEl.textContent = "";
    cfg.questions.forEach(function (q) {
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "ng-chip";
      chip.textContent = q;
      chip.addEventListener("click", function () {
        sendText(q);
      });
      chipsEl.appendChild(chip);
    });
  }

  // Renders a text-message reply as several agent bubbles when the backend split it
  // (response_bubbles, additive/optional -- see WidgetMessageResponse), otherwise falls back
  // to a single bubble. Text-message path only -- the voice reply path never sends/checks this field.
  function appendAgentReply(data) {
    if (Array.isArray(data.response_bubbles) && data.response_bubbles.length > 1) {
      for (var i = 0; i < data.response_bubbles.length; i++) appendMessage(data.response_bubbles[i], "agent");
    } else if (data.response) {
      appendMessage(data.response, "agent");
    }
  }

  function setTyping(visible) {
    typingEl.classList.toggle("ng-visible", visible);
    if (visible) messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function orDefault(value, fallback) {
    return typeof value === "string" && value.trim() ? value.trim() : fallback;
  }

  // ---- apply the business's branding and widget settings; anything missing keeps its default. ----
  function applyConfig(config) {
    config = config || {};
    var color = /^#[0-9a-f]{6}$/i.test(config.brand_color || "") ? config.brand_color : DEFAULT_COLOR;
    root.style.setProperty("--ng-color", color);
    root.style.setProperty("--ng-on-color", readableOn(color));
    root.classList.toggle("ng-left", config.position === "left");
    root.classList.toggle("ng-dark", config.theme === "dark");

    cfg.name = orDefault(config.display_name, orDefault(config.name, DEFAULT_NAME));
    cfg.logo = config.logo_url ? new URL(config.logo_url, apiBase).href : null;
    cfg.welcome = orDefault(config.welcome_message, DEFAULT_WELCOME);
    cfg.questions = Array.isArray(config.suggested_questions)
      ? config.suggested_questions.filter(function (q) { return typeof q === "string" && q.trim(); }).slice(0, 4)
      : [];

    headerNameEl.textContent = cfg.name;
    headerStatusEl.textContent = orDefault(config.subtitle, DEFAULT_SUBTITLE);
    fillAvatar(headerAvatarEl);
    inputEl.placeholder = orDefault(config.input_placeholder, DEFAULT_PLACEHOLDER);
    brandingEl.hidden = config.show_branding === false;

    var label = orDefault(config.launcher_label, "");
    labelEl.textContent = label;
    labelEl.hidden = !label;

    openIconEl.textContent = "";
    if (config.launcher_icon === "logo" && cfg.logo) {
      var img = document.createElement("img");
      img.src = cfg.logo; img.alt = "";
      openIconEl.appendChild(img);
    } else {
      openIconEl.innerHTML = svg(LAUNCHER_ICONS[config.launcher_icon] || LAUNCHER_ICONS.chat);
    }

    // Floating greeting above the button, once per browser session, after the configured delay.
    var popupSeen = false;
    try { popupSeen = window.sessionStorage.getItem(popupKey) === "1"; } catch (e) { /* storage blocked */ }
    if (config.show_popup !== false && cfg.welcome && (previewConfig || !popupSeen)) {
      popupTextEl.textContent = cfg.welcome;
      var delay = Math.max(0, Math.min(60, Number(config.popup_delay_seconds) || 0));
      setTimeout(function () {
        if (root.classList.contains("ng-open")) return;
        popupEl.classList.add("ng-visible");
        try { window.sessionStorage.setItem(popupKey, "1"); } catch (e) { /* storage blocked */ }
      }, previewConfig ? 300 : delay * 1000);
    }

    root.classList.remove("ng-loading");
    if (startOpen) setOpen(true);
  }

  if (previewConfig) {
    applyConfig(previewConfig);
  } else {
    fetch(configEndpoint)
      .then(function (res) {
        if (!res.ok) throw new Error("config fetch failed: " + res.status);
        return res.json();
      })
      .then(applyConfig)
      .catch(function () {
        /* a business with no reachable config still gets a fully working, generically-branded widget */
        applyConfig({});
      });
  }

  // ---- messages the business sends on its own: the widget has no push channel, so while the panel is open (and the tab
  // visible) it asks the server for anything newer than the last message it has seen -- a staff member's reply from the
  // inbox, or the "payment received" message once the gateway confirms. Every 10s; every 5s for 30 min after a reply that
  // contained a payment link. The cursor is the last message id this page knows (the AI reply, or the visitor's own message
  // when a staff member owns the conversation and no AI reply comes). ----
  var lastMessageId = null, pollTimer = null, payDeadline = 0;

  function stopPolling() {
    clearTimeout(pollTimer);
    pollTimer = null;
  }

  function schedulePoll() {
    stopPolling();
    if (!lastMessageId || !root.classList.contains("ng-open") || document.hidden) return;
    pollTimer = setTimeout(pollUpdates, Date.now() < payDeadline ? 5000 : 10000);
  }

  function pollUpdates() {
    pollTimer = null;
    var token = getSessionToken();
    if (!token || !lastMessageId) return;
    if (inputEl.disabled) return schedulePoll(); /* a reply is in flight: the submit handler appends it itself */
    fetch(updatesEndpoint + "?session_token=" + encodeURIComponent(token) + "&after=" + encodeURIComponent(lastMessageId))
      .then(function (res) { return res.ok ? res.json() : { messages: [] }; })
      .then(function (data) {
        (data.messages || []).forEach(function (m) {
          appendMessage(m.content, "agent");
          lastMessageId = m.id;
        });
      })
      .catch(function () { /* transient: the next tick retries */ })
      .finally(schedulePoll);
  }

  function noteTurn(data) {
    lastMessageId = data.agent_message_id || data.customer_message_id || lastMessageId;
    if (data.response && /\/pay-qr\/|\/payments\//.test(data.response)) payDeadline = Date.now() + 30 * 60 * 1000;
    schedulePoll();
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stopPolling();
    else pollUpdates();
  });

  function setSending(disabled) {
    inputEl.disabled = disabled;
    sendEl.disabled = disabled;
    voiceBtn.disabled = disabled;
  }

  function sendText(content) {
    content = (content || "").trim();
    if (!content || inputEl.disabled) return;

    chipsEl.textContent = ""; /* suggestions are a starting point; they go once the visitor has asked something */
    appendMessage(content, "customer");
    inputEl.value = "";
    setSending(true);
    setTyping(true);

    fetch(messagesEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_token: getSessionToken(), content: content }),
    })
      .then(function (res) {
        if (!res.ok) throw new Error("request failed: " + res.status);
        return res.json();
      })
      .then(function (data) {
        setSessionToken(data.session_token);
        setTyping(false);
        /* response is null while a staff member owns the conversation: nothing to show for this turn */
        appendAgentReply(data);
        noteTurn(data);
      })
      .catch(function () {
        setTyping(false);
        appendMessage("Sorry, something went wrong. Please try again in a moment.", "agent");
      })
      .finally(function () {
        setSending(false);
        inputEl.focus();
      });
  }

  formEl.addEventListener("submit", function (event) {
    event.preventDefault();
    sendText(inputEl.value);
  });

  // ---- Phase 43h: push-to-talk voice input. Click the mic to start
  // recording (MediaRecorder), click it again to stop -- the ONE recorded
  // clip is uploaded as a single blob to the backend, which transcribes it
  // (Deepgram pre-recorded STT) and runs it through the EXACT SAME
  // orchestrator turn typed text does (widget_service.send_widget_message).
  // The reply always comes back as plain text and renders into the SAME
  // #ng-widget-messages list, over the SAME session_token as typed chat --
  // there is no live call, no persistent connection, and no spoken audio
  // output anywhere in this flow. ----

  var mediaRecorder = null;
  var mediaStream = null;
  var recordedChunks = [];
  var isRecording = false;

  function stopMediaStream() {
    if (mediaStream) {
      mediaStream.getTracks().forEach(function (track) {
        track.stop();
      });
      mediaStream = null;
    }
  }

  function sendVoiceRecording(blob) {
    setSending(true);
    setTyping(true);
    chipsEl.textContent = "";

    var formData = new FormData();
    formData.append("audio", blob, "voice-message.webm");
    var token = getSessionToken();
    if (token) formData.append("session_token", token);

    fetch(voiceMessageEndpoint, { method: "POST", body: formData })
      .then(function (res) {
        if (!res.ok) throw new Error("request failed: " + res.status);
        return res.json();
      })
      .then(function (data) {
        setTyping(false);
        if (data.session_token) setSessionToken(data.session_token);
        if (data.transcript) appendMessage(data.transcript, "customer");
        if (data.response) appendMessage(data.response, "agent");
        noteTurn(data);
      })
      .catch(function () {
        setTyping(false);
        appendMessage("Sorry, something went wrong with that voice message. Please try again.", "agent");
      })
      .finally(function () {
        setSending(false);
      });
  }

  function startRecording() {
    if (isRecording) return;
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      appendMessage("Sorry, voice messages aren't supported in this browser. You can keep typing instead.", "agent");
      return;
    }

    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then(function (stream) {
        mediaStream = stream;
        recordedChunks = [];
        var options = { mimeType: "audio/webm;codecs=opus" };
        try {
          mediaRecorder = window.MediaRecorder.isTypeSupported && window.MediaRecorder.isTypeSupported(options.mimeType)
            ? new MediaRecorder(stream, options)
            : new MediaRecorder(stream);
        } catch (e) {
          mediaRecorder = new MediaRecorder(stream);
        }
        mediaRecorder.addEventListener("dataavailable", function (event) {
          if (event.data && event.data.size > 0) recordedChunks.push(event.data);
        });
        mediaRecorder.addEventListener("stop", function () {
          stopMediaStream();
          var blob = new Blob(recordedChunks, { type: mediaRecorder.mimeType || "audio/webm" });
          recordedChunks = [];
          if (blob.size > 0) sendVoiceRecording(blob);
        });
        mediaRecorder.start();
        isRecording = true;
        voiceBtn.classList.add("ng-recording");
        voiceBtn.setAttribute("aria-label", "Stop recording");
      })
      .catch(function () {
        appendMessage(
          "Microphone access was denied, so voice messages aren't available. You can keep typing instead.",
          "agent"
        );
      });
  }

  function stopRecording() {
    if (!isRecording) return;
    isRecording = false;
    voiceBtn.classList.remove("ng-recording");
    voiceBtn.setAttribute("aria-label", "Start voice message");
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    } else {
      stopMediaStream();
    }
  }

  voiceBtn.addEventListener("click", function () {
    if (isRecording) stopRecording();
    else startRecording();
  });
})();
