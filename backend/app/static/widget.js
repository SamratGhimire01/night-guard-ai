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
  var voiceMessageEndpoint = apiBase + "/api/v1/widget/" + encodeURIComponent(businessId) + "/voice-message";
  var storageKey = "nightguard_widget_session_" + businessId;

  // Defaults used until (or if) the real branding fetch below resolves —
  // never blocks first paint on a network round trip.
  var DEFAULT_COLOR = "#2563eb";
  var DEFAULT_NAME = "Chat with us";

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

  // ---- styling: static rules go in one injected <style> tag; the one
  // truly per-business value (brand color) is applied via a CSS custom
  // property on the widget root, so it can be updated later (once the real
  // config loads) without re-injecting any CSS text. ----

  var style = document.createElement("style");
  style.textContent =
    "#ng-widget-root{--ng-color:" + DEFAULT_COLOR + ";position:fixed;bottom:20px;right:20px;z-index:999999;" +
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;}" +
    "#ng-widget-bubble{width:60px;height:60px;border-radius:50%;background:var(--ng-color);color:#fff;" +
    "display:flex;align-items:center;justify-content:center;cursor:pointer;border:none;" +
    "box-shadow:0 4px 16px rgba(0,0,0,.22);transition:transform .15s ease;}" +
    "#ng-widget-bubble:hover{transform:scale(1.06);}" +
    "#ng-widget-bubble svg{width:26px;height:26px;transition:opacity .12s ease,transform .12s ease;}" +
    "#ng-widget-bubble .ng-icon-close{position:absolute;opacity:0;transform:rotate(-90deg) scale(.6);}" +
    "#ng-widget-root.ng-open #ng-widget-bubble .ng-icon-chat{opacity:0;transform:rotate(90deg) scale(.6);}" +
    "#ng-widget-root.ng-open #ng-widget-bubble .ng-icon-close{opacity:1;transform:rotate(0) scale(1);}" +
    "#ng-widget-panel{position:absolute;bottom:76px;right:0;width:340px;max-height:480px;background:#fff;" +
    "border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.2);display:flex;flex-direction:column;" +
    "overflow:hidden;opacity:0;transform:translateY(12px) scale(.98);pointer-events:none;" +
    "transition:opacity .18s ease,transform .18s ease;}" +
    "#ng-widget-root.ng-open #ng-widget-panel{opacity:1;transform:translateY(0) scale(1);pointer-events:auto;}" +
    "#ng-widget-header{background:var(--ng-color);color:#fff;padding:16px;display:flex;align-items:center;gap:10px;}" +
    "#ng-widget-header img{width:32px;height:32px;border-radius:50%;object-fit:cover;background:#fff;}" +
    "#ng-widget-header-name{font-size:15px;font-weight:600;line-height:1.2;}" +
    "#ng-widget-header-status{font-size:12px;opacity:.85;}" +
    "#ng-widget-messages{flex:1;overflow-y:auto;padding:14px;font-size:13.5px;background:#f7f8fa;min-height:220px;max-height:340px;}" +
    ".ng-msg{margin:5px 0;padding:9px 13px;border-radius:16px;max-width:80%;line-height:1.45;white-space:pre-wrap;" +
    "animation:ng-msg-in .15s ease;}" +
    "@keyframes ng-msg-in{from{opacity:0;transform:translateY(4px);}to{opacity:1;transform:translateY(0);}}" +
    ".ng-msg-customer{background:var(--ng-color);color:#fff;margin-left:auto;border-bottom-right-radius:4px;}" +
    ".ng-msg-agent{background:#fff;color:#1a1a1a;margin-right:auto;border-bottom-left-radius:4px;" +
    "box-shadow:0 1px 2px rgba(0,0,0,.08);}" +
    "#ng-widget-typing{display:none;margin-right:auto;background:#fff;border-radius:16px;border-bottom-left-radius:4px;" +
    "padding:10px 14px;box-shadow:0 1px 2px rgba(0,0,0,.08);width:fit-content;}" +
    "#ng-widget-typing.ng-visible{display:block;}" +
    "#ng-widget-typing span{display:inline-block;width:6px;height:6px;margin:0 1px;border-radius:50%;" +
    "background:#9aa0a6;animation:ng-typing 1.2s infinite;}" +
    "#ng-widget-typing span:nth-child(2){animation-delay:.15s;}" +
    "#ng-widget-typing span:nth-child(3){animation-delay:.3s;}" +
    "@keyframes ng-typing{0%,60%,100%{transform:translateY(0);opacity:.5;}30%{transform:translateY(-3px);opacity:1;}}" +
    "#ng-widget-form{display:flex;border-top:1px solid #e8e8ea;background:#fff;}" +
    "#ng-widget-input{flex:1;border:none;padding:13px 14px;font-size:13.5px;outline:none;font-family:inherit;}" +
    "#ng-widget-send{border:none;background:none;color:var(--ng-color);padding:0 16px;cursor:pointer;}" +
    "#ng-widget-send:disabled{opacity:.4;cursor:default;}" +
    "#ng-widget-send svg{width:20px;height:20px;}" +
    "#ng-widget-voice{border:none;background:none;color:var(--ng-color);padding:0 4px 0 14px;cursor:pointer;}" +
    "#ng-widget-voice:disabled{opacity:.4;cursor:default;}" +
    "#ng-widget-voice svg{width:19px;height:19px;}" +
    "#ng-widget-voice.ng-recording{color:#ef4444;animation:ng-pulse 1.2s infinite;}" +
    "@keyframes ng-pulse{0%,100%{opacity:.4;}50%{opacity:1;}}" +
    "#ng-widget-branding{text-align:center;font-size:10px;color:#b0b3b8;padding:4px 0 8px;background:#fff;}" +
    "@media (max-width:400px){#ng-widget-panel{width:calc(100vw - 32px);right:-4px;}}";
  document.head.appendChild(style);

  var root = document.createElement("div");
  root.id = "ng-widget-root";

  var CHAT_ICON =
    '<svg class="ng-icon-chat" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
    '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"' +
    ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var CLOSE_ICON =
    '<svg class="ng-icon-close" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
    '<path d="M18 6 6 18M6 6l12 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var SEND_ICON =
    '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
    '<path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var MIC_ICON =
    '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
    '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" stroke="currentColor" stroke-width="2"/>' +
    '<path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v4M8 22h8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  root.innerHTML =
    '<div id="ng-widget-panel">' +
    '<div id="ng-widget-header"><img id="ng-widget-logo" style="display:none" alt="" />' +
    '<div><div id="ng-widget-header-name">' + DEFAULT_NAME + "</div>" +
    '<div id="ng-widget-header-status">Typically replies in a few minutes</div></div></div>' +
    '<div id="ng-widget-messages"></div>' +
    '<div id="ng-widget-typing"><span></span><span></span><span></span></div>' +
    '<form id="ng-widget-form">' +
    '<input id="ng-widget-input" type="text" placeholder="Type a message..." autocomplete="off" />' +
    '<button id="ng-widget-voice" type="button" aria-label="Start voice message">' + MIC_ICON + "</button>" +
    '<button id="ng-widget-send" type="submit" aria-label="Send">' + SEND_ICON + "</button>" +
    "</form>" +
    '<div id="ng-widget-branding">Powered by Night Guard AI</div>' +
    "</div>" +
    '<button id="ng-widget-bubble" type="button" aria-label="Open chat">' + CHAT_ICON + CLOSE_ICON + "</button>";

  document.body.appendChild(root);

  var bubbleEl = root.querySelector("#ng-widget-bubble");
  var messagesEl = root.querySelector("#ng-widget-messages");
  var typingEl = root.querySelector("#ng-widget-typing");
  var formEl = root.querySelector("#ng-widget-form");
  var inputEl = root.querySelector("#ng-widget-input");
  var sendEl = root.querySelector("#ng-widget-send");
  var voiceBtn = root.querySelector("#ng-widget-voice");
  var headerNameEl = root.querySelector("#ng-widget-header-name");
  var logoEl = root.querySelector("#ng-widget-logo");

  bubbleEl.addEventListener("click", function () {
    var opening = !root.classList.contains("ng-open");
    root.classList.toggle("ng-open");
    bubbleEl.setAttribute("aria-label", opening ? "Close chat" : "Open chat");
    if (opening) inputEl.focus();
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

  function appendMessage(text, sender) {
    var el = document.createElement("div");
    el.className = "ng-msg " + (sender === "customer" ? "ng-msg-customer" : "ng-msg-agent");
    fillWithLinks(el, text);
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function setTyping(visible) {
    typingEl.classList.toggle("ng-visible", visible);
    if (visible) messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // ---- real branding fetch: business name, primary color, logo — falls
  // back to the defaults above on any failure (network error, 404, business
  // with no custom branding set) so the widget always renders regardless. ----
  fetch(configEndpoint)
    .then(function (res) {
      if (!res.ok) throw new Error("config fetch failed: " + res.status);
      return res.json();
    })
    .then(function (config) {
      if (config.name) headerNameEl.textContent = config.name;
      if (config.brand_color) root.style.setProperty("--ng-color", config.brand_color);
      if (config.logo_url) {
        logoEl.src = config.logo_url;
        logoEl.style.display = "block";
      }
    })
    .catch(function () {
      /* defaults already rendered — a business with no reachable config
         still gets a fully working, generically-branded widget */
    });

  function setSending(disabled) {
    inputEl.disabled = disabled;
    sendEl.disabled = disabled;
    voiceBtn.disabled = disabled;
  }

  formEl.addEventListener("submit", function (event) {
    event.preventDefault();
    var content = inputEl.value.trim();
    if (!content) return;

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
        appendMessage(data.response, "agent");
      })
      .catch(function () {
        setTyping(false);
        appendMessage("Sorry, something went wrong. Please try again in a moment.", "agent");
      })
      .finally(function () {
        setSending(false);
        inputEl.focus();
      });
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
        appendMessage(data.response, "agent");
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
