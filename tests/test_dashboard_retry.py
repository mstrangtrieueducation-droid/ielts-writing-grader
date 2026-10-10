import json
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from src.dashboard import Dashboard, unb64
from src.retry import retry

def test_encrypted_dashboard_no_public_names(settings):
    dashboard=Dashboard(settings)
    payload={'class_name':'IELTS 45','student_id':'S1','student_name':'Nguyễn Test','task_code':'W29','state':'too_late','essays':[]}
    profile,target=dashboard.stage(payload)
    assert 'Nguyễn Test' not in target.read_text() and 'IELTS 45' not in target.read_text()
    envelope=json.loads(target.read_text()); _,key=dashboard.identity('IELTS 45','S1')
    data=json.loads(AESGCM(key).decrypt(unb64(envelope['nonce']),unb64(envelope['ciphertext']),profile.encode()))
    assert data['assignments']['W29']==payload
    dashboard.stage({**payload,'task_code':'W30'})
    envelope=json.loads(target.read_text())
    data=json.loads(AESGCM(key).decrypt(unb64(envelope['nonce']),unb64(envelope['ciphertext']),profile.encode()))
    assert set(data['assignments'])=={'W29','W30'}
    _,wrong=dashboard.identity('IELTS 45','S2')
    with pytest.raises(Exception): AESGCM(wrong).decrypt(unb64(envelope['nonce']),unb64(envelope['ciphertext']),profile.encode())

def test_transient_retries_and_permanent_no_retry():
    calls=[]; delays=[]
    def operation():
        calls.append(1)
        if len(calls)<3: raise TimeoutError()
        return 'ok'
    assert retry(operation,sleeper=delays.append)=='ok' and len(delays)==2
    calls.clear()
    def permanent(): calls.append(1); raise ValueError('invalid config')
    with pytest.raises(ValueError): retry(permanent,sleeper=delays.append)
    assert len(calls)==1
