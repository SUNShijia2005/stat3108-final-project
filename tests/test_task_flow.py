"""Preparation workflow and field-located errors, using synthetic local data only."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import app
from parcel.domain import clean_fields, quote, document_check, select_service, task_progress, summary_html, ValidationError
from parcel.storage import Store


def fields(**changes):
    return {"origin_province":"Shanghai","destination_country":"US","destination_city":"Los Angeles",
            "destination_state":"CA","destination_zip":"90001","goods":"Cotton T-shirts",
            "weight_kg":10,"length_cm":30,"width_cm":20,"height_cm":10,"budget_cny":5000,
            "sender_name":"Example sender","sender_address":"Fictitious address","sender_phone":"000000",
            "recipient_name":"Example recipient","recipient_address":"Fictitious address","recipient_phone":"000000",
            "currency":"USD","country_of_origin":"CN","invoice_total":50,"invoice_number":"TEST-001","ship_date":"2026-11-17",
            "items":[{"description":"Cotton T-shirt","quantity":2,"packing_quantity":2,"unit_price":25}],**changes}


def task(**changes):
    return {"id":"test-preparation","version":0,"fields":fields(),"quote":None,"checks":None,"tracking":None,"messages":[],"selected_service":None,**changes}


class PreparationFlowTests(unittest.TestCase):
    def test_selection_requires_current_estimate(self):
        t=task()
        with self.assertRaises(ValidationError):select_service(t,'IE')
        self.assertIsNone(t['selected_service'])

    def test_selection_uses_server_price(self):
        t=task();t['quote']=quote(t['fields']);selected=select_service(t,'IE')
        self.assertEqual(selected['known_subtotal'],3879.30)
        self.assertEqual(selected['service'],'IE')
        with self.assertRaises(ValidationError):select_service(t,{'service':'IE','known_subtotal':1})
        with self.assertRaises(ValidationError):select_service(t,'UNKNOWN')

    def test_preparation_progress_follows_required_steps(self):
        t=task();self.assertEqual(task_progress(t)['next_view'],'rates')
        t['quote']=quote(t['fields']);self.assertEqual(task_progress(t)['steps'][0]['status'],'complete')
        select_service(t,'IP');self.assertEqual(task_progress(t)['next_view'],'documents')
        t['checks']=document_check(t['fields']);p=task_progress(t)
        self.assertTrue(p['ready_for_summary']);self.assertEqual(p['next_view'],'summary')

    def test_old_selection_not_ready_when_quote_changes(self):
        t=task();t['quote']=quote(t['fields']);select_service(t,'IE');t['checks']=document_check(t['fields'])
        t['fields']['weight_kg']=8;t['quote']=quote(t['fields'])
        self.assertFalse(task_progress(t)['ready_for_summary'])
        self.assertEqual(task_progress(t)['steps'][1]['status'],'current')

    def test_summary_escapes_customer_text(self):
        t=task(fields=fields(goods='<script>alert(1)</script>',destination_city='<img src=x>'))
        text=summary_html(t)
        self.assertIn('&lt;script&gt;',text);self.assertNotIn('<script>alert',text)
        self.assertIn('&lt;img src=x&gt;',text)
        self.assertIn('尚未订舱',text)

    def test_summary_contains_chosen_reference_and_pending(self):
        t=task();t['quote']=quote(t['fields']);select_service(t,'IP');t['checks']=document_check(t['fields'])
        text=summary_html(t)
        self.assertIn('CNY 3,950.30',text);self.assertIn('当期燃油附加费',text);self.assertIn('基础一致性检查通过',text)

    def test_known_city_state_zip_consistency(self):
        for city,state,zip_code in [('New York','NY','90001'),('Seattle','WA','10001'),('Los Angeles','NY','10001')]:
            with self.subTest(city=city),self.assertRaises(ValidationError):quote(fields(destination_city=city,destination_state=state,destination_zip=zip_code))
        self.assertEqual(quote(fields(destination_city='New York',destination_state='NY',destination_zip='10001'))['zone'],'2')

    def test_document_issues_locate_fields_and_rows(self):
        f=fields(recipient_phone=None,invoice_total=60)
        f['items'][0]['packing_quantity']=1
        issues={row['code']:row for row in document_check(f)['issues']}
        self.assertEqual(issues['missing_recipient_phone']['field'],'recipient_phone')
        self.assertEqual(issues['quantity_mismatch']['item_index'],0)
        self.assertEqual(issues['quantity_mismatch']['field'],'packing_quantity')
        self.assertEqual(issues['total_mismatch']['field'],'invoice_total')

    def test_missing_invoice_reference_or_date_prevents_ready_summary(self):
        for field in ['invoice_number','ship_date']:
            with self.subTest(field=field):
                t=task(fields=fields(**{field:None}));t['quote']=quote(t['fields']);select_service(t,'IP')
                t['checks']=document_check(t['fields'])
                issue=next(row for row in t['checks']['issues'] if row['code']=='missing_'+field)
                self.assertEqual(issue['field'],field)
                self.assertFalse(task_progress(t)['ready_for_summary'])
                self.assertEqual(task_progress(t)['next_view'],'documents')

    def test_zero_value_requires_correction(self):
        f=fields(invoice_total=0);f['items'][0]['unit_price']=0
        result=document_check(f)
        self.assertEqual(result['status'],'needs_correction')
        issue=next(row for row in result['issues'] if row['code']=='zero_value')
        self.assertEqual((issue['field'],issue['item_index']),('unit_price',0))

    def test_cent_precision_does_not_export_inconsistent_math(self):
        f=fields();f['items'][0]['unit_price']=.335
        result=document_check(f)
        self.assertEqual(result['status'],'needs_correction');self.assertEqual(result['lines'],[])
        self.assertEqual(result['issues'][0]['field'],'unit_price')

    def test_item_shape_and_nonfinite_values_rejected_before_save(self):
        for items in [[{'description':{'bad':'shape'}}],[{'quantity':True}],[{'unit_price':'NaN'}],[{'description':'book','unexpected':1}],['not an item']]:
            with self.subTest(items=items),self.assertRaises(ValidationError):clean_fields({'items':items})

    def test_csv_missing_other_document_stays_missing(self):
        items=app.import_csv({},'description,quantity,unit_price\nPrinted book,2,10\n','invoice')
        result=document_check(fields(items=items,invoice_total=20))
        self.assertTrue(any(row.get('field')=='packing_quantity' for row in result['issues']))
        self.assertNotIn('packing_quantity',items[0])

    def test_csv_rejects_ambiguous_structure(self):
        for text in ['description,quantity,quantity\nBook,1,2\n','description,quantity\nBook,1,extra\n']:
            with self.subTest(text=text),self.assertRaises(ValidationError):app.import_csv({},text,'packing')

    def test_history_keeps_human_readable_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'history.sqlite3');t=store.create(demo=True);t['fields']=fields();store.save(t)
            row=store.list()[0]
            self.assertEqual(row['origin'],'Shanghai');self.assertEqual(row['city'],'Los Angeles')
            self.assertEqual(row['weight_kg'],10);self.assertTrue(row['is_demo'])


class PreparationHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.previous=app.STORE;app.STORE=Store(Path(cls.temp.name)/'http.sqlite3')
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();app.STORE=cls.previous;cls.temp.cleanup()

    def request(self,path,body=None):
        request=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        return urlopen(request,timeout=5)

    def create(self):
        with self.request('/api/tasks',{'demo':True}) as response:return json.load(response)

    def test_select_without_quote_leaves_task_unchanged(self):
        t=self.create()
        with self.assertRaises(HTTPError) as error:self.request('/api/select',{'id':t['id'],'version':0,'service':'IE'})
        self.assertEqual(error.exception.code,400)
        with self.request('/api/task?id='+t['id']) as response:again=json.load(response)
        self.assertEqual(again['version'],0);self.assertIsNone(again['selected_service'])

    def test_full_preparation_api_flow_and_summary(self):
        t=self.create();self.assertIn('progress',t)
        for path,extra in [('/api/quote',{'fields':fields()}),('/api/select',{'service':'IP'}),('/api/documents/check',{})]:
            with self.request(path,{'id':t['id'],'version':t['version'],**extra}) as response:t=json.load(response)['task']
        self.assertTrue(t['progress']['ready_for_summary']);self.assertEqual(t['selected_service']['known_subtotal'],3950.30)
        with self.request('/api/export/summary?id='+t['id']) as response:
            text=response.read().decode();self.assertIn('CNY 3,950.30',text);self.assertIn('寄件准备清单',text)
        with self.request('/api/tasks') as response:
            row=next(row for row in json.load(response)['tasks'] if row['id']==t['id'])
        self.assertEqual(row['selected_service'],'IP');self.assertTrue(row['is_demo'])

    def test_only_printable_endpoints_allow_same_origin_frames(self):
        t=self.create()
        for path in ['/api/document?id='+t['id']+'&kind=invoice','/api/document?id='+t['id']+'&kind=packing','/api/export/summary?id='+t['id']]:
            with self.subTest(path=path),self.request(path) as response:
                self.assertIn("frame-ancestors 'self'",response.headers['Content-Security-Policy'])
        for path in ['/','/api/health','/api/task?id='+t['id']]:
            with self.subTest(path=path),self.request(path) as response:
                self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])


if __name__=='__main__':unittest.main()
