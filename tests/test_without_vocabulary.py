import json
from types import SimpleNamespace as N
import pytest
from src.graders.essay_batch import grade_essay_batch
from src.pro_batch_essays import jsonl, response_schema, NO_VOCABULARY_MARKER
from src.schemas import AuditedBundledEssayFeedback, AuditedEssayWithoutVocabulary
from test_per_essay_batch import responses, settings

def test_new_requests_omit_table_and_frozen_results_replay_without_changing_feedback(binding,monkeypatch):
    from src import lesson_packages
    monkeypatch.setattr(lesson_packages,'resolve_package',lambda _: {'id':'TEST','version':'no-vocab','vocabulary_table':False})
    specs,texts,returned=responses(binding)
    raw={k:v.model_dump() for k,v in returned.items()}
    for v in raw.values():v['collocations']=[]
    states=[]
    def submit(requests):
        assert all(response_schema(r) is AuditedEssayWithoutVocabulary for r in requests)
        rows=[json.loads(s) for s in jsonl([{**r,'key':str(i)} for i,r in enumerate(requests)],'system').splitlines()]
        assert all(r['request']['generationConfig']['responseJsonSchema']['properties']['collocations']['maxItems']==0 for r in rows)
        return raw
    result=grade_essay_batch(N(structured_essay_batch=submit),settings(),specs,texts,states.append)
    assert all(e.collocations==[] for e in result)
    assert all(e.original==texts[str(e.exercise)] for e in result)
    replay=grade_essay_batch(None,settings(),specs,texts,states.append,states[-1])
    assert [r.model_dump() for r in result]==[r.model_dump() for r in replay]
    assert response_schema({'prompt':'historical frozen request'}) is AuditedBundledEssayFeedback
    with pytest.raises(ValueError):AuditedBundledEssayFeedback.model_validate(raw['1'])
    with pytest.raises(ValueError):AuditedEssayWithoutVocabulary.model_validate(returned['1'].model_dump())
