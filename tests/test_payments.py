from concurrent.futures import ThreadPoolExecutor
import unittest
import test_numera as foundation

class PaymentTests(unittest.TestCase):
    setUp=foundation.NumeraTests.setUp
    tearDown=foundation.NumeraTests.tearDown
    register=foundation.NumeraTests.register
    product=foundation.NumeraTests.product

    def documents(self):
        product=self.product(self.a).json()['id']
        supplier=self.client.post('/api/suppliers',headers=self.a,json={'code':'S1','name':'Supplier'}).json()['id']
        purchase=self.client.post('/api/purchases',headers=self.a,json={'supplier_id':supplier,'document_date':'2026-10-04','due_date':'2026-10-20','request_key':'payment-purchase-key','lines':[{'product_id':product,'quantity':5,'unit_price':8}]}).json()['id']
        self.client.post(f'/api/purchases/{purchase}/receive',headers=self.a)
        customer=self.client.post('/api/customers',headers=self.a,json={'code':'C1','name':'Customer'}).json()['id']
        sale=self.client.post('/api/sales',headers=self.a,json={'customer_id':customer,'document_date':'2026-10-04','due_date':'2026-10-10','request_key':'payment-sale-key-01','lines':[{'product_id':product,'quantity':3,'unit_price':10,'tax_rate':14}]}).json()['id']
        self.client.post(f'/api/sales/{sale}/post',headers=self.a)
        return sale,purchase

    def pay(self,document,kind='receipt',amount='10',headers=None,**extra):
        return self.client.post('/api/payments',headers=headers or self.a,json={'kind':kind,'document_id':document,'amount':amount,'method':'bank',
            'payment_date':'2026-10-04','request_key':'payment-request-key-0001',**extra})

    def outstanding(self,headers=None):
        return self.client.get('/api/outstanding?aging_date=2026-10-15',headers=headers or self.a).json()

    def test_partial_and_full_receipt_and_supplier_payment(self):
        sale,purchase=self.documents()
        self.assertEqual(self.pay(sale).status_code,201)
        self.assertEqual(self.outstanding()['customer_outstanding'],'24.20')
        self.assertEqual(self.pay(sale,amount='24.20',request_key='payment-request-key-0002').status_code,201)
        self.assertEqual(self.pay(purchase,'payment','15',request_key='payment-request-key-0003').status_code,201)
        report=self.outstanding(); self.assertEqual(report['customer_outstanding'],'0.00'); self.assertEqual(report['supplier_outstanding'],'25.00')
        self.assertEqual([row['status'] for row in report['documents']],['settled','open'])
        summary=self.client.get('/api/payment-summary',headers=self.a).json()[1]
        self.assertEqual(summary['net_recorded_settlements'],'19.20')

    def test_payment_replay_and_conflict(self):
        sale,_=self.documents(); first=self.pay(sale).json(); replay=self.pay(sale,amount='10.00').json()
        self.assertEqual(first['id'],replay['id']); self.assertTrue(replay['replayed'])
        self.assertEqual(self.pay(sale,amount='11').status_code,409)
        self.assertEqual(self.outstanding()['customer_outstanding'],'24.20')

    def test_void_preserves_history_and_reopens_balance(self):
        sale,_=self.documents(); payment=self.pay(sale).json()['id']
        r=self.client.post(f'/api/payments/{payment}/void',headers=self.a,json={'reason':'Recorded in error'})
        self.assertEqual(r.status_code,200,r.text); self.assertEqual(r.json()['status'],'voided')
        self.assertEqual(self.outstanding()['customer_outstanding'],'34.20')
        history=self.client.get('/api/payments',headers=self.a).json()
        self.assertEqual(len(history),1); self.assertEqual(history[0]['void_reason'],'Recorded in error')
        replay=self.pay(sale).json(); self.assertEqual(replay['status'],'voided')
        self.assertEqual(self.outstanding()['customer_outstanding'],'34.20')

    def test_overpayment_and_invalid_date_leave_no_record(self):
        sale,_=self.documents()
        self.assertEqual(self.pay(sale,amount='34.21').status_code,409)
        self.assertEqual(self.pay(sale,payment_date='2026-01-01').status_code,422)
        self.assertEqual(self.client.get('/api/payments',headers=self.a).json(),[])

    def test_duplicate_bank_reference_is_rejected(self):
        sale,_=self.documents(); self.pay(sale,reference='BANK-123')
        self.assertEqual(self.pay(sale,reference='BANK-123',request_key='different-payment-key').status_code,409)
        self.assertEqual(self.outstanding()['customer_outstanding'],'24.20')

    def test_company_isolation(self):
        sale,_=self.documents(); payment=self.pay(sale).json()['id']
        self.assertEqual(self.pay(sale,headers=self.b).status_code,404)
        self.assertEqual(self.client.get('/api/payments',headers=self.b).json(),[])
        self.assertEqual(self.outstanding(self.b)['documents'],[])
        self.assertEqual(self.client.post(f'/api/payments/{payment}/void',headers=self.b,json={'reason':'Wrong company'}).status_code,404)

    def test_inventory_role_and_anonymous_denied(self):
        sale,_=self.documents()
        self.client.post('/api/users',headers=self.a,json={'name':'Employee','email':'inventory@example.com','password':'Employee password 123!','role':'inventory'})
        token=self.client.post('/api/auth/login',json={'email':'inventory@example.com','password':'Employee password 123!'}).json()['access_token']; headers={'Authorization':'Bearer '+token}
        self.assertEqual(self.pay(sale,headers=headers).status_code,403)
        for endpoint in ('/api/payments','/api/outstanding','/api/payment-summary'):
            self.assertEqual(self.client.get(endpoint,headers=headers).status_code,403)
            self.assertEqual(self.client.get(endpoint).status_code,401)

    def test_concurrent_payments_cannot_overallocate(self):
        sale,_=self.documents()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda i:self.pay(sale,amount='20',request_key=f'concurrent-payment-{i:04d}').status_code,range(2)))
        self.assertEqual(sorted(results),[201,409]); self.assertEqual(self.outstanding()['customer_outstanding'],'14.20')

    def test_validation_and_overdue_classification(self):
        sale,_=self.documents()
        for amount in ('0','-1','NaN','1.001'):
            self.assertEqual(self.pay(sale,amount=amount).status_code,422)
        self.assertEqual(self.outstanding()['documents'][0]['status'],'overdue')
        self.assertEqual(self.client.get('/api/outstanding?aging_date=2026-10-10',headers=self.a).json()['documents'][0]['status'],'open')

    def test_unposted_documents_cannot_receive_payment(self):
        sale,_=self.documents()
        customer=self.client.get('/api/customers',headers=self.a).json()[0]['id']; product=self.client.get('/api/products',headers=self.a).json()[0]['id']
        draft=self.client.post('/api/sales',headers=self.a,json={'customer_id':customer,'document_date':'2026-10-04','due_date':'2026-10-04','request_key':'unposted-sale-request','lines':[{'product_id':product,'quantity':1,'unit_price':10}]}).json()['id']
        self.assertEqual(self.pay(draft).status_code,409)
