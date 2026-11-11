"""Build a single-file offline demo (web UI + recorded API replay) from web/index.html and a recorded snapshot."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
snap = Path(sys.argv[1]).read_text()
out = Path(sys.argv[2])
html = (root / "web" / "index.html").read_text()
SHIM = r"""
<script>
/* Static replay layer: serves recorded responses from a real Meridian run so the UI works without a backend. */
(()=>{
const SNAP=__SNAP__;
const state={appr:[],pos:JSON.parse(JSON.stringify(SNAP.portfolio.positions)),n:0};
const J=(o,s=200)=>new Response(JSON.stringify(o),{status:s,headers:{"Content-Type":"application/json"}});
const SY=Object.keys(SNAP.symbols);
function pick(prompt){
  const p=prompt.trim();if(SNAP.runs[p])return p;const l=p.toLowerCase();
  const syms=SY.filter(s=>new RegExp("\\b"+s+"\\b","i").test(p));
  if(/propose|buy|sell|request/.test(l))return"Propose to buy 10 shares of MSFT";
  if(/backtest/.test(l))return"Backtest RSI 25 on AMD";
  if(/what if|allocation|%/.test(l)&&syms.length>1)return"What if I put 40% NVDA, 30% MSFT, 30% AAPL?";
  if(/compare|vs/.test(l)||syms.length>1)return"Compare AAPL vs MSFT vs GOOGL";
  if(/portfolio|holdings|book/.test(l))return"Review my portfolio";
  if(/regime|market|health/.test(l))return"How healthy is the market regime today?";
  if(/screen|rsi|oversold|find/.test(l))return"Screen Nasdaq tech for RSI below 40 and size a $250k allocation";
  if(syms.length)return"Analyze "+syms[0].toUpperCase();
  return"Analyze NVDA";}
const runs={};
const realFetch=window.fetch;
window.fetch=async(path,o={})=>{
  const url=String(path),m=(o.method||"GET").toUpperCase(),role=(o.headers&&o.headers["X-Role"])||"viewer";
  await new Promise(r=>setTimeout(r,60));
  let x;
  if(url==="/api/health"){const h={...SNAP.health,jobs:"recorded replay",sandbox:"recorded",mcp_transport:"inproc"};return J(h)}
  if(url==="/api/overview")return J(SNAP.overview);
  if((x=url.match(/^\/api\/symbol\/([A-Za-z.]+)/)))return SNAP.symbols[x[1].toUpperCase()]?J(SNAP.symbols[x[1].toUpperCase()]):J({detail:"Symbol not in recorded universe"},404);
  if(url==="/api/portfolio"){const pos=state.pos,tv=pos.reduce((a,b)=>a+b.market_value,0);return J({...SNAP.portfolio,total_value:tv,positions:pos.map(q=>({...q,weight:q.market_value/tv}))})}
  if(url==="/api/approvals"&&m==="GET")return J(state.appr);
  if(url==="/api/approvals"&&m==="POST"){if(role==="viewer")return J({detail:"role viewer cannot request trades"},403);const b=JSON.parse(o.body),pr=(state.pos.find(q=>q.symbol===b.symbol)||{}).price||(SNAP.symbols[b.symbol]||{}).price||100;const a={id:"apr_"+Math.random().toString(16).slice(2,10),run_id:b.run_id||"ui",symbol:b.symbol,side:b.side,qty:b.qty,price:pr,rationale:b.rationale||"",status:"pending",requested_by:"demo-"+role,decided_by:null,created:Date.now()/1000,decided_at:null,execution_json:null};state.appr.unshift(a);return J(a)}
  if((x=url.match(/^\/api\/approvals\/([^/]+)\/decide/))){if(role!=="pm")return J({detail:"only the pm role can decide approvals"},403);const a=state.appr.find(q=>q.id===x[1]);if(!a)return J({detail:"not found"},404);a.status=JSON.parse(o.body).decision;a.decided_by="demo-pm";a.decided_at=Date.now()/1000;
    if(a.status==="approved"){let q=state.pos.find(z=>z.symbol===a.symbol);const sign=a.side==="buy"?1:-1;if(!q){q={symbol:a.symbol,qty:0,avg_cost:a.price,price:a.price,market_value:0,pnl_pct:0,weight:0};state.pos.push(q)}
      if(sign<0&&q.qty<a.qty){a.status="rejected";return J(a)}q.qty+=sign*a.qty;q.market_value=q.qty*q.price}return J(a)}
  if(url==="/api/audit/verify")return J(SNAP.audit_verify);
  if((x=url.match(/^\/api\/audit\/(.+)/))){const r=runs[x[1]];return J(r?r.audit:[])}
  if(url==="/api/runs"&&m==="POST"){if(role==="viewer"){/* viewers may analyse */}const b=JSON.parse(o.body),k=pick(b.prompt),rec=SNAP.runs[k],id="run_"+(++state.n)+Math.random().toString(16).slice(2,8);
    const run=JSON.parse(JSON.stringify(rec.run));run.id=id;run.prompt=b.prompt;if(run.result&&run.result.intent==="propose"&&!state.appr.some(a=>a.run_id===id)){const mm=(run.result.cards||[])[0]||{};}
    runs[id]={rec,run,audit:rec.audit};
    if(run.result&&run.result.intent==="propose"){const pr=(state.pos.find(q=>q.symbol==="MSFT")||{}).price||593.63;state.appr.unshift({id:"apr_"+id.slice(-8),run_id:id,symbol:"MSFT",side:"buy",qty:10,price:pr,rationale:"Requested via copilot: buy 10 MSFT",status:"pending",requested_by:"agent",decided_by:null,created:Date.now()/1000,decided_at:null,execution_json:null})}
    return J({run_id:id,session_id:b.session_id||"sess_demo",backend:"recorded replay",status:"queued"},202)}
  if((x=url.match(/^\/api\/runs\/([^/]+)$/))){const r=runs[x[1]];return r?J(r.run):J({detail:"run not found"},404)}
  return J({detail:"not available in the static demo"},404)};
window.EventSource=class{constructor(u){this.l={};const id=u.split("/")[3],r=runs[id];this.onerror=null;
  const steps=(r?r.rec.steps:[]);let i=0;const tick=()=>{if(i<steps.length){(this.l.step||[]).forEach(f=>f({data:JSON.stringify(steps[i])}));i++;this._t=setTimeout(tick,110)}else{(this.l.done||[]).forEach(f=>f({data:"{}"}))}};this._t=setTimeout(tick,150)}
  addEventListener(n,f){(this.l[n]=this.l[n]||[]).push(f)}close(){clearTimeout(this._t)}};
document.addEventListener("DOMContentLoaded",()=>{const b=document.createElement("div");b.style.cssText="position:fixed;bottom:10px;right:12px;z-index:99;background:#16263dcc;color:#f6b84b;border:1px solid #f6b84b55;padding:5px 10px;border-radius:999px;font:11px Inter,sans-serif";b.textContent="Recorded replay of a real run · simulated market data · full stack: see repo";document.body.appendChild(b)});
})();
</script>
"""
html = html.replace("<script>", SHIM.replace("__SNAP__", snap) + "\n<script>", 1)
out.write_text(html)
print(out, len(html))
