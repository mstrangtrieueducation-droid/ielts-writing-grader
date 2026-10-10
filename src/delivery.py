from .policy import TOO_LATE, check_suppression

def feedback_block(payload):
    state=payload['state']
    if state=='too_late':
        content=f"{TOO_LATE}\nThời gian nhận: {payload['received_display']}"
    elif state=='notebook_failed':
        content=payload['warning']+'\nKHÔNG ĐƯỢC CHẤM BÀI VIẾT.'
    elif state=='pending':
        content=payload['warning']
    elif state=='missing':
        content='Chưa ghi nhận bài nộp.'
    else:
        content=payload['warning']
        if payload['essays']:
            content+=f"\nĐã trả {len(payload['essays'])}/{len(payload['essays'])} bài chữa trên dashboard."
        for essay in payload['essays']:
            content+=f"\nĐề {essay['exercise']}: {essay['status']}\n{essay['summary_vi']}"
    if payload.get('received_display') and state!='too_late':
        content=('⚠️ ĐÃ NỘP MUỘN' if payload.get('submitted_late') else '✅ ĐÃ NỘP')+f"\nThời gian nhận: {payload['received_display']}\n"+content
    label={'vocabulary':'SỔ TỪ VỰNG','notebook':'VỞ CHÉP'}.get(payload['assignment_type'],'WRITING')
    return f'【KẾT QUẢ CHẤM {label}】\n{content}\n【HẾT KẾT QUẢ CHẤM】'

def deliver(state, binding, student, dashboard, sheets, store, spreadsheet, drive, settings):
    payload=state['payload']
    check_suppression(payload)
    if state['phase']=='complete':
        return
    # Publishing/checking is repeated on delivery retries, but cached model results are reused.
    state['dashboard_evidence']=dashboard.publish(payload)
    state['phase']='dashboard_verified'
    store.save(state)
    state['tracker_evidence']=sheets.write_feedback(spreadsheet,binding,student,feedback_block(payload))
    if binding.dashboard_link_column:
        from .parsers import sheet_range
        cell=sheet_range(binding.tracker_tab,f"{binding.dashboard_link_column}{student['row']}")
        link=dashboard.link(binding.class_name,student['id'])
        old=sheets.values(spreadsheet,cell,formula=True)
        existing=old[0][0] if old and old[0] else ''
        if existing and existing!=link:
            raise ValueError('Existing parent link is preserved; use a dedicated empty new-dashboard column')
        if existing!=link:
            sheets.set_cell(spreadsheet,cell,link)
    state['phase']='tracker_verified'
    store.save(state)
    if state['source'].get('scan_id'):
        drive.move_processed(state['source']['scan_id'],settings.incoming_folder,settings.processed_folder)
    state['phase']='complete'
    store.save(state)
