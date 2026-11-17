'use strict';
/* 「Grok提示词」技能引擎（EVA skills/imagine_prompt）。
   读 stdin 一个 JSON 请求，调用与网页工具同一次构建生成的 core_bundle.js（同一套模式 / 选项 / 拼装 / 检查 / 参数规则），
   stdout 输出一个 JSON。不联网、不读写文件（只加载同目录的 core_bundle.js）、不执行请求里的任何代码。 */
const C=require('./core_bundle.js');
const {MODES,KB,STRUCT,ASPECTS,TC}=C;
const VERSION='ips-skill-1';
const trim=s=>String(s==null?'':s).trim();
const isObj=v=>!!v&&typeof v==='object'&&!Array.isArray(v);
const CJK=/[\u4e00-\u9fff]/;
const TXT=800;
const txt=v=>typeof v==='string'||typeof v==='number'?String(v).slice(0,TXT).trim():'';
let UO={};
function items(name){if(!name)return [];return ((KB.o&&KB.o[name])||KB[name]||[]).concat(UO[name]||[])}
function lab(it){return it?(it.zt||it.zh||''):''}
function enOf(it){if(!it)return '';return trim(it.en)||trim(it.ev)||''}
/* 值 → 选项 key：key / 中文名 / 英文 完全匹配（不做模糊猜测） */
function keyOf(name,v,form){const s=trim(isObj(v)?(v.k||v.key||v.v||''):v);if(!s)return null;const L=items(name).filter(it=>!it.only||!form||it.only.includes(form));
  const low=s.toLowerCase();const it=L.find(x=>x.k===s)||L.find(x=>trim(x.zh)===s||trim(x.zt)===s)||L.find(x=>enOf(x).toLowerCase()===low);return it?it.k:null}
const FORM_ALIAS={person:'person','人物':'person','人像':'person','数字人':'person',product:'product','产品':'product','商品':'product','物品':'product',other:'other','其他':'other','其它':'other','动物':'other','场景':'other','风景':'other',animal:'other',scene:'other'};
const BASE_ALIAS={t2i:'t2i','文生图':'t2i',i2i:'i2i','图生图':'i2i',i2v:'i2v','图生视频':'i2v',t2v:'t2v','文生视频':'t2v',ref:'ref','参考图生视频':'ref'};
/* mode：完整表单键（t2i_g…）或基本类型 + form + spicy */
function resolve(q,issues){let key=trim(q.mode);if(MODES[key]&&key!==C.baseOf(key)&&!q.form&&q.spicy===undefined)return key;
  const base=BASE_ALIAS[C.baseOf(key)]||BASE_ALIAS[key]||'t2i';if(!BASE_ALIAS[key]&&!MODES[key]&&key)issues.push(['warn','mode「'+key+'」无效，按文生图处理']);
  let form=FORM_ALIAS[trim(q.form)]||(MODES[key]&&MODES[key].form)||'person';if(base==='ref')form='';
  if(q.form&&!FORM_ALIAS[trim(q.form)])issues.push(['warn','form「'+trim(q.form)+'」无效，可选 person / product / other']);
  let sp=q.spicy===undefined?!!(MODES[key]&&MODES[key].spicy):!!q.spicy;
  if(sp&&!C.spicyAllowed(base,form)){issues.push(['warn','辣椒模式只适用于人物表单（文生图 / 图生图 / 图生视频 / 文生视频），已按普通模式处理']);sp=false}
  return base==='ref'?'ref':C.resolveKey(base,form,sp)}
/* 文本节点：中文为准（与网页一致，英文由中文派生）；对话模型给的 zh+en 记入本次译文表 */
function textNode(v,label,issues){let zh='',en='';if(typeof v==='string'||typeof v==='number'){const s=txt(v);if(CJK.test(s))zh=s;else en=s}else if(isObj(v)){zh=txt(v.zh);en=txt(v.en)}
  if(zh&&en&&CJK.test(zh))TC.set(zh,{en,src:'model'});
  if(!zh&&en){if(CJK.test(en)){zh=en}else{issues.push(['tip','「'+label+'」只给了英文，中文版该处也会显示英文']);zh=en}}
  return zh}
function arrOf(v){if(Array.isArray(v))return v;if(isObj(v)&&Array.isArray(v.v))return v.v;if(typeof v==='string')return v.split(/[,，、;；]/).map(trim).filter(Boolean);if(v==null||v==='')return [];return [v]}
function setChoice(f,node,v,form,issues,lbl){/* 单选 combo / action：选项 key 或自定义文本 */
  const L=f.list||f.opts;const k=isObj(v)&&v.v==='_custom'?null:keyOf(L,v,form);if(k){node.v=k;if(isObj(v)&&(v.zh||v.en))issues.push(['tip','「'+lbl+'」已选选项「'+lab(C.optItem(L,k))+'」，附带的文字未使用']);return}
  const vv=isObj(v)&&v.v!=='_custom'?trim(v.v||''):'';const z=textNode(isObj(v)?{zh:v.zh!==undefined&&v.zh!==''?v.zh:(CJK.test(vv)?vv:''),en:v.en!==undefined&&v.en!==''?v.en:(!CJK.test(vv)?vv:'')}:v,lbl,issues);
  if(z){node.v='_custom';node.zh=z;node.en=''}}
function setMany(list,node,v,max,form,issues,lbl){const ks=[],extra=[];for(const x of arrOf(v).slice(0,30)){const k=keyOf(list,x,form);if(k){if(!ks.includes(k))ks.push(k)}else{const z=textNode(x,lbl,issues);if(z)extra.push(z)}}
  if(max&&ks.length>max){issues.push(['warn','「'+lbl+'」最多选 '+max+' 项，已保留前 '+max+' 项']);ks.length=max}
  if(isObj(v)&&!Array.isArray(v)&&(v.zh||v.en)){const z=textNode({zh:v.zh,en:v.en},lbl,issues);if(z)extra.unshift(z)}
  node.v=ks;if(extra.length){node.zh=[trim(node.zh)].concat(extra).filter(Boolean).join('、');node.en='';issues.push(['tip','「'+lbl+'」中不在选项里的内容已作为补充说明：'+extra.join('、')])}}
function setStruct(f,node,v,form,issues){const D=STRUCT[f.struct];const lbl=f.label;if(typeof v==='string'){node.zh=textNode(v,lbl,issues);return}if(!isObj(v))return;
  const src=isObj(v.parts)?v.parts:v;const extra=[];const PID=new Set(D.parts.map(p=>p.id));
  for(const k of Object.keys(src)){if(['zh','en','extra','parts','note'].includes(k))continue;if(!PID.has(k)){issues.push(['warn','「'+lbl+'」没有子项「'+k+'」，已并入补充说明']);const z=textNode(src[k],lbl,issues);if(z)extra.push(z)}}
  for(const pt of D.parts){if(!(pt.id in src))continue;const val=src[pt.id];const pl='「'+lbl+' · '+pt.label+'」';
    if(pt.kind==='flag'){node.parts[pt.id]=val===true||val==='true'||val==='是';continue}
    const L=typeof pt.list==='function'?pt.list(node.parts):pt.list;
    if(pt.kind==='many'){const n={v:[],zh:''};setMany(L,n,val,pt.max,form,issues,lbl+' · '+pt.label);node.parts[pt.id]=n.v;if(n.zh)extra.push(n.zh)}
    else{const k=keyOf(L,val,form);if(k)node.parts[pt.id]=k;else{const z=textNode(val,lbl,issues);if(z){extra.push(z);issues.push(['tip',pl+'「'+z+'」不在选项中，已并入补充说明'])}}}}
  for(const pt of D.parts)if(pt.show&&node.parts[pt.id]!==undefined&&!pt.lock&&!pt.show(node.parts)){issues.push(['tip','「'+lbl+' · '+pt.label+'」对当前主体类型不适用，已忽略']);delete node.parts[pt.id]}
  const z=textNode({zh:v.zh!==undefined?v.zh:v.extra,en:v.en},lbl,issues);node.zh=[z].concat(extra).filter(Boolean).join('，');node.en=''}
const KEEPV={keep:'keep','保持':'keep','保留':'keep','不变':'keep',chg:'chg',change:'chg','修改':'chg','改':'chg'};
function setAspects(f,d,v,issues,ch){if(!isObj(v))return;if(isObj(v.m)){const o={};for(const [k,x] of Object.entries(v.m))o[k]=x==='chg'&&isObj(ch)&&ch[k]?{change:ch[k]}:x;v=o}const AL=typeof f.aspects==='function'?f.aspects(d):f.aspects;
  for(const [k0,val] of Object.entries(v)){const a=ASPECTS.find(x=>x.k===k0||x.zh===k0||(C&&false))||ASPECTS.find(x=>x.zh.startsWith(trim(k0)));const k=a&&a.k;
    if(!k||!AL.includes(k)){issues.push(['warn','对照项「'+k0+'」不适用于当前表单；可用：'+AL.map(x=>x+'('+(ASPECTS.find(y=>y.k===x)||{}).zh+')').join('、')]);continue}
    if(typeof val==='string'&&KEEPV[trim(val)]){d.keep.m[k]=KEEPV[trim(val)];continue}
    const ch=isObj(val)?(val.change!==undefined?val.change:val):val;const z=textNode(ch,'修改'+a.zh,issues);if(z){d.keep.m[k]='chg';d.keepch[k]={zh:z,en:''}}}}
function setFrames(M,d,v,form,issues){if(!isObj(v))return;const AL=M.fields.find(x=>x.id==='action').list;
  if(v.seg1!==undefined){const n=+v.seg1;if(isFinite(n)&&n>0)d.seg1=n}
  if(Array.isArray(v.segs)){d.segs=v.segs.slice(0,2).map(s=>{const n={b:isObj(s)&&isFinite(+s.b)?+s.b:0,v:'',zh:'',en:''};setChoice({list:AL},n,isObj(s)?(s.action!==undefined?s.action:(s.v!==undefined||s.zh!==undefined||s.en!==undefined?{v:s.v,zh:s.zh,en:s.en}:'')):s,form,issues,'时间轴动作');return n});if(v.segs.length>2)issues.push(['warn','时间轴最多 3 段（含第 1 段主要动作）'])}
  d.tl=v.tl!==undefined?!!v.tl:(d.segs||[]).length>0;
  if(Array.isArray(v.keys))d.keys=v.keys.slice(0,8).map(k=>({t:isObj(k)&&isFinite(+k.t)?+k.t:0,zh:textNode(isObj(k)?{zh:k.zh,en:k.en}:k,'关键帧',issues),en:'',img:''}));
  if(v.endf!==undefined){const e=v.endf;d.endf={on:isObj(e)&&'on' in e?!!e.on:(e!==false&&e!==null),zh:e===true||e===false||e===null?'':textNode(isObj(e)?{zh:e.zh,en:e.en}:e,'尾帧',issues),en:''}}}
let FX={};
function setField(M,f,d,v,form,issues){const lbl=f.label.replace(/（.*?）/g,'');const o=d[f.id];
  switch(f.type){
    case 'seg':case 'select':{const k=v===''||v===null?'':keyOf(f.opts,v,M.form||'person');if(k===null){issues.push(['warn','「'+lbl+'」没有选项「'+trim(isObj(v)?v.v:v)+'」，已忽略；可选：'+items(f.opts).filter(it=>!it.only||it.only.includes(M.form||'person')).map(it=>it.k+'='+lab(it)).join('、')]);return}o.v=k;return}
    case 'combo':if(f.kind==='many')setMany(f.list,o,v,f.max,M.form,issues,lbl);else setChoice(f,o,v,M.form,issues,lbl);return
    case 'checks':setMany(f.opts,o,v,f.max,M.form,issues,lbl);return
    case 'struct':setStruct(f,o,v,M.form,issues);return
    case 'toggle':d[f.id]=v===true||v==='true'||v==='是'||v===1;return
    case 'text2':o.zh=textNode(v,lbl,issues);o.en='';return
    case 'action':{setChoice(f,o,isObj(v)?(v.v!==undefined&&v.v!==''&&v.v!=='_custom'?v.v:{zh:v.zh,en:v.en}):v,M.form,issues,lbl);if(isObj(v)){const vp=Object.assign({},isObj(v.parts)?v.parts:{},v);for(const p of ['speed','dir'])if(vp[p]!==undefined&&vp[p]!==''){const k=keyOf(p,vp[p]);if(k)o.parts[p]=k;else issues.push(['warn','「'+lbl+'」的'+(p==='speed'?'速度':'方向')+'「'+trim(vp[p])+'」不在选项中，已忽略'])}}return}
    case 'sound':{const val=isObj(v)?v:{v};const k=keyOf('sound',val.v);if(!k){if(val.v)issues.push(['warn','声音类型「'+trim(val.v)+'」无效；可选：'+KB.sound.map(it=>it.k+'='+lab(it)).join('、')]);return}o.v=k;
      if(val.zh!==undefined||val.en!==undefined||val.text!==undefined){o.zh=textNode(val.text!==undefined?val.text:{zh:val.zh,en:val.en},'声音',issues);o.en=''}
      if(val.amb===undefined&&isObj(val.parts)&&val.parts.amb!==undefined)val.amb=val.parts.amb;if(val.amb!==undefined){const n={v:[]};setMany('amb',n,val.amb,3,'',issues,'环境音');o.parts.amb=n.v}
      if(k==='dlg'&&val.keep_zh_dialogue)d.keepZhDlg=true;return}
    case 'beats':{const a=arrOf(v).slice(0,f.max||3);if(arrOf(v).length>(f.max||3))issues.push(['warn','节拍最多 '+(f.max||3)+' 个']);d[f.id]=a.map(x=>{const n={v:'',zh:'',en:''};setChoice({list:'actions'},n,x,M.form,issues,'节拍');return n});if(!d[f.id].length)d[f.id]=[{v:'',en:'',zh:''}];return}
    case 'refs':{d.refs=arrOf(v).slice(0,15).map(x=>{const r=isObj(x)?x:{zh:x};const role=keyOf('refRoles',r.role)||'char';if(r.role&&!keyOf('refRoles',r.role))issues.push(['warn','参考图角色「'+trim(r.role)+'」无效，按人物处理']);return {role,zh:textNode({zh:r.zh,en:r.en},'参考图',issues),en:''}});return}
    case 'aspects':setAspects(f,d,v,issues,FX.keepch);return
    case 'frames':setFrames(M,d,v,M.form,issues);return
    case 'imgs':issues.push(['tip','技能不接收图片本身；需要识图请先用 action=analyze_image（工作区图片路径），再把识别结果填入字段']);return
  }}
const PDEF={model:'v15',dur:8,res:'480',ar:'16:9',iar:'1:1',i2iar:'src',i2var:'src'};
function params(mode,p,issues){const P=Object.assign({},PDEF);if(isObj(p)){const h=C.histParams(mode,p);Object.assign(P,h);for(const k of Object.keys(p))if(!(k in h)&&p[k]!==undefined&&p[k]!==''&&['model','dur','res','ar','iar','i2iar','i2var'].includes(k))issues.push(['warn','参数 '+k+'='+JSON.stringify(p[k])+' 无效或不适用于当前模式，已忽略（比例键：文生图 iar / 图生图 i2iar / 图生视频 i2var / 文生视频与参考图 ar）'])}
  const ch=C.normalizeParamsP(mode,P);ch.forEach(x=>issues.push(['tip','已按限制调整：'+x]));return P}
function srcIm(q){const s=q.source_size;if(isObj(s)&&+s.w>0&&+s.h>0)return {w:+s.w,h:+s.h};const r=trim(q.source_ratio);const m=/^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/.exec(r);return m?{w:+m[1],h:+m[2]}:null}
function setup(q){UO=isObj(q.user_opts)?q.user_opts:{};C.setUser(UO);C.setOptEnHook(z=>C.enFor(z).text);C.tcSeed();
  if(isObj(q.translations))for(const [z,e] of Object.entries(q.translations).slice(0,200))if(CJK.test(z)&&typeof e==='string'&&trim(e))TC.set(trim(z).slice(0,TXT),{en:trim(e).slice(0,TXT),src:'model'});
  if(isObj(q.pupd)&&!q.use_builtin_params)C.setPupd(q.pupd)}
function capInfo(){const p=C.getPupd();return {source:p&&p.updated&&Object.keys(p.fields||{}).length?'updated':'builtin',updated:p&&p.updated||0,fields:Object.keys((p&&p.fields)||{}).length}}
function finish(mode,d,P,q,issues,extra){const vis={minor:!!(q.vis&&q.vis.minor),real:!!(q.vis&&q.vis.real)};
  const o={vis};if(typeof q.prompt_en==='string')o.ov=q.prompt_en.slice(0,6000);if(typeof q.prompt_zh==='string')o.zov=q.prompt_zh.slice(0,6000);
  const R=C.runPipeline(mode,d,P,o);const M=MODES[mode];const A=C.arInfoP(mode,P,srcIm(q));
  return Object.assign({ok:!R.blocked,engine:'shared',engine_version:VERSION,build:C.IPS_BUILD,mode,base:C.baseOf(mode),form:M.form||'',spicy:!!M.spicy,mode_title:M.name+(M.fname?' · '+M.fname:''),
    prompt_en:R.blocked?'':R.out.en,prompt_zh:R.blocked?'':R.out.zh,blocked:R.blocked,
    lint:R.lint.map(x=>({level:x.level,title:x.title,msg:x.msg||'',fix:x.fix||''})),
    params:P,settings:C.genSettingsP(mode,P,d,A),param_notes:C.paramNotes(mode,R.dd,P).map(([t,c])=>({text:t,warn:c==='w'})),
    translation:{missing:R.info.missing,pending:R.info.pending,from_model:[...TC.entries()].filter(([,v])=>v.src==='model').slice(0,100).map(([z,v])=>[z,v.en])},caps:capInfo(),
    input_issues:issues.map(([level,msg])=>({level,msg})),data:q.return_data?d:undefined},extra||{})}
function opBuild(q){const issues=[];const mode=resolve(q,issues);const M=MODES[mode];const P=params(mode,q.params,issues);let d=C.defaults(mode);C.migrateData(mode,d);
  const F=Object.assign({},isObj(q.fields)?q.fields:{});FX={keepch:F.keepch};delete F.keepch;delete F.keepd;
  const fr=M.fields.find(f=>f.type==='frames');if(fr){const ex={};for(const k of ['tl','seg1','segs','keys','endf'])if(k in F){ex[k]=F[k];delete F[k]}if(Object.keys(ex).length)F[fr.id]=Object.assign({},isObj(F[fr.id])?F[fr.id]:{},ex)}
  const ids=new Set(M.fields.map(f=>f.id));
  for(const k of Object.keys(F))if(!ids.has(k))issues.push(['warn','当前表单「'+M.name+(M.fname?'·'+M.fname:'')+'」没有字段「'+k+'」，已忽略；可用字段：'+M.fields.filter(f=>f.type!=='imgs').map(f=>f.id).join('、')]);
  const order=M.fields.filter(f=>f.type!=='aspects').concat(M.fields.filter(f=>f.type==='aspects'));
  for(const f of order)if(f.id in F)setField(M,f,d,F[f.id],M.form,issues);
  d=C.migrateData(mode,d);return finish(mode,d,P,q,issues)}
function opLint(q){const issues=[];const mode=resolve(q,issues);const P=params(mode,q.params,issues);const d=C.migrateData(mode,C.defaults(mode));
  if(typeof q.prompt_en!=='string'||!trim(q.prompt_en))return {ok:false,error:'lint 需要 prompt（英文提示词）'};return finish(mode,d,P,q,issues,{checked:'text'})}
function opRestore(q){const issues=[];const x=C.histClean(q.entry);if(!x)return {ok:false,error:'历史记录格式无效（需要网页「导出历史」文件中的一条：含 id / mode / en，可选 data / params）'};
  let key=x.mode,r=null;if(x.data){r=C.migrateEntryP(x.mode,x.data);key=r.mode;if(r.conv)C.regLeftP(r.conv)}
  const notes=[];const d=r?r.data:C.migrateData(key,C.defaults(key));if(r&&r.mode!==x.mode)notes.push('旧版记录已迁移到新表单'+(r.moved.length?'；不兼容内容已并入补充说明：'+r.moved.join('、'):''));if(!r)notes.push('这条记录只有文本，无法还原表单字段：按保存时的中英文检查');
  if(Array.isArray(d.keys))d.keys.forEach(k=>{if(k&&k.img)k.img=''});
  const P=Object.assign({},PDEF,C.histParams(key,x.params));C.normalizeParamsP(key,P);
  if(['i2i','i2v','ref'].includes(C.baseOf(key)))notes.push('历史记录不保存图片：生成时请使用原图');
  const q2=Object.assign({},q);if(!r||x.enEdited)q2.prompt_en=x.en;if(x.zh&&(!r||x.zhEdited))q2.prompt_zh=x.zh;
  let out=finish(key,d,P,q2,issues);
  if(r&&!(x.enEdited)&&out.prompt_en!==x.en&&!out.blocked){q2.prompt_en=x.en;if(x.zh)q2.prompt_zh=x.zh;out=finish(key,d,P,q2,issues);notes.push('按当前规则生成的文本与保存时不同（词表/翻译更新），已按保存时的文本检查')}
  out.restored={id:x.id,title:x.title,time:x.time,notes};return out}
function opt(it){const e=enOf(it);return e?[it.k,lab(it),e]:[it.k,lab(it)]}
function opDescribe(q){const issues=[];const mode=resolve(q,issues);const M=MODES[mode];const form=M.form||'person';const only=q.field?String(q.field):'';
  const L=n=>items(n).filter(it=>!it.only||it.only.includes(form)).slice(0,120).map(opt);
  const fields=M.fields.filter(f=>f.type!=='imgs'&&(!only||f.id===only)).map(f=>{const r={id:f.id,type:f.type,label:f.label};if(f.req)r.required=true;if(f.max)r.max=f.max;if(f.hint)r.hint=f.hint;
    if(f.type==='seg'||f.type==='select')r.options=L(f.opts);else if(f.type==='combo'||f.type==='action')r.options=L(f.list);else if(f.type==='checks')r.options=L(f.opts);
    if(f.type==='combo')r.kind=f.kind;
    if(f.type==='struct')r.parts=STRUCT[f.struct].parts.map(p=>{const o={id:p.id,label:p.label,kind:p.kind||'one'};if(p.max)o.max=p.max;if(p.lock)o.locked=true;
      if(typeof p.list==='function'){const dep=STRUCT[f.struct].parts.find(x=>x.id==='target');o.depends_on='target';o.options_by={};for(const t of dep?items(dep.list):[])o.options_by[t.k]=L(p.list({target:t.k}))}else if(p.list)o.options=L(p.list);return o});
    if(f.type==='action')r.extra={speed:L('speed'),dir:L('dir'),custom:'{zh,en} 自定义动作'};
    if(f.type==='sound')r.options=KB.sound.map(opt),r.extra={amb:L('amb'),text:'amb/nodlg 补充说明；dlg 对白（短句）'};
    if(f.type==='beats')r.options=L('actions');if(f.type==='refs')r.options=L('refRoles');
    if(f.type==='aspects'){const d=C.defaults(mode);const AL=typeof f.aspects==='function'?f.aspects(d):f.aspects;r.aspects=AL.map(k=>{const a=ASPECTS.find(x=>x.k===k);return [k,a.zh]});r.values="'keep' 保持 / {change:'改成什么'} 修改"}
    if(f.type==='frames')r.shape="{seg1:第1段结束秒数, segs:[{b:结束秒数, action:选项key或自定义文本}], keys:[{t:秒, zh, en}], endf:{zh,en}|true}";
    return r});
  const A=C.arInfoP(mode,Object.assign({},PDEF),null);
  return {ok:true,engine:'shared',engine_version:VERSION,build:C.IPS_BUILD,mode,base:C.baseOf(mode),form:M.form||'',spicy:!!M.spicy,mode_title:M.name+(M.fname?' · '+M.fname:''),intro:M.intro||'',
    fields,params:{video:!!M.video,defaults:PDEF,ratio_key:A.key,ratios:A.list,models:M.video?KB.models.map(m=>[m.k,m.name]):undefined},caps:capInfo(),
    forms:{t2i:['person','product','other'],t2v:['person','product','other'],i2i:['person','product','other'],i2v:['person','product','other'],ref:[]},input_issues:issues.map(([level,msg])=>({level,msg}))}}
function opVisLists(q){const issues=[];const mode=resolve(q,issues);return {ok:true,mode,spicy:!!MODES[mode].spicy,lists:C.visListsP(mode,C.baseOf(mode))}}
function handle(q){if(!isObj(q))return {ok:false,error:'请求必须是 JSON 对象'};setup(q);
  switch(q.op){case 'build':return opBuild(q);case 'lint':return opLint(q);case 'restore':return opRestore(q);case 'describe':return opDescribe(q);case 'vis_lists':return opVisLists(q);
    default:return {ok:false,error:'未知 op'}}}
let buf='';process.stdin.setEncoding('utf8');process.stdin.on('data',c=>{buf+=c;if(buf.length>2e6){process.stdout.write(JSON.stringify({ok:false,error:'请求过大'}));process.exit(0)}});
process.stdin.on('end',()=>{let q;try{q=JSON.parse(buf||'{}')}catch(_){process.stdout.write(JSON.stringify({ok:false,error:'请求不是有效 JSON'}));return}
  let out;try{out=handle(q)}catch(e){out={ok:false,error:'引擎内部错误：'+String(e&&e.message||e).slice(0,200)}}process.stdout.write(JSON.stringify(out))});
