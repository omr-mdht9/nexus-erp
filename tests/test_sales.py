from concurrent.futures import ThreadPoolExecutor
import unittest
import test_numera as foundation

class SalesTests(unittest.TestCase):
    setUp=foundation.NumeraTests.setUp
    tearDown=foundation.NumeraTests.tearDown
    register=foundation.NumeraTests.register
    product=foundation.NumeraTests.product

    def customer(self,headers=None):
        r=self.client.post('/api/customers',headers=headers or self.a,json={'code':'CUS-1','name':'Customer One'})
        self.assertEqual(r.status_code,201,r.text); return r.json()['id']

    def stock(self,pid,quantity='10'):
        r=self.client.post('/api/inventory/movements',headers=self.a,json={'product_id':pid,'kind':'opening','quantity':quantity,'reason':'Opening stock','request_key':f'opening-stock-key-{pid:06d}'})
        self.assertEqual(r.status_code,201,r.text)

    def draft(self,customer=None,product=None,headers=None,**extra):
        headers=headers or self.a; customer=customer or self.customer(headers); product=product or self.product(headers).json()['id']
        data={'customer_id':customer,'customer_reference':'REF-1','document_date':'2026-10-04','due_date':'2026-11-04',
            'request_key':'sale-request-key-0001','lines':[{'product_id':product,'quantity':'2.125','unit_price':'10.00','tax_rate':14}],**extra}
        return self.client.post('/api/sales',headers=headers,json=data)

    def post(self,pid,headers=None): return self.client.post(f'/api/sales/{pid}/post',headers=headers or self.a)
    def balance(self): return self.client.get('/api/inventory/balances',headers=self.a).json()

    def test_draft_and_post_with_exact_totals_and_retry(self):
        product=self.product(self.a).json()['id']; self.stock(product)
        r=self.draft(product=product); self.assertEqual(r.status_code,201,r.text); sale=r.json()
        self.assertEqual((sale['subtotal'],sale['tax'],sale['total']),('21.25','2.98','24.23'))
        self.assertEqual(self.balance()[0]['quantity'],'10.000')
        self.assertFalse(self.post(sale['id']).json()['replayed'])
        self.assertTrue(self.post(sale['id']).json()['replayed'])
        self.assertEqual(self.balance()[0]['quantity'],'7.875')
        row=self.client.get(f'/api/sales/{sale["id"]}',headers=self.a).json()
        self.assertEqual(row['status'],'posted'); self.assertTrue(row['posted_at'])

    def test_insufficient_stock_keeps_draft(self):
        sale=self.draft().json(); before=self.client.get('/api/audit-logs',headers=self.a).json()
        self.assertEqual(self.post(sale['id']).status_code,409)
        self.assertEqual(self.client.get(f'/api/sales/{sale["id"]}',headers=self.a).json()['status'],'draft')
        self.assertEqual(self.client.get('/api/audit-logs',headers=self.a).json(),before)
        self.assertEqual(self.client.get('/api/inventory/movements',headers=self.a).json(),[])

    def test_multiline_failure_rolls_back_earlier_deduction(self):
        p1=self.product(self.a).json()['id']; p2=self.product(self.a,sku='P2').json()['id']; self.stock(p1)
        sale=self.draft(product=p1,lines=[{'product_id':p1,'quantity':1,'unit_price':1},{'product_id':p2,'quantity':1,'unit_price':1}]).json()
        self.assertEqual(self.post(sale['id']).status_code,409)
        self.assertEqual(self.balance()[0]['quantity'],'10.000')
        self.assertEqual(len(self.client.get('/api/inventory/movements',headers=self.a).json()),1)

    def test_tenant_isolation(self):
        customer=self.customer(); product=self.product(self.a).json()['id']; sale=self.draft(customer,product).json()['id']
        self.assertEqual(self.client.get('/api/customers',headers=self.b).json(),[])
        self.assertEqual(self.client.get('/api/sales',headers=self.b).json(),[])
        self.assertEqual(self.client.get(f'/api/sales/{sale}',headers=self.b).status_code,404)
        self.assertEqual(self.post(sale,self.b).status_code,404)
        self.assertEqual(self.draft(customer,product,headers=self.b).status_code,404)
        other=self.customer(self.b)
        self.assertEqual(self.draft(other,product,headers=self.b).status_code,404)

    def test_creation_idempotency_and_duplicate_reference(self):
        customer=self.customer(); product=self.product(self.a).json()['id']
        first=self.draft(customer,product).json(); retry=self.draft(customer,product).json()
        self.assertEqual(first['id'],retry['id']); self.assertTrue(retry['replayed'])
        self.assertEqual(self.draft(customer,product,notes='Changed').status_code,409)
        self.assertEqual(self.draft(customer,product,request_key='sale-request-key-0002').status_code,409)
        self.assertEqual(len(self.client.get('/api/sales',headers=self.a).json()),1)

    def test_cancellation_and_posted_document_protection(self):
        product=self.product(self.a).json()['id']; self.stock(product); customer=self.customer()
        first=self.draft(customer,product).json()['id']
        self.assertEqual(self.client.post(f'/api/sales/{first}/cancel',headers=self.a).status_code,200)
        self.assertEqual(self.post(first).status_code,409)
        second=self.draft(customer,product,customer_reference='REF-2',request_key='sale-request-key-0002').json()['id']; self.post(second)
        self.assertEqual(self.client.post(f'/api/sales/{second}/cancel',headers=self.a).status_code,409)

    def test_inventory_role_cannot_read_or_post_sales(self):
        sale=self.draft().json()['id']
        self.client.post('/api/users',headers=self.a,json={'name':'Employee','email':'inventory@example.com','password':'Employee password 123!','role':'inventory'})
        token=self.client.post('/api/auth/login',json={'email':'inventory@example.com','password':'Employee password 123!'}).json()['access_token']
        headers={'Authorization':'Bearer '+token}
        self.assertEqual(self.client.get('/api/sales',headers=headers).status_code,403)
        self.assertEqual(self.post(sale,headers).status_code,403)
        self.assertEqual(self.client.post('/api/customers',headers=headers,json={'code':'C2','name':'Other'}).status_code,403)
        self.assertEqual(self.client.get('/api/sales').status_code,401)

    def test_simultaneous_sales_cannot_oversell(self):
        product=self.product(self.a).json()['id']; self.stock(product,'3'); customer=self.customer()
        invoices=[self.draft(customer,product,customer_reference=f'REF-{i}',request_key=f'sale-concurrency-{i:04d}').json()['id'] for i in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda pid:self.post(pid).status_code,invoices))
        self.assertEqual(sorted(results),[200,409]); self.assertEqual(self.balance()[0]['quantity'],'0.875')

    def test_purchase_to_sale_integration(self):
        product=self.product(self.a).json()['id']
        supplier=self.client.post('/api/suppliers',headers=self.a,json={'code':'SUP1','name':'Supplier'}).json()['id']
        purchase=self.client.post('/api/purchases',headers=self.a,json={'supplier_id':supplier,'document_date':'2026-10-04','due_date':'2026-10-04','request_key':'integration-purchase-key','lines':[{'product_id':product,'quantity':5,'unit_price':8}]}).json()['id']
        self.assertEqual(self.client.post(f'/api/purchases/{purchase}/receive',headers=self.a).status_code,200)
        sale=self.draft(product=product,lines=[{'product_id':product,'quantity':2,'unit_price':10}]).json()['id']
        self.assertEqual(self.post(sale).status_code,200)
        self.assertEqual(self.balance()[0]['quantity'],'3.000')
        movements=self.client.get('/api/inventory/movements',headers=self.a).json()
        self.assertEqual([m['change'] for m in movements],['-2.000','5.000'])

    def test_invalid_dates_and_duplicate_lines(self):
        customer=self.customer(); product=self.product(self.a).json()['id']
        self.assertEqual(self.draft(customer,product,due_date='2026-01-01').status_code,422)
        self.assertEqual(self.draft(customer,product,lines=[]).status_code,422)
        self.assertEqual(self.draft(customer,product,lines=[{'product_id':product,'quantity':1,'unit_price':1}]*2).status_code,422)

    def test_concurrent_post_same_invoice_deducts_once(self):
        product=self.product(self.a).json()['id']; self.stock(product)
        sale=self.draft(product=product).json()['id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.post(sale).json(),range(2)))
        self.assertEqual(sorted(r['replayed'] for r in results),[False,True])
        self.assertEqual(self.balance()[0]['quantity'],'7.875')
        self.assertEqual(len(self.client.get('/api/inventory/movements',headers=self.a).json()),2)
