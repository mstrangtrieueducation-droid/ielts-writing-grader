"""Saved Gemini prose uses the established lesson review, without regrading."""
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]

def test_saved_review_anchors_revision_refresh_and_identity():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page()
        page.route('https://review.test/**',lambda r:r.fulfill(body='<html><body><section id="results"></section></body></html>',content_type='text/html'))
        page.goto('https://review.test/')
        bootstrap=re.search(r'<script>(.*?)</script>',(ROOT/'index.html').read_text(encoding='utf8'),re.S)[1]
        page.add_script_tag(content=bootstrap)
        for asset in ['review-ui/assignments.js','review-ui/writing-assignments.js','parent-bridge.js','review-ui/writing-feedback.js']:
            page.add_script_tag(content=(ROOT/asset).read_text(encoding='utf8'))
        page.evaluate("""()=>{
            Object.assign(parentState,{authorized:true,locked:false,name:'Test Student',revision:'test'});
            ieltsParentAccess.className='IELTS 48';state.student={name:'Test Student'};state.dashboard={};
            window.payload={class_name:'IELTS 48',student_name:'Test Student',student_id:'synthetic',task_code:'IELTS-WRITING-W14',graded_at:'2026-10-12T00:00:00Z'};
            window.essay={exercise:1,word_count:8,status:'Cần sửa',original:'Wrong phrase. <img src=x onerror="window.injected=true">',summary_vi:'Saved summary',taught_application_vi:'Saved theory',
                corrections:[{section:'Body',original:'Wrong phrase.',error:'Saved explanation.',suggested:'Correct phrase.'}],
                upgraded_paragraphs:[[{text:'Correct phrase.',color:'green'}],[{text:'Second paragraph.',color:'plain'}]],
                collocations:[{phrase:'Saved phrase',meaning_vi:'Saved meaning',usage_example:'Saved example.'}]};
            window.record=ieltsHybridReviews_.reviewRecord(payload,essay);
            document.querySelector('#results').innerHTML=ieltsWritingReviews_.savedResultCard(record);
        }""")
        page.locator('[data-wr-open]').click()
        assert page.locator('#wr-note-0 h5').inner_text()=='Lỗi 1 · Body'
        assert page.evaluate("ieltsHybridReviews_.sectionLabel('Detail 2')")=='Detail 2'
        assert page.evaluate("ieltsHybridReviews_.sectionLabel('Unit 11')")==''
        assert page.evaluate("ieltsHybridReviews_.sectionLabel('Overview')")=='Overview'
        assert page.locator('#wr-original .wr-essay').text_content()==page.evaluate('essay.original')
        assert page.locator('#wr-original img').count()==0
        page.locator('[data-wr-notes]').click()
        assert page.locator('#wr-note-0').get_attribute('class').endswith('is-selected')
        assert 'Saved explanation.' in page.locator('#wr-note-0').inner_text()
        page.locator('[data-wr-tab=revision]').click()
        assert page.locator('#wr-revision .wr-essay > p').all_text_contents()==['Correct phrase.','Second paragraph.']
        assert page.locator('.wr-revision-change').count()>0
        page.evaluate("window.originalPane=document.querySelector('#wr-revision .wr-essay');ieltsWritingReviews_.savedResultCard(ieltsHybridReviews_.reviewRecord(payload,essay))")
        page.evaluate('async()=>{await ieltsWritingReviews_.refresh(true)}')
        assert page.evaluate('originalPane===document.querySelector("#wr-revision .wr-essay")')
        assert page.locator('[data-wr-review-label]').inner_text()=='Đã trả bài'
        assert page.locator('[data-wr-tab=revision]').get_attribute('aria-selected')=='true'
        assert not page.evaluate('Boolean(window.injected)')
        assert page.evaluate("ieltsWritingReviews_.savedResultCard({...record,studentName:'Another student'})")==''
        page.locator('[data-wr-close]').click()
        page.evaluate("essay.corrections[0].section='Unit 11';payload.graded_at='2026-10-12T00:01:00Z';document.querySelector('#results').innerHTML=ieltsWritingReviews_.savedResultCard(ieltsHybridReviews_.reviewRecord(payload,essay))")
        page.locator('[data-wr-open]').click()
        assert page.locator('#wr-note-0 h5').inner_text()=='Lỗi 1'
        page.evaluate('ieltsParentLock_()')
        assert page.locator('dialog').count()==0
        assert page.evaluate('ieltsWritingReviews_.savedResultCard(record)')==''
        browser.close()
