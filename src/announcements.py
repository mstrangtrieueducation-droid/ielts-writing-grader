from datetime import datetime, timezone
from .policy import cutoff
from .parsers import digest

def draft(binding, roster, store):
    boundary=cutoff(binding)
    if boundary and datetime.now(timezone.utc)<boundary:
        return None
    states=[store.jobs.get(store.identity(binding,student)) for student in roster]
    if any(not state or state['phase']!='complete' or not state.get('tracker_evidence',{}).get('exact_readback')
        or not state.get('dashboard_evidence',{}).get('live_ui_verified') for state in states):
        return None
    payloads=[s['payload'] for s in states]
    graded=[p for p in payloads if p['state']=='graded']
    essay_count=sum(len(p['essays']) for p in graded)
    title=f"📝 **{binding.class_name} – NHẬN XÉT {'BÀI KIỂM TRA' if binding.assignment_type=='assessment' else 'BÀI TẬP VỀ NHÀ'} BUỔI {binding.lesson}**"
    lines=[title,'',f'Cô đã trả nhận xét cho **{len(graded)}/{len(roster)} em**, gồm **{essay_count} bài viết**.']
    for status,heading in [('too_late','⏰ NỘP QUÁ MUỘN – KHÔNG ĐƯỢC CHẤM CHỮA CHI TIẾT'),
            ('notebook_failed','⛔ VỞ CHƯA ĐẠT'),('pending','🕒 ĐÃ NỘP – ĐANG CHỜ XÁC MINH'),('missing','📝 CHƯA GHI NHẬN BÀI NỘP')]:
        group=[p for p in payloads if p['state']==status]
        if not group: continue
        lines+=['',f'**{heading} ({len(group)} em)**']
        for item in group:
            detail=item['received_display'] if status=='too_late' else item['warning'] if status in ('notebook_failed','pending') else ''
            lines.append(f"• **{item['student_name']}**"+(f': {detail}' if detail else '.'))
    lines+=['','**Nhận xét bài đã chữa:**']
    for item in graded:
        notes=' '.join(f"Đề {e['exercise']}: {e['status']}. {e['summary_vi']}" for e in item['essays']) or item['warning']
        lines.append(f"• **{item['student_name']}:** {notes}")
    lines+=['','**Cô yêu cầu các em đọc từng chú thích và sửa bài nghiêm túc.** Áp dụng đúng lý thuyết đã học; ghi lại lỗi và cách sửa để tránh lặp lại khi thi thật. Phụ huynh và các em mở **dashboard riêng** để xem nhận xét.']
    return '\n'.join(lines)

def save_draft(binding,roster,store):
    message=draft(binding,roster,store)
    if not message: return False
    name='announcement-'+digest(binding.class_name+'|'+binding.task_code)+'.json'
    store.drive.write_json(store.folder,name,{'class_name':binding.class_name,'task_code':binding.task_code,
        'message_markdown':message,'verified_students':len(roster),'never_auto_send':True})
    return True
