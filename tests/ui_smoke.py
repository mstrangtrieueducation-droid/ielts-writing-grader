"""Actual browser verification with synthetic students, never real credentials/media."""
import contextlib
import functools
import http.server
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from src.dashboard import Dashboard
from src.parsers import word_count
from src.schemas import EssayResult

def main():
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as folder:
        target=Path(folder)
        for name in ('index.html','dashboard.js','parent-bridge.js'): shutil.copy2(root/name,target/name)
        shutil.copytree(root/'review-ui',target/'review-ui')
        class SilentHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self,*args): pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(SilentHandler,directory=folder))
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        settings=SimpleNamespace(master_key=b't'*32,output_dir=target/'dashboard_data',dashboard_base_url=f'http://127.0.0.1:{server.server_port}')
        dashboard=Dashboard(settings)
        original=' '.join(['study']*65)+' <img src=x onerror="window.injected=true">'
        essay=EssayResult(exercise=1,status='Cần sửa',original=original,word_count=word_count(original),paragraph_count=1,
            summary_vi='Em cần sửa các lỗi được ghi rõ trong từng chú thích của bài viết.',
            taught_application_vi='Em cần áp dụng đủ các bước triển khai lý thuyết đã học.',
            corrections=[],upgraded_paragraphs=[[{'text':' '.join(['learning']*65),'color':color}] for color in ('yellow','blue','green','plain')],
            collocations=[{'phrase':f'phrase {n}','type':'cụm từ','meaning_vi':'nghĩa','usage_example':'Example.'} for n in range(4)])
        checks=[]
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True)
                for number,state in enumerate(['graded','notebook_failed','too_late','missing']):
                    payload={'schema_version':1,'student_id':f'fake-{number}','student_name':'Học sinh giả lập',
                        'class_name':'IELTS DEMO','task_code':'W29','lesson':29,'assignment_type':'homework',
                        'graded_at':'2026-10-10T00:00:00Z','received_display':'10/10/2026 00:00:00' if state=='too_late' else '',
                        'state':state,'warning':{'graded':'Vở đạt yêu cầu.','notebook_failed':'Vở thiếu bản dịch.',
                            'too_late':'NỘP QUÁ MUỘN — KHÔNG ĐƯỢC CHẤM CHỮA CHI TIẾT','missing':'Chưa ghi nhận bài nộp.'}[state],
                        'notebook_links':['https://drive.google.com/file/d/abcdefghijk/view'] if state=='too_late' else [],
                        'essays':[essay.model_dump(mode='json')] if state=='graded' else []}
                    dashboard.stage(payload)
                    page=browser.new_page(); page.goto(dashboard.link(payload['class_name'],payload['student_id']))
                    page.wait_for_selector('[data-ready="true"]')
                    assert page.locator('[data-essay]').count()==(1 if state=='graded' else 0)
                    assert payload['warning'] in page.inner_text('#results')
                    assert page.locator('#results a').count()==len(payload['notebook_links'])
                    assert page.get_by_role('heading',name='Nhận xét bài tập về nhà',exact=True).count()==1
                    assert payload['task_code'] not in page.inner_text('#results')
                    if state=='graded':
                        page.locator('summary').click()
                        assert page.locator('.yellow').count()==1 and page.locator('.blue').count()==1 and page.locator('.green').count()==1
                        assert page.locator('#results img').count()==0 and not page.evaluate('Boolean(window.injected)')
                    checks.append({'state':state,'actual_browser_verified':True})
                    page.close()
                # Wrong keys must never render anyone else's plaintext.
                page=browser.new_page(); page.goto(settings.dashboard_base_url+'/index.html#p='+'0'*64+'&k='+'A'*43)
                page.wait_for_selector('.error'); assert page.locator('[data-task-code]').count()==0
                checks.append({'state':'wrong-link','actual_browser_verified':True})
                browser.close()
        finally:
            server.shutdown(); server.server_close()
        print(json.dumps({'verified':True,'checks':checks}))

if __name__=='__main__': main()
