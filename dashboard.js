'use strict';
(() => {
  const el = (tag, text, cls) => { const node = document.createElement(tag); if (text != null) node.textContent = text; if (cls) node.className = cls; return node; };
  const b64 = value => Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4-value.length%4)%4)), x => x.charCodeAt(0));
  function render(data) {
    if (data.schema_version !== 1 || !data.assignments) throw new Error('Invalid schema');
    const root = document.getElementById('results');
    root.replaceChildren();
    const identity=Object.values(data.assignments)[0];
    if(!identity || Object.values(data.assignments).some(p=>p.student_id!==identity.student_id || p.class_name!==identity.class_name || p.student_name!==identity.student_name))throw Error('Mixed identity');
    Object.assign(parentState,{authorized:true,locked:false,name:identity.student_name,revision:'saved-profile'});
    ieltsParentAccess.className=identity.class_name;
    state.student={name:identity.student_name};state.dashboard={className:identity.class_name};
    for (const payload of Object.values(data.assignments)) {
      const card = el('article'); card.dataset.taskCode = payload.task_code;
      const title = {homework:'Nhận xét bài tập về nhà',assessment:'Nhận xét bài kiểm tra',notebook:'Nhận xét vở chép',vocabulary:'Nhận xét sổ từ vựng'}[payload.assignment_type] || 'Nhận xét bài tập';
      card.append(el('h2', title), el('p', `${payload.class_name} · ${payload.student_name} · Buổi ${payload.lesson}`));
      if (payload.received_display) card.append(el('p', `Thời gian nhận: ${payload.received_display}`));
      if (payload.received_display && payload.state !== 'too_late') card.append(el('p', payload.submitted_late ? 'Đã nộp muộn so với hạn bài tập' : 'Đã nộp'));
      if (payload.warning) card.append(el('p', payload.warning, 'warning'));
      for (const url of payload.notebook_links || []) {
        if (!/^https:\/\/drive\.google\.com\/file\/d\/[A-Za-z0-9_-]+\/view$/.test(url)) continue;
        const link = el('a', 'Mở vở đã nộp'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        card.append(link, el('br'));
      }
      // Suppression enforced independently in both producer and actual browser renderer.
      if (payload.state === 'graded') for (const essay of payload.essays || []) {
        const matching=ieltsWritingAssignments_.all().some(a=>a.assignmentCode===payload.task_code&&a.tasks.some(t=>t.taskNumber===essay.exercise));
        if(matching){
          const holder=el('div');holder.dataset.essay=String(essay.exercise);
          holder.innerHTML=ieltsWritingReviews_.savedResultCard(ieltsHybridReviews_.reviewRecord(payload,essay));
          card.append(holder);continue;
        }
        const details = el('details'); details.dataset.essay = String(essay.exercise);
        details.append(el('summary', `Đề ${essay.exercise} · ${essay.status} · ${essay.word_count} từ`));
        details.append(el('p', essay.summary_vi, 'prose'), el('p', essay.taught_application_vi, 'prose'));
        if (Object.keys(essay.band_scores || {}).length) details.append(el('p', Object.entries(essay.band_scores).map(([name, value]) => `${name}: ${value}`).join(' · ')));
        details.append(el('h3', 'Bài viết đã nộp'), el('p', essay.original, 'prose'), el('h3', 'Chữa từng lỗi'));
        for (const [index, correction] of essay.corrections.entries()) {
          const section=ieltsHybridReviews_.correctionLocation(payload,essay,correction);
          const block = el('blockquote'); block.append(el('strong', `Lỗi ${index+1}${section?' · '+section:''}`), el('p', correction.original, 'prose'), el('p', correction.error), el('p', `Sửa: ${correction.suggested}`, 'prose')); details.append(block);
        }
        details.append(el('h3', 'Bài viết tham khảo sau khi sửa'));
        for (const paragraph of essay.upgraded_paragraphs) {
          const p = el('p'); for (const span of paragraph) p.append(el('span', span.text, ['yellow','blue','green'].includes(span.color) ? span.color : '')); details.append(p);
        }
        if(essay.collocations.length) details.append(el('h3', 'Cụm từ cần ghi nhớ'));
        for (const entry of essay.collocations) details.append(el('p', `${entry.phrase} (${entry.type}): ${entry.meaning_vi}\n${entry.usage_example}`, 'prose'));
        card.append(details);
      }
      root.append(card);
    }
    root.dataset.ready = 'true';
  }
  async function start() {
    const params = new URLSearchParams(location.hash.slice(1)); const profile = params.get('p') || ''; const secret = params.get('k') || '';
    if (!/^[a-f0-9]{64}$/.test(profile) || !/^[A-Za-z0-9_-]{43}$/.test(secret)) throw new Error('Invalid private link');
    const response = await fetch(`dashboard_data/${profile}.json`, {cache:'no-store',credentials:'omit'});
    if (!response.ok) throw new Error('Result not available');
    const envelope = await response.json();
    const key = await crypto.subtle.importKey('raw', b64(secret), 'AES-GCM', false, ['decrypt']);
    const decoded = await crypto.subtle.decrypt({name:'AES-GCM',iv:b64(envelope.nonce),additionalData:new TextEncoder().encode(profile)}, key, b64(envelope.ciphertext));
    render(JSON.parse(new TextDecoder().decode(decoded)));
    document.getElementById('status').textContent = 'Nhận xét cá nhân';
  }
  start().catch(() => { const status = document.getElementById('status'); status.className = 'error'; status.textContent = 'Chưa mở được nhận xét. Vui lòng dùng đúng đường dẫn riêng hoặc thử lại sau.'; });
})();
