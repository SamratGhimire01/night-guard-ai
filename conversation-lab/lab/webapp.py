"""Sandbox chat UI (stdlib only, no new dependency). Distinct from the
production widget and from backend's /test-chat: separate port, separate
look, banner says NON-PRODUCTION. Shows the baseline reply plus the real judge
score for every turn.  Run:  python -m lab.webapp   ->  http://127.0.0.1:8765"""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lab.businesses import BUSINESSES, facts_text
from lab.judge import ReplyJudge
from lab.llm import build_lm, configure
from lab.receptionist import BaselineReceptionist

PORT = 8765
# Interactive speed settings (measured in LAB_STATUS.md). None = deployment default effort. The calibrated,
# rigorous judge (validate_judge.py, the "re-score x5" button) always uses the default-effort judge.
REPLY_EFFORT = "low"
QUICK_JUDGE_EFFORT = "low"
_reply_lm = None
_quick_judge_lm = None

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Conversation Lab (sandbox)</title>
<style>
body{margin:0;font:15px system-ui,sans-serif;background:#1b1230;color:#eee}
.banner{background:#b3261e;color:#fff;text-align:center;padding:6px;font-weight:700;letter-spacing:.5px}
.wrap{max-width:860px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:6px 0}.sub{color:#b9a9e0;font-size:13px;margin-bottom:10px}
details.facts{background:#261a45;border-radius:8px;padding:8px 12px;margin-bottom:12px;color:#cdbff0;font-size:13px}
#log{background:#241a3f;border-radius:10px;padding:12px;min-height:340px;max-height:56vh;overflow:auto}
.msg{margin:10px 0;max-width:82%;padding:9px 12px;border-radius:12px;white-space:pre-wrap}
.me{background:#4b3a8f;margin-left:auto}.bot{background:#33285c}
.meta{margin-top:6px;font-size:12px;color:#cbbdf0}
.rescore{padding:2px 9px;font-size:12px;margin-left:8px}.badge{display:inline-block;padding:2px 9px;border-radius:10px;font-weight:700;color:#111}
details.why{margin-top:4px}summary{cursor:pointer}
table{border-collapse:collapse;margin-top:4px}td{padding:1px 10px 1px 0;font-size:12px}
form{display:flex;gap:8px;margin-top:12px}input[type=text]{flex:1;padding:10px;border-radius:8px;border:0;background:#2d2150;color:#fff}
button,select{padding:10px 14px;border-radius:8px;border:0;background:#7c5cff;color:#fff;font-weight:600}
select{background:#2d2150}.busy{opacity:.6}
</style></head><body>
<div class="banner">CONVERSATION LAB &mdash; NON-PRODUCTION SANDBOX &mdash; fictional business, no real customer data</div>
<div class="wrap"><h1>Conversation Lab: baseline receptionist + judge</h1>
<div class="sub">Unoptimized baseline &middot; real Azure gpt-5-mini for both the reply and the judge</div>
<div style="margin-bottom:8px">Business: <select id="biz">__BIZ_OPTIONS__</select> <span class="sub">(changing it starts a new conversation)</span></div>
<details class="facts"><summary>Sandbox business facts the bot sees</summary><pre id="facts">__FACTS__</pre></details>
<div id="log"></div>
<form id="f"><input id="t" type="text" autocomplete="off" placeholder="Type a customer message (English / Nepali / Roman Nepali)..." autofocus>
<select id="s" title="judge samples per turn (x1 = fast; each reply also has a re-score x5 button)"><option value="1">judge x1 (fast)</option><option value="3">judge x3</option><option value="5">judge x5</option></select>
<button id="b">Send</button></form></div>
<script>
const log=document.getElementById('log'),t=document.getElementById('t'),b=document.getElementById('b'),s=document.getElementById('s');
let turns=[];const biz=document.getElementById('biz');
function color(x){return x>=80?'#6ee7a0':x>=55?'#ffd166':'#ff7b7b'}
function add(cls,text){const d=document.createElement('div');d.className='msg '+cls;d.textContent=text;log.appendChild(d);log.scrollTop=log.scrollHeight;return d}
function meta(j,timing){const rows=Object.entries(j.criteria).map(([k,v])=>`<tr><td>${k}</td><td>${v}/5</td></tr>`).join('');
 return `judge score <span class="badge" style="background:${color(j.score)}">${j.score}</span> /100 &nbsp;(${j.samples} sample${j.samples>1?'s':''}: ${j.per_sample.join(', ')}) &nbsp; words ${j.objective.word_count}, emoji ${j.objective.emoji_count}, ends with "?" ${j.objective.ends_with_question} &nbsp; <span style="opacity:.75">${timing}</span>`+
 `<details class="why"><summary>why this score</summary><table>${rows}</table><div style="max-width:640px;margin-top:4px">${j.reasoning.replace(/</g,'&lt;')}</div></details>`}
function attach(bot,m,reply,hist,j,timing){const d=document.createElement('div');d.className='meta';d.innerHTML=meta(j,timing);
 const btn=document.createElement('button');btn.className='rescore';btn.textContent='re-score x5 (calibrated judge)';
 btn.onclick=async()=>{btn.disabled=true;btn.textContent='scoring x5...';
  try{const r=await fetch('/api/judge',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m,response:reply,history:hist,business:biz.value,samples:5})});
   const k=await r.json();if(k.error){btn.textContent='ERROR';return}d.innerHTML=meta(k,`judge ${k.judge_s}s`)}catch(e){btn.textContent='ERROR'}};
 d.appendChild(btn);bot.appendChild(d)}
biz.onchange=async()=>{turns=[];log.innerHTML='';const r=await fetch('/api/facts?business='+biz.value);document.getElementById('facts').textContent=(await r.json()).facts;t.focus()};
document.getElementById('f').onsubmit=async e=>{e.preventDefault();const m=t.value.trim();if(!m)return;t.value='';
 add('me',m);const bot=add('bot','...thinking (reply, then judge)');b.classList.add('busy');b.disabled=true;
 try{const hist=turns.slice();const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m,history:hist,business:biz.value,samples:+s.value})});
  const j=await r.json();if(j.error){bot.textContent='ERROR: '+j.error;return}
  bot.textContent=j.response;turns.push(['Customer',m],['Assistant',j.response]);
  attach(bot,m,j.response,hist,j,`reply ${j.reply_s}s + judge ${j.judge_s}s`);
 }catch(err){bot.textContent='ERROR: '+err}finally{b.classList.remove('busy');b.disabled=false;t.focus()}};
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            opts = "".join(f'<option value="{k}">{v["name"]} ({v["type"]})</option>' for k, v in BUSINESSES.items())
            page = PAGE.replace("__BIZ_OPTIONS__", opts).replace("__FACTS__", facts_text("dental"))
            self._send(200, page.encode(), "text/html; charset=utf-8")
        elif self.path.startswith("/api/facts?business="):
            key = self.path.split("=", 1)[1]
            self._send(200, json.dumps({"facts": facts_text(key)}).encode(), "application/json") if key in BUSINESSES \
                else self._send(404, b"unknown business", "text/plain")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path not in ("/api/chat", "/api/judge"):
            return self._send(404, b"not found", "text/plain")
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            message = str(data["message"])[:2000]
            history = [(str(a), str(b)) for a, b in data.get("history", [])][-20:]
            biz = data.get("business", "dental")
            if biz not in BUSINESSES:
                raise ValueError(f"unknown business {biz!r}")
            samples = max(1, min(5, int(data.get("samples", 1))))
            convo = "\n".join(f"{a}: {b}" for a, b in history)
            reply_s = 0.0
            if self.path == "/api/chat":
                t = time.time()
                response = BaselineReceptionist(biz)(customer_message=message, history=history, lm=_reply_lm).response
                reply_s = round(time.time() - t, 1)
                judge = ReplyJudge(samples=samples, lm=_quick_judge_lm)  # quick judge: interactive speed settings
            else:
                response = str(data["response"])[:4000]
                judge = ReplyJudge(samples=samples)  # calibrated judge: default effort, same as validate_judge.py
            t = time.time()
            j = judge(message, response, conversation=convo, facts=facts_text(biz))
            out = {"response": response, "score": j.score, "criteria": j.criteria, "objective": j.objective,
                   "reasoning": j.reasoning, "samples": j.samples, "per_sample": j.per_sample_scores,
                   "reply_s": reply_s, "judge_s": round(time.time() - t, 1)}
            self._send(200, json.dumps(out, ensure_ascii=False).encode(), "application/json")
        except Exception as exc:  # sandbox tool: surface errors in the UI, never crash the server
            self._send(200, json.dumps({"error": f"{type(exc).__name__}: {exc}"[:300]}).encode(), "application/json")

    def log_message(self, *args):  # keep the terminal quiet; no message content logged
        pass


def main() -> None:
    global _reply_lm, _quick_judge_lm
    configure()
    _reply_lm = build_lm(reasoning_effort=REPLY_EFFORT) if REPLY_EFFORT else None
    _quick_judge_lm = build_lm(reasoning_effort=QUICK_JUDGE_EFFORT) if QUICK_JUDGE_EFFORT else None
    print(f"Conversation Lab (NON-PRODUCTION) on http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
