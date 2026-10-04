from concurrent.futures import ThreadPoolExecutor
import sqlite3
import unittest
import test_numera as foundation

class PurchaseTests(unittest.TestCase):
    setUp=foundation.NumeraTests.setUp
    tearDown=foundation.NumeraTests.tearDown
    register=foundation.NumeraTests.register
    product=foundation.NumeraTests.product

    def supplier(self,headers=None,code='SUP-1'):
        r=self.client.post('/api/suppliers',headers=headers or self.a,json={'code':code,'name':'Supplier One'})
        self.assertEqual(r.status_code,201,r.text)
        return r.json()['id']

    def draft(self,supplier=None,product=None,headers=None,**extra):
        headers=headers or self.a
        supplier=supplier or self.supplier(headers)
        product=product or self.product(headers).json()['id']
        data={'supplier_id':supplier,'supplier_reference':'INV-01','document_date':'2026-10-04','due_date':'2026-11-04',
              'request_key':'purchase-request-0001','lines':[{'product_id':product,'quantity':'2.125','unit_price':'10.00','tax_rate':'14'}],**extra}
        return self.client.post('/api/purchases',headers=headers,json=data)

    def receive(self,pid,headers=None):
        return self.client.post(f'/api/purchases/{pid}/receive',headers=headers or self.a)

    def balance(self,headers=None):
        return self.client.get('/api/inventory/balances',headers=headers or self.a).json()

    def employee(self,role):
        self.client.post('/api/users',headers=self.a,json={'name':'Employee','email':role+'@example.com','password':'Employee password 123!','role':role})
        r=self.client.post('/api/auth/login',json={'email':role+'@example.com','password':'Employee password 123!'})
        return {'Authorization':'Bearer '+r.json()['access_token']}

    def test_draft_totals_and_receipt_update_stock_once(self):
        draft=self.draft()
        self.assertEqual(draft.status_code,201,draft.text)
        data=draft.json()
        self.assertEqual((data['subtotal'],data['tax'],data['total']),('21.25','2.98','24.23'))
        self.assertEqual(self.balance()[0]['quantity'],'0.000')
        self.assertFalse(self.receive(data['id']).json()['replayed'])
        self.assertTrue(self.receive(data['id']).json()['replayed'])
        self.assertEqual(self.balance()[0]['quantity'],'2.125')
        details=self.client.get(f'/api/purchases/{data["id"]}',headers=self.a).json()
        self.assertEqual(details['status'],'received')
        self.assertTrue(details['received_at'])
        self.assertEqual(len(self.client.get('/api/inventory/movements',headers=self.a).json()),1)

    def test_multiline_receipt(self):
        supplier=self.supplier(); p1=self.product(self.a).json()['id']; p2=self.product(self.a,sku='P2').json()['id']
        r=self.draft(supplier,p1,lines=[{'product_id':p1,'quantity':'1.001','unit_price':'1.01'},{'product_id':p2,'quantity':'2','unit_price':'3','tax_rate':0}])
        self.assertEqual(r.json()['subtotal'],'7.01')
        self.assertEqual(self.receive(r.json()['id']).status_code,200)
        self.assertEqual([row['quantity'] for row in self.balance()],['1.001','2.000'])

    def test_creation_retry_and_supplier_reference_deduplication(self):
        sup=self.supplier(); product=self.product(self.a).json()['id']
        first=self.draft(sup,product).json()
        replay=self.draft(sup,product).json()
        self.assertEqual(first['id'],replay['id']); self.assertTrue(replay['replayed'])
        self.assertEqual(self.draft(sup,product,notes='Changed').status_code,409)
        self.assertEqual(self.draft(sup,product,request_key='purchase-request-0002').status_code,409)
        self.assertEqual(len(self.client.get('/api/purchases',headers=self.a).json()),1)

    def test_tenant_isolation(self):
        sup=self.supplier(); product=self.product(self.a).json()['id']; pid=self.draft(sup,product).json()['id']
        self.assertEqual(self.client.get('/api/suppliers',headers=self.b).json(),[])
        self.assertEqual(self.client.get('/api/purchases',headers=self.b).json(),[])
        self.assertEqual(self.client.get(f'/api/purchases/{pid}',headers=self.b).status_code,404)
        self.assertEqual(self.receive(pid,self.b).status_code,404)
        self.assertEqual(self.draft(sup,product,headers=self.b).status_code,404)
        other=self.supplier(self.b)
        self.assertEqual(self.draft(other,product,headers=self.b).status_code,404)
        self.assertEqual(self.client.get('/api/purchases/receiving',headers=self.b).json(),[])

    def test_role_permissions_and_price_redaction(self):
        pid=self.draft().json()['id']
        inv=self.employee('inventory'); accountant=self.employee('accountant')
        self.assertEqual(self.client.get('/api/purchases',headers=inv).status_code,403)
        receiving=self.client.get('/api/purchases/receiving',headers=inv).json()[0]
        self.assertNotIn('total',receiving); self.assertNotIn('unit_price',receiving['lines'][0])
        self.assertEqual(self.receive(pid,accountant).status_code,403)
        self.assertEqual(self.receive(pid,inv).status_code,200)
        self.assertEqual(self.client.post('/api/suppliers',headers=inv,json={'code':'S','name':'Supplier'}).status_code,403)
        self.assertEqual(self.client.get('/api/purchases').status_code,401)

    def test_cancel_preserves_records_without_stock(self):
        pid=self.draft().json()['id']
        self.assertEqual(self.client.post(f'/api/purchases/{pid}/cancel',headers=self.a).status_code,200)
        self.assertEqual(self.receive(pid).status_code,409)
        self.assertEqual(self.balance()[0]['quantity'],'0.000')
        self.assertEqual(self.client.get(f'/api/purchases/{pid}',headers=self.a).json()['status'],'cancelled')

    def test_received_purchase_cannot_be_cancelled(self):
        pid=self.draft().json()['id']; self.receive(pid)
        self.assertEqual(self.client.post(f'/api/purchases/{pid}/cancel',headers=self.a).status_code,409)
        self.assertEqual(self.balance()[0]['quantity'],'2.125')

    def test_invalid_dates_duplicate_products_and_precision(self):
        sup=self.supplier(); product=self.product(self.a).json()['id']
        for changes in ({'due_date':'2026-01-01'},{'lines':[]},{'lines':[{'product_id':product,'quantity':1,'unit_price':1}]*2},
                        {'lines':[{'product_id':product,'quantity':'0.0001','unit_price':1}]},
                        {'lines':[{'product_id':product,'quantity':1,'unit_price':'1.001'}]},
                        {'lines':[{'product_id':product,'quantity':1,'unit_price':1,'tax_rate':101}]}):
            self.assertEqual(self.draft(sup,product,**changes).status_code,422)

    def test_concurrent_receive_never_duplicates_stock(self):
        pid=self.draft().json()['id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.receive(pid).json(),range(2)))
        self.assertEqual(sorted(r['replayed'] for r in results),[False,True])
        self.assertEqual(self.balance()[0]['quantity'],'2.125')

    def test_failed_receipt_rolls_back_all_lines(self):
        sup=self.supplier(); p1=self.product(self.a).json()['id']; p2=self.product(self.a,sku='P2').json()['id']
        self.client.post('/api/inventory/movements',headers=self.a,json={'product_id':p2,'kind':'opening','quantity':'99999999999.999','reason':'Opening count','request_key':'opening-big-request-01'})
        draft=self.draft(sup,p1,lines=[{'product_id':p1,'quantity':1,'unit_price':0},{'product_id':p2,'quantity':1,'unit_price':0}]).json()
        self.assertEqual(self.receive(draft['id']).status_code,422)
        self.assertEqual(self.balance()[0]['quantity'],'0.000')
        self.assertEqual(self.client.get(f'/api/purchases/{draft["id"]}',headers=self.a).json()['status'],'draft')
        self.assertEqual(len(self.client.get('/api/inventory/movements',headers=self.a).json()),1)

    def test_system_stock_keys_are_reserved(self):
        product=self.product(self.a).json()['id']
        r=self.client.post('/api/inventory/movements',headers=self.a,json={'product_id':product,'kind':'receipt','quantity':1,'reason':'Test receipt','request_key':'sys_purchase_1_line_1'})
        self.assertEqual(r.status_code,422)
