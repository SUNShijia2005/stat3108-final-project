"""Offline regression cases. Golden price anchors were checked against retained PDFs."""
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

import app
from parcel.domain import quote,clean_fields,document_check,document_html,ValidationError,RATES
from parcel.assistant import chat,update
from parcel.storage import Store
from parcel.tracking import track,summarize
from parcel.knowledge import retrieve,DOCS
from parcel import model


def shipment(**changes):
    return dict(origin_province='Shanghai',destination_country='US',destination_zip='90001',destination_state='CA',goods='Cotton T-shirts',weight_kg=10,length_cm=30,width_cm=20,height_cm=10,**changes) if not changes else {**shipment(),**changes}


def documents(**changes):
    return {**shipment(), 'sender_name':'Demo Sender','sender_address':'Example only','sender_phone':'000000',
            'recipient_name':'Demo Recipient','recipient_address':'Example only','recipient_phone':'000000',
            'currency':'USD','country_of_origin':'CN','invoice_total':50,'invoice_number':'TEST-001','ship_date':'2026-11-17',
            'items':[{'description':'Cotton T-shirt','quantity':2,'packing_quantity':2,'unit_price':25}],**changes}


def option(q,service='IP'):
    return next(o for o in q['options'] if o['service']==service)


class RateTests(unittest.TestCase):
    def test_01_source_price_anchors(self):
        q=quote(shipment())
        self.assertEqual({o['service']:o['base_charge'] for o in q['options']},{'IPE':4132,'IP':3931,'IE':3860})
    def test_02_east_zone_anchor(self):
        q=quote(shipment(destination_state='NY',destination_zip='10001'))
        self.assertEqual(q['zone'],'2');self.assertEqual(option(q)['base_charge'],3956)
    def test_03_half_kg_ordinary_packaging(self):
        q=quote(shipment(weight_kg=.4,length_cm=10,width_cm=10,height_cm=10))
        self.assertEqual(q['billable_kg'],.5);self.assertEqual(option(q)['base_charge'],536)
    def test_04_weight_rounded_up(self):
        q=quote(shipment(weight_kg=10.01));self.assertEqual(q['billable_kg'],10.5);self.assertEqual(option(q)['base_charge'],4069)
    def test_05_dimensional_weight(self):
        q=quote(shipment(length_cm=50,width_cm=40,height_cm=30));self.assertEqual(q['volumetric_kg'],12);self.assertEqual(q['billable_kg'],12)
    def test_06_weight_range_handoff(self):
        self.assertEqual(quote(shipment(weight_kg=20.51))['status'],'needs_review')
    def test_07_oversize_handoff(self):
        self.assertEqual(quote(shipment(length_cm=122))['status'],'needs_review')
    def test_08_girth_handoff(self):
        self.assertEqual(quote(shipment(length_cm=100,width_cm=60,height_cm=30))['status'],'needs_review')
    def test_09_origin_eligibility(self):
        for origin in ['Guangdong','福建','Shenzhen','New York']:
            with self.subTest(origin=origin):self.assertEqual(quote(shipment(origin_province=origin))['status'],'needs_review')
    def test_10_other_destination(self):
        self.assertEqual(quote(shipment(destination_country='CA'))['status'],'needs_review')
    def test_11_missing_dimensions(self):
        q=quote(shipment(height_cm=None));self.assertEqual(q['status'],'needs_input');self.assertIn('height_cm',q['missing'])
    def test_12_zip_validation(self):
        for zip_code in ['00000','abc','9000']:
            with self.subTest(zip_code=zip_code),self.assertRaises(ValidationError):quote(shipment(destination_zip=zip_code))
    def test_13_state_zip_conflict(self):
        with self.assertRaises(ValidationError):quote(shipment(destination_state='NY'))
    def test_14_zip4(self):
        self.assertEqual(quote(shipment(destination_zip='90001-1234'))['zone'],'1')
    def test_15_non_finite_or_negative(self):
        for value in ['NaN','Infinity',-2,True]:
            with self.subTest(value=value),self.assertRaises(ValidationError):quote(shipment(weight_kg=value))
    def test_16_inbound_fee(self):
        self.assertEqual(option(quote(shipment()))['known_subtotal'],3950.30)
    def test_17_residential_fee(self):
        self.assertEqual(option(quote(shipment(oda_tier='none',residential=True)))['known_subtotal'],3974.30)
    def test_18_remote_excludes_residential(self):
        q=quote(shipment(oda_tier='B',residential=True));self.assertEqual(option(q)['known_subtotal'],4121.30)
        self.assertFalse(any('住宅' in c['label'] for c in option(q)['components']))
    def test_19_explicit_fuel_scenario(self):
        q=quote(shipment(fuel_percent=10));self.assertEqual(option(q)['known_subtotal'],4343.40);self.assertFalse(q['fuel_verified'])
    def test_20_unknown_fuel_not_zero(self):
        self.assertIn('当期燃油附加费',quote(shipment())['pending'])
        self.assertNotIn('当期燃油附加费',quote(shipment(fuel_percent=0))['pending'])
    def test_21_budget_partial(self):
        self.assertEqual(option(quote(shipment(budget_cny=4000)))['budget_status'],'within_known_cost')
        self.assertEqual(option(quote(shipment(budget_cny=1000)))['budget_status'],'over')
    def test_22_deadline_not_invented(self):
        q=quote(shipment(deadline='2026-12-01'));self.assertTrue(any('2026-12-01' in p for p in q['pending']));self.assertFalse(option(q)['arrival_confirmed'])
    def test_23_restricted_goods(self):
        for goods in ['Lithium battery','液体']:
            with self.subTest(goods=goods):self.assertEqual(quote(shipment(goods=goods))['status'],'needs_review')
    def test_24_table_completeness(self):
        self.assertEqual(sum(len(s['rates'])*10 for s in RATES['services']),1230)
        for s in RATES['services']:self.assertEqual([r['weight_kg'] for r in s['rates']],[i/2 for i in range(1,42)])


class DocumentTests(unittest.TestCase):
    def test_01_valid_draft(self):
        q=document_check(documents());self.assertEqual(q['issues'],[]);self.assertEqual(q['calculated_total'],50)
    def test_02_missing_contacts(self):
        q=document_check(documents(recipient_phone=None));self.assertIn('missing_recipient_phone',[i['code'] for i in q['issues']])
    def test_03_quantity_mismatch(self):
        f=documents();f['items'][0]['packing_quantity']=1;self.assertIn('quantity_mismatch',[i['code'] for i in document_check(f)['issues']])
    def test_04_incorrect_total(self):
        self.assertIn('total_mismatch',[i['code'] for i in document_check(documents(invoice_total=99))['issues']])
    def test_05_decimal_arithmetic(self):
        q=document_check(documents(invoice_total=.3,items=[{'description':'Printed book','quantity':3,'packing_quantity':3,'unit_price':.1}]))
        self.assertEqual(q['calculated_total'],.3);self.assertEqual(q['issues'],[])
    def test_06_vague_description(self):
        q=document_check(documents(items=[{'description':'gifts','quantity':2,'packing_quantity':2,'unit_price':25}]))
        self.assertIn('vague_description',[i['code'] for i in q['issues']])
    def test_07_invalid_item(self):
        q=document_check(documents(items=[{'description':'Book','quantity':1.5,'packing_quantity':1,'unit_price':25}]))
        self.assertIn('invalid_item',[i['code'] for i in q['issues']])
    def test_08_html_escaped(self):
        text=document_html(documents(sender_name='<script>alert(1)</script>'))
        self.assertIn('&lt;script&gt;',text);self.assertNotIn('<script>alert',text)
    def test_09_packing_contains_package(self):
        text=document_html(documents(), 'packing');self.assertIn('Gross weight: 10',text);self.assertIn('PACKING LIST',text);self.assertNotIn('<th>Unit price</th>',text)
    def test_10_csv_preserves_other_document(self):
        f=documents();items=app.import_csv(f,'description,quantity\nCotton T-shirt,1\n','packing');f['items']=items
        self.assertEqual(items[0]['quantity'],2);self.assertIn('quantity_mismatch',[i['code'] for i in document_check(f)['issues']])
    def test_11_csv_rejects_bad_headers(self):
        with self.assertRaises(ValidationError):app.import_csv({},'name,count\nBook,1\n','invoice')


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'tasks.sqlite3');self.task=self.store.create()
        self.mock=patch('parcel.assistant.model.configured',return_value=False);self.mock.start()
    def tearDown(self):self.mock.stop();self.temp.cleanup()
    def test_01_multi_turn_update(self):
        update(self.task,shipment());chat(self.task,'估算运费');self.assertEqual(self.task['quote']['billable_kg'],10)
        chat(self.task,'把重量改成8kg');self.assertEqual(self.task['quote']['billable_kg'],8);self.assertEqual(self.task['fields']['destination_zip'],'90001')
        self.assertEqual(option(self.task['quote'])['base_charge'],3207)
    def test_02_persistence(self):
        update(self.task,documents());self.store.save(self.task)
        self.assertEqual(Store(self.store.path).get(self.task['id'])['fields'],self.task['fields'])
    def test_03_update_invalidates_old_results(self):
        update(self.task,shipment());self.task['quote']=quote(self.task['fields']);self.task['checks']={'status':'old'}
        update(self.task,{'weight_kg':8});self.assertIsNone(self.task['quote']);self.assertIsNone(self.task['checks'])
    def test_04_english_retrieval(self):
        answer=chat(self.task,'How is dimensional weight calculated?');self.assertIn('5000',answer['text']);self.assertIn('Volumetric',answer['text'])
    def test_05_offline_tracking(self):
        with patch('parcel.tracking.build_opener',side_effect=AssertionError('No network expected')):result=track()
        self.assertEqual(len(result['events']),4);self.assertEqual(result['data_type'],'official_synthetic_sample');self.assertEqual(result['status'],'delivered')
    def test_06_no_accidental_live_query(self):
        with patch('parcel.tracking.build_opener',side_effect=AssertionError('No network expected')),self.assertRaises(ValidationError):track('TEST12345')
    def test_07_trace_and_citations(self):
        result=chat(self.task,'体积重如何计算？');self.assertEqual(result['trace'][0]['tool'],'search_rules');self.assertTrue(result['citations'][0]['source_url'].startswith('https://'))
    def test_08_timestamps_sorted_in_utc(self):
        data={'data':{'trackings':[{'events':[{'status':'earlier','occurrenceDatetime':'2026-01-02T10:00:00+08:00'},{'status':'later','occurrenceDatetime':'2026-01-02T03:00:00Z'}]}]}}
        self.assertEqual(summarize(data,'test','test')['events'][0]['status'],'later')
    def test_09_document_edit_preserves_rate(self):
        update(self.task,shipment());self.task['quote']=quote(self.task['fields']);previous=self.task['quote']
        update(self.task,{'invoice_total':50})
        self.assertEqual(self.task['quote'],previous)


class ModelContractTests(unittest.TestCase):
    def test_00_baseline_and_retrieval_arms(self):
        requests=[]
        class Opener:
            def open(self,req,timeout):
                requests.append(json.loads(req.data))
                return io.BytesIO(json.dumps({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'Reference answer.'}]}]}).encode())
        with patch.dict(os.environ,{'LLM_API_KEY':'test-only','LLM_MODEL':'test-model','LLM_BASE_URL':'https://example.invalid/v1','LLM_API_STYLE':'responses'}),patch('parcel.model.build_opener',return_value=Opener()):
            for mode in ['baseline','rag']:
                model.respond('question',{'fields':{},'messages':[]},lambda *args:self.fail('No tools expected'),mode=mode,context=[{'id':'weight','text':'5000'}] if mode=='rag' else None)
        self.assertEqual(requests[0]['tools'],[]);self.assertEqual(requests[1]['tools'],[])
        self.assertFalse(any('Retrieved reference' in m['content'] for m in requests[0]['input']))
        self.assertTrue(any('Retrieved reference' in m['content'] for m in requests[1]['input']))
    def test_01_function_call_roundtrip(self):
        responses=[{'status':'completed','output':[{'type':'function_call','name':'estimate_rates','arguments':'{}','call_id':'call-test','id':'fc-test'}]}, {'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'Saved reference estimate.'}]}]}]
        requests=[];calls=[]
        class Opener:
            def open(self,req,timeout):requests.append(json.loads(req.data));return io.BytesIO(json.dumps(responses.pop(0)).encode())
        with patch.dict(os.environ,{'LLM_API_KEY':'test-only','LLM_MODEL':'test-model','LLM_BASE_URL':'https://example.invalid/v1','LLM_API_STYLE':'responses'}),patch('parcel.model.build_opener',return_value=Opener()):
            text=model.respond('estimate',{'fields':{},'messages':[]},lambda name,args:calls.append((name,args)) or {'status':'needs_input'})
        self.assertEqual(calls,[('estimate_rates',{})]);self.assertEqual(text,'Saved reference estimate.')
        self.assertEqual(requests[1]['input'][-1]['type'],'function_call_output');self.assertFalse(requests[0]['store'])
    def test_02_model_failure_uses_workflow(self):
        task={'fields':{},'messages':[],'quote':None,'checks':None,'tracking':None}
        with patch('parcel.assistant.model.configured',return_value=True),patch('parcel.assistant.model.respond',side_effect=RuntimeError('offline')):
            result=chat(task,'体积重如何计算？')
        self.assertEqual(result['mode'],'workflow');self.assertIn('5000',result['text']);self.assertEqual(result['model_error'],'offline')


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.previous=app.STORE;app.STORE=Store(Path(cls.temp.name)/'http.sqlite3')
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join();app.STORE=cls.previous;cls.temp.cleanup()
    def request(self,path,body=None,headers=None):
        req=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**(headers or {})})
        return urlopen(req,timeout=5)
    def test_01_health_and_assets(self):
        with self.request('/api/health') as r:self.assertEqual(json.load(r)['rate_count'],1230)
        for path in ['/','/app.js','/style.css']:
            with self.subTest(path=path),self.request(path) as r:self.assertEqual(r.status,200)
    def test_02_create_quote_restore(self):
        with self.request('/api/tasks',{}) as r:t=json.load(r)
        with self.request('/api/quote',{'id':t['id'],'version':0,'fields':shipment()}) as r:t=json.load(r)['task']
        self.assertEqual(t['version'],1);self.assertEqual(option(t['quote'])['known_subtotal'],3950.3)
        with self.request('/api/task?id='+t['id']) as r:self.assertEqual(json.load(r)['quote'],t['quote'])
    def test_03_conflict_preserves_saved_state(self):
        with self.request('/api/tasks',{}) as r:t=json.load(r)
        with self.assertRaises(HTTPError) as error:self.request('/api/task',{'id':t['id'],'version':99,'fields':shipment()})
        self.assertEqual(error.exception.code,409)
        with self.request('/api/task?id='+t['id']) as r:self.assertEqual(json.load(r)['fields'],{})
    def test_04_reject_external_origin(self):
        with self.assertRaises(HTTPError) as error:self.request('/api/tasks',{}, {'Origin':'https://example.invalid'})
        self.assertEqual(error.exception.code,403)
    def test_05_rollback_invalid_update(self):
        with self.request('/api/tasks',{}) as r:t=json.load(r)
        with self.assertRaises(HTTPError):self.request('/api/quote',{'id':t['id'],'version':0,'fields':shipment(weight_kg=-1)})
        with self.request('/api/task?id='+t['id']) as r:self.assertEqual(json.load(r)['version'],0)
    def test_06_export_document(self):
        with self.request('/api/tasks',{}) as r:t=json.load(r)
        with self.request('/api/documents/check',{'id':t['id'],'version':0,'fields':documents()}) as r:self.assertEqual(json.load(r)['task']['checks']['issues'],[])
        with self.request('/api/document?id='+t['id']+'&kind=invoice') as r:self.assertIn('COMMERCIAL INVOICE',r.read().decode())


if __name__=='__main__':unittest.main()
