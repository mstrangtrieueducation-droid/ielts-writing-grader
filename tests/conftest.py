import json
from types import SimpleNamespace
import pymupdf as fitz
import pytest
from src.schemas import Binding, NotebookResult, EssayResult
from src.parsers import word_count

@pytest.fixture
def binding():
    return Binding(task_code='W29',class_name='IELTS 45',assignment_type='homework',lesson=29,
        ready=True,source_verified=True,version='v1',source_reference='verified-source-audit',
        source_file_ids=['reference_file_123'],notebook_requirements=[{'id':'notes','text':'Handwritten model and assigned translation'}],
        notebook_copy_scope='Copy only assigned teacher notes/model/translation. Exclude new homework questions/charts, blank answer sheets and tool instructions.',
        essays=[{'exercise':1,'task':2,'question':'Discuss the benefits and risks of online communication.',
            'taught_theory':'Explain the causal chain and each assigned argument using taught foundations.',
            'assigned_outline':'Risk with mitigation; business communication benefits.', 'ground_truth':'No chart.'}],
        form_spreadsheet_id='form123',form_tab='W29',class_column=None,notebook_columns=['C'],essay_columns={1:'D'},
        tracker_header_exact='Writing W29',roster_end_row=7,next_writing_date='2026-10-10',
        next_writing_evidence='dashboard-snapshot-sha256-verified',due_at='2026-10-08T23:59:59+07:00')

@pytest.fixture
def settings(tmp_path):
    return SimpleNamespace(master_key=b'a'*32,output_dir=tmp_path/'dashboard_data',
        dashboard_base_url='https://example.test/ielts',class_sheets={'IELTS 45':'tracker123'},
        max_jobs=12,incoming_folder='incoming',processed_folder='processed',state_folder='state',
        notebook_model='flash',essay_model='pro')

def pdf():
    doc=fitz.open(); doc.new_page(); data=doc.tobytes(); doc.close(); return data

def notebook(status='complete'):
    page={'file_id':'notebook_file_123','page':1,'readable':True,'description':'Readable full notebook page'}
    return NotebookResult(items=[{'id':'notes','status':status,'explanation_vi':'Thiếu phần bản dịch được giao.' if status!='complete' else 'Đã chép đủ bài mẫu và bản dịch.', 'pages':[page] if status=='complete' else []}],page_audit=[page],summary_vi='Vở đã chép đủ bài mẫu và bản dịch được giao.')

def essay(original, spec):
    upgraded=[[{'text':' '.join(['learning']*70)+'.','color':'plain'}] for _ in range(4)]
    return EssayResult(exercise=spec.exercise,status='Cần sửa',original=original,word_count=word_count(original),
        paragraph_count=len(original.split('\n\n')),summary_vi='Em cần sửa câu chủ đề để bao quát đầy đủ lập luận của đoạn.',
        taught_application_vi='Em đã triển khai chuỗi giải thích theo dàn ý được giao.',corrections=[],
        upgraded_paragraphs=upgraded,collocations=[{'phrase':f'phrase {i}','type':'cụm ĐT','meaning_vi':'ý nghĩa','usage_example':'An example.'} for i in range(4)])

class FakeDrive:
    def __init__(self): self.state={}; self.downloaded=[]; self.moved=[]
    def folder_files(self, folder):
        return [{'id':k,'name':k,'mimeType':'application/json'} for k in self.state] if folder=='state' else []
    def download(self, fid):
        self.downloaded.append(fid)
        return (json.dumps(self.state[fid]).encode(),'application/json') if fid in self.state else (pdf(),'application/pdf')
    def write_json(self, folder, name, data): self.state[name]=json.loads(json.dumps(data)); return name
    def move_processed(self, *args): self.moved.append(args)

class FakeSheets:
    def __init__(self, rows): self.rows=rows; self.blocks=[]; self.fail_once=False
    def roster(self,*_): return [{'id':'S1','name':'Nguyễn Test','row':7}]
    def values(self,*_): return self.rows
    def has_prior_grading(self,*_): return False
    def write_feedback(self,spreadsheet,binding,student,block):
        if self.fail_once: self.fail_once=False; raise RuntimeError('Transient sheet failure')
        self.blocks.append(block); return {'cell':'AI7','exact_readback':True}

class FakeDashboard:
    def __init__(self): self.payloads=[]
    def publish(self,payload): self.payloads.append(payload); return {'live_payload_exact':True,'live_ui_verified':True}
