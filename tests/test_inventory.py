from concurrent.futures import ThreadPoolExecutor
import sqlite3
import unittest
import test_numera as foundation
from numera.main import create_app
from fastapi.testclient import TestClient


class InventoryTests(unittest.TestCase):
    setUp = foundation.NumeraTests.setUp
    tearDown = foundation.NumeraTests.tearDown
    register = foundation.NumeraTests.register
    product = foundation.NumeraTests.product

    def create_product(self, headers=None, sku='STOCK-01'):
        response = self.product(headers or self.a, sku=sku)
        self.assertEqual(response.status_code,201,response.text)
        return response.json()['id']

    def post(self, pid, quantity='10', kind='opening', key='inventory-request-0001', headers=None, **extra):
        return self.client.post('/api/inventory/movements',headers=headers or self.a,json={
            'product_id':pid,'quantity':quantity,'kind':kind,'request_key':key,'reason':'Test stock count',**extra})

    def balance(self, headers=None):
        return self.client.get('/api/inventory/balances',headers=headers or self.a).json()

    def test_opening_receipt_issue_and_adjustments(self):
        pid = self.create_product()
        self.assertTrue(self.balance()[0]['opening_allowed'])
        for kind,qty,key in [('opening','10.125','01'),('receipt','2.200','02'),('issue','1.025','03'),('adjustment_in','0.200','04'),('adjustment_out','0.100','05')]:
            r = self.post(pid,qty,kind,'stock-request-key-'+key)
            self.assertEqual(r.status_code,201,r.text)
        balance = self.balance()[0]
        self.assertEqual(balance['quantity'],'11.400')
        self.assertFalse(balance['opening_allowed'])
        history = self.client.get('/api/inventory/movements',headers=self.a).json()
        self.assertEqual(len(history),5)
        self.assertEqual(history[0]['change'],'-0.100')
        self.assertEqual(len(self.client.get('/api/audit-logs',headers=self.a).json()),7)

    def test_no_negative_stock_and_failed_post_has_no_audit(self):
        pid = self.create_product()
        self.post(pid,'1')
        before = self.client.get('/api/audit-logs',headers=self.a).json()
        self.assertEqual(self.post(pid,'1.001','issue','different-request-01').status_code,409)
        self.assertEqual(self.balance()[0]['quantity'],'1.000')
        self.assertEqual(self.client.get('/api/audit-logs',headers=self.a).json(),before)

    def test_opening_only_before_any_movement(self):
        pid = self.create_product()
        self.assertEqual(self.post(pid,kind='receipt').status_code,201)
        self.assertEqual(self.post(pid,key='another-opening-key').status_code,409)

    def test_idempotent_retry_and_conflicting_retry(self):
        pid = self.create_product()
        first = self.post(pid).json()
        replay = self.post(pid).json()
        self.assertEqual(first['id'],replay['id'])
        self.assertTrue(replay['replayed'])
        self.assertEqual(self.balance()[0]['quantity'],'10.000')
        self.assertEqual(self.post(pid,'11').status_code,409)
        self.assertEqual(len(self.client.get('/api/inventory/movements',headers=self.a).json()),1)

    def test_tenant_isolation_in_balances_and_history(self):
        pa = self.create_product()
        pb = self.create_product(self.b)
        self.post(pa)
        self.assertEqual(self.post(pa,headers=self.b).status_code,404)
        self.assertEqual(self.post(pb,'3',headers=self.b).status_code,201)
        self.assertEqual(self.balance(self.b)[0]['quantity'],'3.000')
        self.assertEqual(self.balance()[0]['quantity'],'10.000')
        self.assertEqual(len(self.client.get('/api/inventory/movements',headers=self.b).json()),1)
        self.assertEqual(self.client.get('/api/inventory/movements',params={'product_id':pa},headers=self.b).status_code,404)

    def test_permissions(self):
        pid = self.create_product()
        for role in ('accountant','inventory'):
            self.client.post('/api/users',headers=self.a,json={'name':'Employee','email':role+'@example.com','password':'Employee password 123!','role':role})
            session = self.client.post('/api/auth/login',json={'email':role+'@example.com','password':'Employee password 123!'}).json()
            headers = {'Authorization':'Bearer '+session['access_token']}
            self.assertEqual(self.client.get('/api/inventory/balances',headers=headers).status_code,200)
            self.assertEqual(self.post(pid,kind='receipt',key='employee-request-'+role,headers=headers).status_code,201 if role=='inventory' else 403)
        self.assertEqual(self.client.get('/api/inventory/balances').status_code,401)
        self.assertEqual(self.client.post('/api/inventory/movements',json={}).status_code,401)

    def test_quantity_validation_and_low_stock(self):
        pid = self.create_product()
        self.assertTrue(self.balance()[0]['low_stock'])
        for changes in ({'quantity':'0'},{'quantity':'-1'},{'quantity':'NaN'},{'quantity':'0.0001'},{'quantity':'100000000000'},{'reason':'   '},{'kind':'transfer'},{'request_key':'short'}):
            self.assertEqual(self.post(pid,**changes).status_code,422)
        self.post(pid,'0.001')
        self.assertFalse(self.balance()[0]['low_stock'])

    def test_simultaneous_issues_cannot_oversell(self):
        pid = self.create_product()
        self.post(pid,'10')
        def issue(number):
            return self.post(pid,'7','issue',f'concurrent-request-{number:02}').status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(issue,[1,2]))
        self.assertEqual(sorted(results),[201,409])
        self.assertEqual(self.balance()[0]['quantity'],'3.000')

    def test_schema_survives_restart_and_keeps_history(self):
        pid = self.create_product()
        self.post(pid,'2.345')
        with TestClient(create_app(self.path,self.secret)) as restarted:
            self.assertEqual(restarted.get('/api/inventory/balances',headers=self.a).json()[0]['quantity'],'2.345')
            self.assertEqual(len(restarted.get('/api/inventory/movements',headers=self.a).json()),1)

    def test_database_rejects_cross_company_product_reference(self):
        pid = self.create_product()
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO stock_movements(company_id,product_id,kind,quantity_milli,delta_milli,reason,request_key,actor_id,created_at) VALUES(2,?,'opening',1000,1000,'Test','forged-request-key',2,'2026-01-01')",(pid,))
