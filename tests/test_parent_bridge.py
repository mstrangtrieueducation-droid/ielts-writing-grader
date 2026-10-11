import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from src.delivery import feedback_block

SCRIPT=Path(__file__).resolve().parents[1]/'parent-bridge.js'

def test_parent_bridge_identity_render_and_suppression():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page()
        page.route('https://parent.test/**',lambda r:r.fulfill(body='<html><body></body></html>',content_type='text/html'))
        page.goto('https://parent.test/')
        page.add_script_tag(content="const parentState={authorized:true,locked:false,name:'Nguyễn Test',revision:1};const ieltsParentAccess={className:'IELTS 48'};const ieltsWritingAssignments_={forItem:()=>({assignmentCode:'IELTS-WRITING-W14'})};")
        page.add_script_tag(content=SCRIPT.read_text(encoding='utf8'))
        # Encrypt a real response in the browser, exercise fetch/decryption and DOM.
        result=page.evaluate("""async()=>{
          const secret=new Uint8Array(32), profile='a'.repeat(64), nonce=new Uint8Array(12);
          const base64=v=>btoa(String.fromCharCode(...new Uint8Array(v))).replace(/=/g,'').replace(/\\+/g,'-').replace(/\\//g,'_');
          const key=await crypto.subtle.importKey('raw',secret,'AES-GCM',false,['encrypt']);
          const payload={schema_version:1,class_name:'IELTS 48',student_name:'Nguyễn Test',student_id:'1',task_code:'IELTS-WRITING-W14',lesson:14,state:'graded',warning:'Vở đủ.',notebook_links:[],essays:[{exercise:1,status:'Cần sửa',word_count:150,original:'<script>bad()</script>',summary_vi:'Nhận xét riêng',taught_application_vi:'Lý thuyết.',corrections:[{section:'Body',original:'wrong',error:'Giải thích',suggested:'correct'}],upgraded_paragraphs:[[{text:'Corrected.',color:'yellow'}]],collocations:[]}]};
          window.testPayload=payload;
          window.fetch=async()=>{const bytes=await crypto.subtle.encrypt({name:'AES-GCM',iv:nonce,additionalData:new TextEncoder().encode(profile)},key,new TextEncoder().encode(JSON.stringify({schema_version:1,assignments:{[payload.task_code]:payload}})));return {ok:true,json:async()=>({nonce:base64(nonce),ciphertext:base64(bytes)})};};
          window.testLegacy='<div><p><strong>Nhận xét bài tập về nhà:</strong> Đã nộp</p><div class="ielts-feedback-message">Ghi chú tay\\n【KẾT QUẢ CHẤM WRITING】\\nChi tiết\\nhttps://mstrangtrieueducation-droid.github.io/ielts-writing-grader/index.html#p='+profile+'&amp;k='+base64(secret)+'&amp;a=IELTS-WRITING-W14&amp;s=1\\n【HẾT KẾT QUẢ CHẤM】</div></div>';
          document.body.innerHTML=ieltsHybridReviews_.fragment({skill:'writing'},testLegacy);
          return true;
        }""")
        page.wait_for_selector('[data-hybrid-state=ready]')
        assert page.locator('[data-hybrid-essay]').count()==1
        assert 'KẾT QUẢ CHẤM' not in page.locator('body').inner_text()
        assert 'Ghi chú tay' in page.locator('body').inner_text()
        page.locator('[data-hybrid-essay] summary').click()
        assert page.get_by_text('Giải thích',exact=True).is_visible()
        assert page.locator('body script').count()==0
        # Wrong identity fails closed even with a valid encrypted envelope/key.
        page.evaluate("ieltsHybridReviews_.clear(); testPayload.student_name='Other Student';document.body.innerHTML=ieltsHybridReviews_.fragment({skill:'writing'},testLegacy)")
        page.wait_for_selector('[data-hybrid-state=error]')
        assert page.locator('[data-hybrid-essay]').count()==0
        # Gated payload never renders historical details.
        page.evaluate("ieltsHybridReviews_.clear();testPayload.student_name='Nguyễn Test';testPayload.state='too_late';document.body.innerHTML=ieltsHybridReviews_.fragment({skill:'writing'},testLegacy)")
        page.wait_for_selector('[data-hybrid-state=error]')
        assert page.locator('[data-hybrid-essay]').count()==0
        page.evaluate("ieltsHybridReviews_.clear();testPayload.essays=[];document.body.innerHTML=ieltsHybridReviews_.fragment({skill:'writing'},testLegacy)")
        page.wait_for_selector('[data-hybrid-state=ready]')
        assert page.locator('[data-hybrid-essay]').count()==0
        assert page.evaluate("ieltsHybridReviews_.fragment({skill:'writing'},testLegacy,true)") is None
        page.evaluate("parentState.locked=true")
        assert page.evaluate("ieltsHybridReviews_.fragment({skill:'writing'},testLegacy)") is None
        browser.close()

def test_tracker_bridge_preserves_markers_and_scopes_private_link():
    p={'state':'graded','warning':'Vở đủ.','essays':[],'assignment_type':'homework','task_code':'IELTS-WRITING-W14','student_id':'25'}
    url='https://mstrangtrieueducation-droid.github.io/ielts-writing-grader/index.html#p='+('a'*64)+'&k='+('b'*43)
    text=feedback_block(p,url)
    assert text.endswith('【HẾT KẾT QUẢ CHẤM】') and '&a=IELTS-WRITING-W14&s=25' in text
    import pytest
    with pytest.raises(ValueError):feedback_block(p,'https://other.test/#p=a&k=b')
