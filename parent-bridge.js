/* IELTS_HYBRID_PARENT_BRIDGE_V1: only authenticated private tracker pointers. */
const ieltsHybridReviews_ = (() => {
  'use strict';
  const ORIGIN='https://mstrangtrieueducation-droid.github.io';
  const cache=new Map(); let epoch=0;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const inline=v=>esc(v).replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>');
  const prose=v=>'<p class="hy-prose">'+inline(v)+'</p>';
  const normal=v=>String(v||'').normalize('NFC').trim().replace(/\s+/g,' ').toLocaleUpperCase('vi');
  function identity(){return parentState.authorized&&!parentState.locked&&parentState.name?[ieltsParentAccess.className,parentState.revision,normal(parentState.name)].join('|'):'';}
  function clear(){epoch++;cache.clear();document.querySelectorAll('[data-hybrid-result]').forEach(n=>n.replaceChildren());}
  const b64=v=>Uint8Array.from(atob(v.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-v.length%4)%4)),c=>c.charCodeAt(0));
  function pointer(text){
    // The legacy feedback typography inserts spaces after full stops, including
    // domain/path dots. Normalize only for parsing the allowlisted pointer;
    // never rewrite saved feedback or display prose.
    text=text.replace(/\.\s+/g,'.');
    const found=[...text.matchAll(/https:\/\/mstrangtrieueducation-droid\.github\.io\/ielts-writing-grader\/index\.html#[A-Za-z0-9_=&%-]+/g)];
    if(found.length!==1)return null;
    const url=new URL(found[0][0]),p=new URLSearchParams(url.hash.slice(1));
    if([...p.keys()].sort().join(',')!=='a,k,p,s'||!/^IELTS-WRITING-W\d{2,3}$/.test(p.get('a'))||!/^\d+$/.test(p.get('s'))||! /^[a-f0-9]{64}$/.test(p.get('p'))||! /^[A-Za-z0-9_-]{43}$/.test(p.get('k')))return null;
    return {url:url.href,profile:p.get('p'),secret:p.get('k'),code:p.get('a'),student:p.get('s')};
  }
  function validate(data,ref){
    const p=data?.schema_version===1&&data.assignments?.[ref.code];
    if(!p||p.schema_version!==1||p.class_name!==ieltsParentAccess.className||normal(p.student_name)!==normal(parentState.name)||String(p.student_id)!==ref.student||p.task_code!==ref.code||!Array.isArray(p.essays)||!['graded','too_late','notebook_failed','pending','missing','notebook_pass'].includes(p.state))throw Error('Private result identity mismatch');
    if(p.state!=='graded'&&p.essays.length)throw Error('Suppressed result exposes essay details');
    const seen=new Set();
    for(const e of p.essays){if(!Number.isInteger(e.exercise)||seen.has(e.exercise)||typeof e.original!=='string'||!Array.isArray(e.corrections)||!Array.isArray(e.upgraded_paragraphs)||!Array.isArray(e.collocations))throw Error('Invalid essay');seen.add(e.exercise);}
    return p;
  }
  function essayHtml(e){
    return '<details class="hy-essay" data-hybrid-essay="'+e.exercise+'"><summary>Đề '+e.exercise+' · '+esc(e.status)+' · Xem bài chữa</summary><div class="hy-essay-body">'+
      '<h4>Nhận xét bài viết</h4>'+prose(e.summary_vi)+prose(e.taught_application_vi)+
      '<h4>Bài em đã nộp · '+esc(e.word_count)+' từ</h4>'+prose(e.original)+
      '<h4>Chữa từng lỗi</h4>'+e.corrections.map(c=>'<blockquote><strong>'+inline(c.section)+'</strong>'+prose(c.original)+prose(c.error)+prose('Sửa: '+c.suggested)+'</blockquote>').join('')+
      '<h4>Bài viết tham khảo sau khi sửa</h4>'+e.upgraded_paragraphs.map(p=>'<p class="hy-prose">'+p.map(s=>'<span class="hy-'+(['yellow','blue','green'].includes(s.color)?s.color:'plain')+'">'+esc(s.text)+'</span>').join('')+'</p>').join('')+
      '<h4>Cụm từ cần ghi nhớ</h4>'+e.collocations.map(c=>prose(c.phrase+' ('+c.type+'): '+c.meaning_vi+'\n'+c.usage_example)).join('')+'</div></details>';
  }
  function resultHtml(p){
    const header='<header class="hy-head"><h3>Nhận xét bài tập về nhà</h3><p>Buổi '+esc(p.lesson)+(p.state==='graded'?' · Đã trả '+p.essays.length+' bài chữa':'')+'</p></header>';
    const links=(p.notebook_links||[]).filter(u=>/^https:\/\/drive\.google\.com\/file\/d\/[A-Za-z0-9_-]+\/view$/.test(u)).map((u,i)=>'<a class="wr-button secondary" href="'+esc(u)+'" target="_blank" rel="noopener noreferrer">Mở vở đã nộp'+(i?' '+(i+1):'')+'</a>').join(' ');
    if(p.state!=='graded')return header+'<div class="hy-content" role="status">'+prose(p.warning)+prose(p.received_display?'Thời gian nhận: '+p.received_display:'')+links+'</div>';
    return header+'<div class="hy-content"><section class="hy-notebook"><strong>VỞ ĐÃ ĐẠT YÊU CẦU</strong><details><summary>Xem nhận xét và vở đã nộp</summary>'+prose(p.warning)+links+'</details></section>'+p.essays.map(essayHtml).join('')+'</div>';
  }
  function mount(key){
    const entry=cache.get(key);if(!entry||entry.identity!==identity())return;
    document.querySelectorAll('[data-hybrid-result]').forEach(node=>{
      if(node.dataset.hybridResult!==key)return;
      const version=entry.payload?'ready':entry.error?'error':'loading';
      if(node.dataset.hybridState===version)return;
      node.dataset.hybridState=version;
      node.innerHTML=entry.payload?resultHtml(entry.payload):'<p role="status">'+(entry.error?'Chưa tải được bài chữa. Em có thể mở đường dẫn bên dưới hoặc tải lại trang.':'Đang mở bài chữa của em…')+'</p>';
      if(entry.error){const a=document.createElement('a');a.textContent='Mở bài chữa chi tiết';a.href=entry.ref.url;a.target='_blank';a.rel='noopener noreferrer';node.append(a);}
    });
  }
  function load(ref){
    const key=ref.profile+'|'+ref.code,id=identity();
    let entry=cache.get(key);
    if(entry&&entry.identity===id&&Date.now()-entry.created<180000){setTimeout(()=>mount(key),0);return key;}
    const started=epoch;entry={identity:id,ref,created:Date.now()};cache.set(key,entry);
    (async()=>{
      const response=await fetch(ORIGIN+'/ielts-writing-grader/dashboard_data/'+ref.profile+'.json',{cache:'no-store',credentials:'omit',referrerPolicy:'no-referrer'});
      if(!response.ok)throw Error('Unavailable');const envelope=await response.json();
      const k=await crypto.subtle.importKey('raw',b64(ref.secret),'AES-GCM',false,['decrypt']);
      const bytes=await crypto.subtle.decrypt({name:'AES-GCM',iv:b64(envelope.nonce),additionalData:new TextEncoder().encode(ref.profile)},k,b64(envelope.ciphertext));
      if(started!==epoch||identity()!==id)return;
      entry.payload=validate(JSON.parse(new TextDecoder().decode(bytes)),ref);
    })().catch(()=>{entry.error=true;}).finally(()=>{if(started===epoch&&identity()===id)mount(key);});
    return key;
  }
  function fragment(item,legacyHtml,blocked=false){
    if(item?.skill!=='writing'||!identity()||blocked)return null;
    const template=document.createElement('template');template.innerHTML=legacyHtml||'';
    const text=template.content.textContent;
    if(!text.includes('【KẾT QUẢ CHẤM ')||!text.includes('【HẾT KẾT QUẢ CHẤM】'))return null;
    const ref=pointer(text);if(!ref)return null;
    const assignment=ieltsWritingAssignments_.forItem(item);
    if(!assignment||assignment.assignmentCode!==ref.code)return null;
    template.content.querySelectorAll('.ielts-feedback-message').forEach(node=>{
      const outside=node.textContent.replace(/【KẾT QUẢ CHẤM [\s\S]*?【HẾT KẾT QUẢ CHẤM】/g,'').trim();
      if(outside)node.textContent=outside;else node.remove();
    });
    template.content.querySelectorAll('p > strong').forEach(node=>{if(node.textContent.trim().replace(/:$/,'')==='Nhận xét bài tập về nhà')node.textContent='Tình trạng nộp bài:';});
    const key=load(ref);
    return template.innerHTML+'<section class="hy-result" data-hybrid-result="'+esc(key)+'" aria-label="Nhận xét bài tập về nhà"><p role="status">Đang mở bài chữa của em…</p></section>';
  }
  window.addEventListener('hashchange',clear);window.addEventListener('pagehide',clear);
  return {fragment,clear};
})();
