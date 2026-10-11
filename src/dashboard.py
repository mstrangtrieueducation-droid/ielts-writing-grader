import base64
import hashlib
import hmac
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .policy import check_suppression
from .retry import retry

def b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip('=')

def unb64(value):
    return base64.urlsafe_b64decode(value+'='*(-len(value)%4))

class Dashboard:
    def __init__(self, settings):
        self.settings = settings

    def identity(self, classroom, student_id):
        identity = f'{classroom}\0{student_id}'.encode()
        profile = hmac.new(self.settings.master_key, b'profile\0'+identity,hashlib.sha256).hexdigest()
        key = hmac.new(self.settings.master_key,b'encryption\0'+identity,hashlib.sha256).digest()
        return profile, key

    def link(self, classroom, student_id):
        profile, key = self.identity(classroom,student_id)
        return f'{self.settings.dashboard_base_url}/index.html#p={profile}&k={b64(key)}'

    def stage(self, payload):
        check_suppression(payload)
        profile, key = self.identity(payload['class_name'],payload['student_id'])
        target = self.settings.output_dir/f'{profile}.json'
        data = {'schema_version':1,'assignments':{}}
        if target.exists():
            old = json.loads(target.read_text())
            decoded = AESGCM(key).decrypt(unb64(old['nonce']),unb64(old['ciphertext']),profile.encode())
            data = json.loads(decoded)
        data['assignments'][payload['task_code']] = payload
        nonce = os.urandom(12)
        encrypted = AESGCM(key).encrypt(nonce,json.dumps(data,ensure_ascii=False,sort_keys=True).encode(),profile.encode())
        envelope = {'schema_version':1,'nonce':b64(nonce),'ciphertext':b64(encrypted)}
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(envelope,sort_keys=True),encoding='utf-8')
        return profile,target

    def publish(self, payload):
        profile,target = self.stage(payload)
        # Fail before tracker mutation unless running in the authenticated dedicated checkout.
        if os.getenv('GITHUB_ACTIONS') != 'true':
            raise RuntimeError('Live publishing requires the dedicated GitHub Actions workflow')
        def git(*args):
            return subprocess.run(['git',*args],capture_output=True,text=True,check=True).stdout
        git('config','user.name','github-actions[bot]')
        git('config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
        git('add','--',str(self.settings.output_dir),'index.html','dashboard.js')
        if git('diff','--cached','--name-only').strip():
            git('commit','-m','Publish encrypted IELTS results [skip ci]')
            git('push','origin',f"HEAD:{os.environ['GRADING_DEFAULT_BRANCH']}")
        # GITHUB_TOKEN pushes do not trigger Pages; explicitly request a build, also on retries.
        self.request_pages_build()
        expected = target.read_bytes()
        url = f'{self.settings.dashboard_base_url}/dashboard_data/{profile}.json'
        last_error = None
        for attempt in range(18):
            try:
                request=urllib.request.Request(url+f'?v={hashlib.sha256(expected).hexdigest()}',
                    headers={'Cache-Control':'no-cache'})
                with urllib.request.urlopen(request,timeout=20) as response:
                    if response.read() == expected:
                        self.verify_ui(payload)
                        return {'profile':profile,'live_payload_exact':True,'live_ui_verified':True}
            except (OSError,ValueError) as exc:
                last_error=type(exc).__name__
            time.sleep(10)
        raise RuntimeError(f'Live dashboard not yet verified ({last_error or "stale deployment"}); resume delivery next run')

    def request_pages_build(self):
        repository=os.environ.get('GITHUB_REPOSITORY','')
        token=os.environ.get('GITHUB_TOKEN','')
        if not token or repository.count('/')!=1:
            raise ValueError('GitHub Pages publishing requires repository identity and scoped workflow token')
        request=urllib.request.Request(f'https://api.github.com/repos/{repository}/pages/builds',
            method='POST',data=b'',headers={'Authorization':'Bearer '+token,
                'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
        def submit():
            with urllib.request.urlopen(request,timeout=30) as response:
                if response.status!=201:
                    raise RuntimeError('Pages build request was not accepted')
        retry(submit)

    def verify_parent_ui(self, payload, parent_url):
        """The existing classroom portal is part of delivery, not just the new site."""
        import re
        from playwright.sync_api import sync_playwright
        if not re.fullmatch(r'https://mstrangtrieueducation-droid\.github\.io/[a-z0-9]{8}/#p=[A-Za-z0-9_-]{22}',parent_url):
            raise ValueError('Invalid parent dashboard link')
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            try:
                page=browser.new_page()
                page.goto(parent_url,wait_until='domcontentloaded',timeout=60000)
                page.wait_for_function("typeof parentState!=='undefined'&&parentState.authorized&&typeof state!=='undefined'&&state.student&&state.dashboard",timeout=60000)
                actual=page.evaluate('({name:parentState.name,className:ieltsParentAccess.className})')
                from .parsers import normalize_name
                if actual['className']!=payload['class_name'] or normalize_name(actual['name'])!=normalize_name(payload['student_name']):
                    raise ValueError('Parent dashboard identity mismatch')
                gate=page.locator('#ielts-pending-work-gate')
                if gate.is_visible():gate.get_by_role('button').first.click()
                page.get_by_role('button',name='Writing · Viết',exact=True).click()
                target=page.locator(f'[data-hybrid-result$="|{payload["task_code"]}"][data-hybrid-state="ready"]')
                if payload['state'] in {'too_late','notebook_failed'}:
                    gate=page.locator(f'.wr-assignment[data-wr-assignment="{payload["task_code"]}"]')
                    if gate.count() and gate.is_visible():
                        if gate.locator('[data-wr-open],[data-wr-task],[data-hybrid-essay]').count():raise ValueError('Parent gate exposes essay details')
                        expected_warning='NỘP QUÁ MUỘN' if payload['state']=='too_late' else 'KHÔNG ĐƯỢC CHẤM'
                        if expected_warning not in gate.inner_text():raise ValueError('Parent warning absent')
                        return {'live_parent_ui_verified':True,'identity_verified':True,'essays_verified':0,'suppression_verified':True}
                # Prepared profile refresh runs independently after the sheet write.
                # Wait for its real projection; never substitute an injected preview.
                target.wait_for(state='visible',timeout=180000)
                expected=len(payload['essays']) if payload['state']=='graded' else 0
                if target.locator('[data-hybrid-essay]').count()!=expected:raise ValueError('Parent essay count differs')
                if '【KẾT QUẢ CHẤM' in target.inner_text():raise ValueError('Internal tracker markers exposed')
                for essay in payload['essays'] if payload['state']=='graded' else []:
                    detail=target.locator(f'[data-hybrid-essay="{essay["exercise"]}"]')
                    detail.locator('summary').click()
                    if essay['original'] not in detail.inner_text():raise ValueError('Parent original essay differs')
                return {'live_parent_ui_verified':True,'identity_verified':True,'essays_verified':expected}
            finally:browser.close()

    def verify_ui(self, payload):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page()
            page.goto(self.link(payload['class_name'],payload['student_id']),wait_until='networkidle',timeout=60000)
            page.wait_for_selector('[data-ready="true"]',timeout=20000)
            card=page.locator(f'article[data-task-code="{payload["task_code"]}"]')
            if card.count()!=1:
                raise RuntimeError('Actual dashboard assignment card absent or ambiguous')
            if card.locator('[data-essay]').count()!=len(payload.get('essays',[])):
                raise RuntimeError('Actual dashboard essay count/suppression mismatch')
            if payload['state']!='graded' and card.locator('[data-essay]').count():
                raise RuntimeError('Actual dashboard exposes locked essay details')
            if payload['warning'] and payload['warning'] not in card.inner_text():
                raise RuntimeError('Actual dashboard warning missing')
            if card.locator('a').count()!=len(payload.get('notebook_links',[])):
                raise RuntimeError('Actual dashboard notebook links missing')
            browser.close()
