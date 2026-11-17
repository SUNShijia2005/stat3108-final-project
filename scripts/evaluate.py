"""Run offline component regression tests and a small labeled retrieval comparison."""
import json
from datetime import datetime,timezone
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from parcel.knowledge import retrieve

QUESTIONS=[
 ('体积重如何计算？','weight'),('How is dimensional weight calculated?','weight'),
 ('美国邮编如何分区？','us-zone'),('Which zone applies to California ZIP codes?','us-zone'),
 ('广东和福建适用这个报价吗？','rate-scope'),('What account eligibility applies to these rates?','rate-scope'),
 ('燃油附加费百分比是多少？','fuel'),('Does residential delivery add to ODA charges?','remote'),
 ('偏远地区费和住宅费是否重复？','remote'),('超过尺寸上限怎么办？','nonstandard'),
 ('美国入境处理费是多少？','inbound'),('What fields belong on a commercial invoice?','invoice'),
 ('货品只写 gifts 可以吗？','description'),('How do packing list quantities match the invoice?','packing'),
 ('官方模拟运单有哪些物流节点？','tracking'),('Can an arrival deadline be guaranteed?','transit'),
 ('电池物品可以寄吗？','dangerous'),('Are dangerous goods or liquids accepted?','dangerous')]

class RecordedResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.records=[]
    def addSuccess(self,test):super().addSuccess(test);self.records.append({'id':test.id(),'category':test.__class__.__name__,'passed':True})
    def addFailure(self,test,error):super().addFailure(test,error);self.records.append({'id':test.id(),'category':test.__class__.__name__,'passed':False,'reason':self._exc_info_to_string(error,test)})
    def addError(self,test,error):super().addError(test,error);self.records.append({'id':test.id(),'category':test.__class__.__name__,'passed':False,'reason':self._exc_info_to_string(error,test)})

def main():
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py')
    result=unittest.TextTestRunner(verbosity=1,resultclass=RecordedResult).run(suite)
    categories={}
    for row in result.records:
        c=categories.setdefault(row['category'],{'passed':0,'total':0});c['total']+=1;c['passed']+=row['passed']
    retrieval={'count':len(QUESTIONS),'methods':{},'note':'Small fixed developer-authored query set, not an independent held-out benchmark; no LLM evaluation.'}
    for method in ['keyword','bm25','hybrid']:
        rows=[]
        for query,gold in QUESTIONS:
            ids=[d['id'] for d in retrieve(query,method)]
            rows.append({'query':query,'expected':gold,'returned':ids,'top1':bool(ids and ids[0]==gold),'top3':gold in ids})
        retrieval['methods'][method]={'top1':sum(r['top1'] for r in rows),'top3':sum(r['top3'] for r in rows),'cases':rows}
    output={'status':'passed' if result.wasSuccessful() else 'failed','generated_at':datetime.now(timezone.utc).isoformat(),
            'scope':'Offline component and HTTP tests. Optional model transport is mocked; no live LLM, real shipment or end-user study.',
            'total':result.testsRun,'passed':sum(r['passed'] for r in result.records),'categories':categories,'cases':result.records,'retrieval':retrieval}
    (ROOT/'results').mkdir(exist_ok=True)
    (ROOT/'results/evaluation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    for method,stats in retrieval['methods'].items():print(f"{method}: top1 {stats['top1']}/{len(QUESTIONS)}, top3 {stats['top3']}/{len(QUESTIONS)}")
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':sys.exit(main())
