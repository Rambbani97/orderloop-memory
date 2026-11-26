#!/usr/bin/env python3
"""Generate the M8 phone-rating widget HTML from the 72-item sample pack.

Output: hidden_files/m8-rating-widget.html  (embedded data, <1MB)
State: window.hatchWidget bridge {scores: {blind_id: 0-100}, idx: int}
"""
import json
from pathlib import Path

BASE = Path.home() / "workspace/goals/contextcon-hackathon-tema-2-never-solve-it-twice"
RES = BASE / "build/orderloop-memory/results"
items = json.loads((BASE / "files/m8-rating/m8-rating-sample-72.json").read_text())
skey = json.loads((BASE / "hidden_files/m8-rating-sample-key.json").read_text())["mapping"]

# Jarvis verdict per item, from the harness auto quality score
# (m8_quality_auto on the exact (run, ticket) record): >=70 -> Tinggi, <70 -> Rendah.
auto = {}
for run in ["A1", "A2", "A3", "B1", "B2", "B3"]:
    p = RES / f"run-{run}" / f"run-{run}.jsonl"
    for line in p.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            auto[(run, r["ticket_id"])] = r["m8_quality_auto"]

# Seed state migrates the 1 rating already given in the old widget
# (widget-f57a421c, read 26 Nov ~12:48): S-001 = 70, idx = 1.
SEED_STATE = {"scores": {"S-001": 70}, "idx": 1}

data = []
for i in items:
    m = skey[i["blind_id"]]
    q = auto[(m["run"], i["ticket_id"])]
    data.append(
        {
            "blind_id": i["blind_id"],
            "ticket_subject": i["ticket_subject"],
            "ticket_body": i["ticket_body"],
            "fix_text": i["fix_text"],
            "gt_cause": i["ground_truth_root_cause"],
            "gt_fix": i["ground_truth_correct_fix"],
            "text_source": i["text_source"],
            "saran": "Tinggi" if q >= 70 else "Rendah",
        }
    )
data_json = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
seed_json = json.dumps(SEED_STATE, ensure_ascii=False).replace("<", "\\u003c")

HTML = r"""<div id="m8app" style="font-family:system-ui,-apple-system,sans-serif;color:var(--hatch-widget-text);background:var(--hatch-widget-bg);padding:12px;box-sizing:border-box;max-width:640px;margin:0 auto;">
<style>
#m8app .card{background:var(--hatch-widget-surface);border:1px solid var(--hatch-widget-border);border-radius:12px;padding:12px;margin:10px 0}
#m8app .box{background:var(--hatch-widget-surface-muted);border:1px solid var(--hatch-widget-border);border-radius:8px;padding:10px;max-height:180px;overflow:auto;white-space:pre-wrap;font-size:14px;line-height:1.5;margin:6px 0}
#m8app .lbl{font-size:12px;font-weight:700;letter-spacing:.04em;color:var(--hatch-widget-muted);text-transform:uppercase;margin:10px 0 2px}
#m8app button{font-size:16px;padding:12px 16px;border-radius:10px;border:1px solid var(--hatch-widget-border);background:var(--hatch-widget-surface);color:var(--hatch-widget-text);min-height:48px;cursor:pointer}
#m8app button.primary{background:var(--hatch-widget-accent);color:var(--hatch-widget-on-accent);border-color:var(--hatch-widget-accent);font-weight:700}
#m8app button:disabled{opacity:.45}
#m8app .row{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
#m8app .row button{flex:1}
#m8app .quick button{flex:1;padding:10px 4px;font-size:15px}
#m8app input[type=range]{width:100%;height:36px}
#m8app .bar{height:10px;border-radius:6px;background:var(--hatch-widget-surface-muted);overflow:hidden;margin:6px 0}
#m8app .bar>i{display:block;height:100%;background:var(--hatch-widget-accent)}
#m8app details{font-size:14px}
#m8app summary{cursor:pointer;font-weight:600;padding:6px 0}
#m8app .verdict{font-size:18px;font-weight:700;margin:6px 0}
#m8app .note{font-size:13px;color:var(--hatch-widget-muted)}
</style>
<div style="display:flex;justify-content:space-between;align-items:baseline">
<b style="font-size:18px">Rating M8 — 72 item</b>
<span id="prog" style="font-size:14px;color:var(--hatch-widget-muted)"></span>
</div>
<div class="bar"><i id="barfill" style="width:0%"></i></div>
<details><summary>Rubrik (lulus ≥ 70)</summary>
<div style="font-size:14px;line-height:1.6">Diagnosis 30 · Langkah 40 · Tanpa halusinasi 20 · Nada 10 · Bonus verifikasi +5.<br>Beri skor total 0–100 sesuai rubrik. Nilai isi fix vs ground truth, bukan tebakan kondisi A/B.</div></details>
<div id="view"></div>
<script>
const ITEMS = __DATA__;
const SEED = __SEED__;
let state = SEED;
let cur = null;
function el(tag, text, cls){ const e=document.createElement(tag); if(text!=null) e.textContent=text; if(cls) e.className=cls; return e; }
function load(){ try{ state = window.hatchWidget.getState(SEED) || SEED; }catch(e){} if(!state.scores) state.scores={}; if(state.idx==null) state.idx=0; render(); }
window.addEventListener('hatch-widget-state', function(e){ if(e.detail && e.detail.state){ state=e.detail.state; render(); } });
function persist(){ try{ window.hatchWidget.setState(state); }catch(e){} }
function done(){ return Object.keys(state.scores).length; }
function render(){
  const v=document.getElementById('view'); v.innerHTML='';
  document.getElementById('prog').textContent = done() + '/72 dinilai';
  document.getElementById('barfill').style.width = Math.round(done()/72*100) + '%';
  if(done()>=72){
    const c=el('div',null,'card');
    c.appendChild(el('b','Selesai — 72/72 sudah dinilai.'));
    c.appendChild(el('p','Kabarin Jarvis di chat kalau sudah selesai, nanti Jarvis buka kunci dan hitung hasilnya. Terima kasih, bang.'));
    const b=el('button','Lihat lagi item pertama',''); b.onclick=function(){ state.idx=0; persist(); render(); };
    c.appendChild(b); v.appendChild(c); return;
  }
  if(state.idx<0) state.idx=0; if(state.idx>=ITEMS.length) state.idx=ITEMS.length-1;
  const it=ITEMS[state.idx];
  const saved = state.scores[it.blind_id];
  const card=el('div',null,'card');
  const head=el('div',null,''); head.style.display='flex'; head.style.justifyContent='space-between';
  head.appendChild(el('b', it.blind_id + '  ·  item ' + (state.idx+1) + '/72'));
  head.appendChild(el('span', saved!=null ? ('Skor tersimpan: ' + saved) : 'Belum dinilai'));
  card.appendChild(head);
  card.appendChild(el('div', it.ticket_subject)); card.lastChild.style.cssText='font-size:17px;font-weight:700;margin:8px 0';
  if(it.text_source==='ops_reconstruction'){
    const n=el('div','Catatan: teks fix ini rekonstruksi dari trace operasi (bukan teks asli) — nilai berdasarkan operasi yang dieksekusi dan hasil verifikasinya.','note'); card.appendChild(n);
  }
  card.appendChild(el('div','Tiket','lbl')); const tb=el('div', it.ticket_body,'box'); card.appendChild(tb);
  card.appendChild(el('div','Fix yang dinilai','lbl')); const fb=el('div', it.fix_text,'box'); card.appendChild(fb);
  const det=document.createElement('details'); const sum=el('summary','Ground truth (pembanding)'); det.appendChild(sum);
  det.appendChild(el('div','Akar masalah: ' + it.gt_cause)); det.lastChild.style.cssText='font-size:14px;line-height:1.5;margin:4px 0';
  det.appendChild(el('div','Fix yang benar: ' + it.gt_fix)); det.lastChild.style.cssText='font-size:14px;line-height:1.5;margin:4px 0';
  card.appendChild(det);
  card.appendChild(el('div','Skor total (0–100)','lbl'));
  const saranLine=el('div','Saran Jarvis: ' + (it.saran==='Tinggi' ? 'Tinggi — skornya cenderung tinggi' : 'Rendah — skornya cenderung rendah'));
  saranLine.style.cssText='font-size:15px;font-weight:700;margin:2px 0 6px';
  card.appendChild(saranLine);
  const range=document.createElement('input'); range.type='range'; range.min=0; range.max=100; range.step=1;
  range.value = saved!=null ? saved : (it.saran==='Tinggi' ? 85 : 45); card.appendChild(range);
  const num=document.createElement('input'); num.type='number'; num.min=0; num.max=100; num.value=range.value;
  num.style.cssText='width:90px;font-size:18px;padding:8px;border-radius:8px;border:1px solid var(--hatch-widget-border);background:var(--hatch-widget-surface);color:var(--hatch-widget-text)';
  const verdict=el('div','', 'verdict');
  function sync(){ let s=parseInt(range.value,10); if(isNaN(s)) s=0; s=Math.max(0,Math.min(100,s)); range.value=s; num.value=s; cur=s; verdict.textContent = s + ' — ' + (s>=70 ? 'Lulus' : 'Belum lulus'); }
  range.oninput=function(){ sync(); }; num.oninput=function(){ range.value=num.value; sync(); };
  const mid=el('div',null,''); mid.style.cssText='display:flex;gap:10px;align-items:center;margin:6px 0'; mid.appendChild(num); mid.appendChild(verdict); card.appendChild(mid);
  const q=el('div',null,'row quick');
  [0,50,70,85,100].forEach(function(s){ const b=el('button',String(s)); b.onclick=function(){ range.value=s; sync(); }; q.appendChild(b); });
  card.appendChild(q); card.appendChild(el('div','Ketuk angka cepat atau geser slider, lalu simpan.','note'));
  const row=el('div',null,'row');
  const prev=el('button','← Sebelumnya'); prev.disabled = state.idx===0;
  prev.onclick=function(){ state.idx=Math.max(0,state.idx-1); persist(); render(); };
  const save=el('button', state.idx>=ITEMS.length-1 ? 'Simpan' : 'Simpan & lanjut →','primary');
  save.onclick=function(){ state.scores[it.blind_id]=cur; if(state.idx<ITEMS.length-1){ state.idx=state.idx+1; } persist(); render(); };
  row.appendChild(prev); row.appendChild(save); card.appendChild(row);
  const row2=el('div',null,'row');
  const jump=el('button','Ke item yang belum dinilai');
  jump.onclick=function(){ for(let k=0;k<ITEMS.length;k++){ if(state.scores[ITEMS[k].blind_id]==null){ state.idx=k; persist(); render(); return; } } };
  row2.appendChild(jump); card.appendChild(row2);
  v.appendChild(card);
  sync();
}
load();
</script></div>
"""
HTML = HTML.replace("__DATA__", data_json).replace("__SEED__", seed_json)
out = BASE / "hidden_files/m8-rating-widget.html"
out.write_text(HTML, encoding="utf-8")
print("wrote", out, len(HTML), "bytes")
