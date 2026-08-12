from pathlib import Path
from bs4 import BeautifulSoup
from collections import Counter
import re,json,hashlib,gzip,subprocess,zipfile
p=Path('index.html');s=p.read_text('utf-8')
# Versions and policy
s=s.replace("PRODUCT_VERSION='34.5.0-preview.16',UI_VERSION='32.0.0-preview.16'","PRODUCT_VERSION='35.0.0-preview.18',UI_VERSION='32.0.0-preview.18'",1)
s=s.replace("DIFFICULTY_POLICY_VERSION='3.0.0-preview.17'","DIFFICULTY_POLICY_VERSION='3.1.0-preview.1'",1)
# Policy probabilities and engine mix.
def replace_func(text,name,newf):
 start=text.find('function '+name+'(');brace=text.find('{',start);d=0;q=None;esc=False
 for i in range(brace,len(text)):
  c=text[i]
  if q:
   if esc:esc=False
   elif c=='\\':esc=True
   elif c==q:q=None
  else:
   if c in "'\"`":q=c
   elif c=='{':d+=1
   elif c=='}':
    d-=1
    if d==0:return text[:start]+newf+text[i+1:]
 raise ValueError(name)
s=replace_func(s,'engineMixPolicy',"function engineMixPolicy(level){return level==='EASY'?{analysis:0.95,strategic:0,random:0.05}:{analysis:1,strategic:0,random:0}}")
s=replace_func(s,'correctVetoSkipProbability',"function correctVetoSkipProbability(level){return level==='EASY'?0.75:level==='NORMAL'?0.45:level==='HARD'?0.10:0}")
# Existing incorrect SB retained unless explicitly superseded; analysis mix no longer calls strategic for EASY/NORMAL.
# Worker gzip decompression with safe main-thread fallback.
start=s.find("async function loadSolvedBuffer(")
brace=s.find("{",start);depth=0;quote=None;esc=False
for i in range(brace,len(s)):
 c=s[i]
 if quote:
  if esc:esc=False
  elif c=="\\":esc=True
  elif c==quote:quote=None
 else:
  if c in "\'\"`":quote=c
  elif c=="{":depth+=1
  elif c=="}":
   depth-=1
   if depth==0:break
old_func=s[start:i+1]
new_func="""async function loadSolvedBuffer(buf,source='builtin',name='標準内蔵データ'){let raw;if(typeof Worker==='function'&&typeof DecompressionStream==='function'){const code=`onmessage=async e=>{try{const st=new Blob([e.data]).stream().pipeThrough(new DecompressionStream('gzip'));const out=await new Response(st).arrayBuffer();postMessage({ok:true,out},[out])}catch(error){postMessage({ok:false,error:error.message})}}`;const url=URL.createObjectURL(new Blob([code],{type:'text/javascript'}));try{raw=await new Promise((resolve,reject)=>{const w=new Worker(url);w.onmessage=e=>{w.terminate();URL.revokeObjectURL(url);e.data.ok?resolve(e.data.out):reject(new Error(e.data.error))};w.onerror=e=>{w.terminate();URL.revokeObjectURL(url);reject(new Error(e.message||'Worker展開に失敗しました'))};w.postMessage(buf,[buf])})}catch(error){URL.revokeObjectURL(url)}}if(!raw){if(typeof DecompressionStream==='undefined')throw new Error('このブラウザーはgzip展開に対応していません。');const stream=new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'));raw=await new Response(stream).arrayBuffer()}solvedTable=new SolvedTable(raw);solvedFallbackReason='';const init=solvedTable.lookup(0x11111111);if(solvedTable.count!==8363027||!init||init.className!=='Lose'||init.distance!==42)throw new Error('解析データの互換性検証に失敗しました。');window.aiDataSource=source;window.aiDataName=name;$('#analysisStatus').className='analysisReady';$('#analysisStatus').textContent=`読込済み: ${solvedTable.count.toLocaleString()}局面 / 初期局面 ${init.className}(${init.distance})`;return init}"""
s=s[:start]+new_func+s[i+1:]
# Idle preparation: UI first; single promise already prevents duplication.
marker="window.__SB_STARTUP_PROFILE__={analysisPreparation:'on-demand',resultsFile:'second_best_results_v1.json'};"
s=s.replace(marker,"window.__SB_STARTUP_PROFILE__={analysisPreparation:'idle-worker',resultsFile:'second_best_results_v1.json'};if(location.protocol!=='file:'){const begin=()=>prepareBuiltinSolved().catch(()=>{});'requestIdleCallback'in window?requestIdleCallback(begin,{timeout:2500}):setTimeout(begin,900)}",1)
# Natural labels.
repls={
'このブラウザに一時保存':'この端末に保存','再開用JSONをダウンロード':'再開用ファイルを保存','再開用JSONを選択':'再開用ファイルを選ぶ',
'選択したログをダウンロード':'選んだ対局のログを保存','AI比較レポートをダウンロード':'AIの比較結果を保存',
'表示中の完了ログをまとめて削除':'表示中のログを削除','すべての完了ログを削除':'すべての終了ログを削除',
'AIデータ設定':'解析AIデータ','外部AIデータを読み込む':'解析データを選ぶ','標準内蔵データへ戻す':'標準データに戻す',
'不具合・感想の報告':'不具合や感想を送る','Second Bestの改善にご協力ください':'遊んでいて気づいたことを送れます'}
for a,b in repls.items():s=s.replace(a,b)
# Simple AI functions, independent from analysis and legacy strategic. Add selectable option, hidden by default.
s=s.replace('<option id="strategicOption" value="strategic">','<option id="simpleOption" value="simple" hidden>簡易AI（探索型）</option><option id="strategicOption" value="strategic" hidden>',1)
simple="""
function simpleEvaluate(st,p){const w=winner(st);if(w===p)return 100000;if(w===-p)return -100000;return threat(st,p)-threat(st,-p)+4*(legal(Object.assign(cp(st),{turn:p}),p).length-legal(Object.assign(cp(st),{turn:-p}),-p).length)}
function simpleSearch(st,depth,alpha,beta,p,ban=null,ctx={nodes:0,limit:120000,cache:new Map}){if(ctx.nodes++>=ctx.limit||depth<=0||winner(st))return simpleEvaluate(st,p);const key=JSON.stringify(st.b)+':'+st.turn+':'+depth;if(ctx.cache.has(key))return ctx.cache.get(key);let moves=legal(st).filter(m=>!ban||!eq(m,ban));if(!moves.length)return simpleEvaluate(st,p);let best=st.turn===p?-Infinity:Infinity;for(const m of moves){const v=simpleSearch(apply(st,m),depth-1,alpha,beta,p,null,ctx);if(st.turn===p){best=Math.max(best,v);alpha=Math.max(alpha,best)}else{best=Math.min(best,v);beta=Math.min(beta,best)}if(beta<=alpha)break}if(ctx.cache.size<60000)ctx.cache.set(key,best);return best}
function simpleChoose(st,ban=null){const p=st.turn,moves=legal(st).filter(m=>!ban||!eq(m,ban));if(!moves.length)return null;for(const m of moves)if(winner(apply(st,m))===p)return m;const depth=st.r[p===1?'w':'b']>0?3:(moves.length<=4?5:4),ctx={nodes:0,limit:120000,cache:new Map};let best=moves[0],score=-Infinity;for(const m of moves){const v=simpleSearch(apply(st,m),depth-1,-Infinity,Infinity,p,null,ctx);if(v>score){score=v;best=m}}return best}
"""
pos=s.find('function aiTurn()');s=s[:pos]+simple+s[pos:]
# Branch simple in proposal and alternative selection.
s=s.replace("if(mode==='random'){m=choices[Math.floor(Math.random()*choices.length)]}else if(mode==='solved'", "if(mode==='random'){m=choices[Math.floor(Math.random()*choices.length)]}else if(mode==='simple'){m=simpleChoose(S)}else if(mode==='solved'",1)
s=s.replace("?.proposal.move:null)||choose(S,ban)","?.proposal.move:null)||(mode==='simple'?simpleChoose(S,ban):choose(S,ban))",1)
# 250ms already present; enforce no 100ms aiTurn.
s=re.sub(r'setTimeout\(aiTurn,\s*100\)', 'setTimeout(aiTurn,250)', s)
# Notification FIFO queue, preserve durations.
s=s.replace("function note(t,msn=1200){clearTimeout(timer);$('#notice').textContent=t;$('#notice').classList.add('show');timer=setTimeout(()=>$('#notice').classList.remove('show'),msn)}", "let noticeQueue=[],noticeBusy=false,lastQueuedNotice='';function note(t,msn=1200){if(t===lastQueuedNotice)return;lastQueuedNotice=t;noticeQueue.push([t,msn]);if(noticeQueue.length>8)noticeQueue=noticeQueue.slice(-8);if(noticeBusy)return;const run=()=>{const item=noticeQueue.shift();if(!item){noticeBusy=false;lastQueuedNotice='';return}noticeBusy=true;$('#notice').textContent=item[0];$('#notice').classList.add('show');timer=setTimeout(()=>{$('#notice').classList.remove('show');setTimeout(run,40)},item[1])};run()}",1)
# Rules dialog content replaced after DOM load, and developer-only simple unlock based on existing developer body class.
addon="""<script id="mobileV35CommonUpgrade">(()=>{const RULES=`<h2>Second Best かんたんルール</h2><p><strong>相手の最善手を阻止できる戦略ゲーム</strong><br>初めて遊ぶ場合は、EASYかNORMALがおすすめです。</p><h3>1. 手番の流れ</h3><ul><li>白と黒に分かれ、それぞれコマを8個ずつ持ちます。</li><li>交互にコマを置き、手持ちのコマがなくなったら、動かせるコマを左右または対角のマスへ移動します。</li><li>1ターンに一度だけ、相手の提案した手に「セカンドベスト！」を宣言できます。</li><li>宣言された場合、最初に提案した手とは別の手を打たなければなりません。</li></ul><h3>2. コマと積層</h3><ul><li>1つのマスには最大3個までコマを積めます。</li><li>x2・x3は、そのマスに積まれたコマの数です。</li><li>上にあるコマが移動するまで、下のコマは動かせません。</li></ul><h3>3. 勝利</h3><ul><li>4つの連続したマスの一番上が、すべて自分のコマになる。</li><li>1つのマスに自分のコマが3個重なる。</li><li>相手がコマを移動できなくなる。</li><li>セカンドベストによって移動できなくなった側も原則として負けです。</li></ul><h3>4. 主な画面表示</h3><ul><li>紫色: AIが配置または移動したコマ</li><li>赤色: 配置または移動を予定しているコマ</li><li>金色: 合法手として選べる場所</li></ul>`;function init(){const d=document.getElementById('rulesDialog');if(d){const close=d.querySelector('#closeRules');d.innerHTML=`<div class="scroll">${RULES}</div><div class="endActions"></div>`;d.querySelector('.endActions').appendChild(close)}const opt=document.getElementById('developerOptions');if(opt&&!document.getElementById('unlockSimpleAi')){const l=document.createElement('label');l.id='simpleUnlockRow';l.innerHTML='<input id="unlockSimpleAi" type="checkbox"> 簡易AIを解放する';opt.appendChild(l);const c=l.querySelector('input'),o=document.getElementById('simpleOption');c.checked=localStorage.getItem('sb_simple_unlocked')==='1';const sync=()=>{o.hidden=!c.checked;if(!c.checked&&document.getElementById('mode').value==='simple')document.getElementById('mode').value='solved'};c.onchange=()=>{localStorage.setItem('sb_simple_unlocked',c.checked?'1':'0');sync()};sync()}document.getElementById('mode')?.addEventListener('change',e=>{document.getElementById('difficultyPanel').style.display=e.target.value==='solved'?'':'none'})}document.readyState==='loading'?document.addEventListener('DOMContentLoaded',init):init()})();</script>"""
s=s.replace('</body>',addon+'</body>',1)
# Responsive rules readability.
s=s.replace('</head>',"<style id='mobileV35RulesStyles'>#rulesDialog .scroll{max-height:68dvh;overflow:auto;line-height:1.65}#rulesDialog h2{font-size:24px}#rulesDialog h3{font-size:18px;margin:20px 0 8px}#rulesDialog li{margin:8px 0}</style></head>",1)
p.write_text(s,'utf-8')
# Metadata
for q in list(Path('.').glob('*preview_16*')): q.unlink()
manifest={'productVersion':'35.0.0-preview.18','uiVersion':'32.0.0-preview.18','difficultyPolicyVersion':'3.1.0-preview.1','immediateBase':'34.5.0-preview.16','analysisDataFile':'second_best_solved_table_v1.gz','simpleAi':{'mode':'simple','aiId':'simple-search','decisionEngineId':'simple-search-v1','nodeLimit':120000,'cacheLimit':60000},'aiDelayMs':250,'analysisPreparation':'idle-worker-with-fallback','saveSchemaChanged':False}
Path('release_manifest_v35_0_0_preview_18_mobile_ui.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n','utf-8')
Path('RELEASE_NOTES_v35_0_0_preview_18_mobile_ui.md').write_text('# SB.br-mobile v35.0.0-preview.18\n\n直前のv34.5.0-preview.16へ、引き継ぎ資料の共通テキスト、Worker解析準備、Difficulty Policy v3.1.0-preview.1、探索型簡易AI、通知キュー、250ms AI待機を差分適用。スマホ固有UIと盤面操作を継承。\n','utf-8')
# Validation
s=p.read_text('utf-8');data=Path('second_best_solved_table_v1.gz').read_bytes();raw=gzip.decompress(data)
soup=BeautifulSoup(s,'html.parser');ids=[x['id'] for x in soup.find_all(id=True)];dup={k:v for k,v in Counter(ids).items() if v>1};assert not dup
checks={'versions':all(x in s for x in ["35.0.0-preview.18","32.0.0-preview.18","3.1.0-preview.1"]),'worker':'new Worker(url)' in s,'singlePromise':'window.builtinSolvedPromise' in s,'policyEasy':'analysis:0.95' in s and 'random:0.05' in s,'policyNormal':'correctVetoSkipProbability(level){return level===\'EASY\'?0.75:level===\'NORMAL\'?0.45' in s,'simpleAI':all(x in s for x in ['function simpleSearch','function simpleChoose',"mode==='simple'"]),'limits':'limit:120000' in s and 'ctx.cache.size<60000' in s,'ai250':'setTimeout(aiTurn,250)' in s and 'setTimeout(aiTurn,100)' not in s,'notificationQueue':'noticeQueue' in s,'rules':'相手の最善手を阻止できる戦略ゲーム' in s,'dataName':'second_best_solved_table_v1.gz' in s,'gzipValid':len(raw)>50000000,'resultsRetained':Path('second_best_results_v1.json').exists(),'noDuplicateIds':not dup}
assert all(checks.values()),checks
syntax=[]
for i,m in enumerate(re.finditer(r'<script(?:\s+id="([^"]+)")?([^>]*)>(.*?)</script>',s,re.S|re.I)):
 if 'application/octet-stream' in m.group(2) or 'text/plain' in m.group(2):continue
 f=Path(f'/tmp/v35m_{i}.js');f.write_text(m.group(3),'utf-8');r=subprocess.run(['node','--check',str(f)],capture_output=True,text=True);assert r.returncode==0,(m.group(1),r.stderr);syntax.append(m.group(1) or str(i))
val={'result':'PASS','checks':checks,'gzipSha256':hashlib.sha256(data).hexdigest(),'rawSha256':hashlib.sha256(raw).hexdigest(),'rawBytes':len(raw),'scriptSyntaxPass':len(syntax)}
Path('STATIC_VALIDATION_RESULTS_v35_0_0_preview_18_mobile_ui.json').write_text(json.dumps(val,ensure_ascii=False,indent=2)+'\n','utf-8')
entries=[]
for q in sorted(Path('.').iterdir()):
 if q.is_file() and not q.name.startswith('SHA256SUMS'):entries.append(f'{hashlib.sha256(q.read_bytes()).hexdigest()}  {q.name}')
Path('SHA256SUMS_v35_0_0_preview_18_mobile_ui.txt').write_text('\n'.join(entries)+'\n','utf-8')
out=Path('/mnt/data/SB.br-mobile_v35_0_0_preview_18.zip')
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
 for q in sorted(Path('.').iterdir()):
  if q.is_file():z.write(q,q.name)
with zipfile.ZipFile(out) as z:assert z.testzip() is None
print(json.dumps({'file':out.name,'size':out.stat().st_size,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'checks':checks,'validation':val},ensure_ascii=False,indent=2))
