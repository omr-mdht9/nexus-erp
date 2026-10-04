import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi.testclient import TestClient
from jose import jwt
from numera.main import create_app


class NumeraTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'numera.db'
        self.secret = 'test-only-numera-secret-at-least-32-characters'
        self.app = create_app(self.path, self.secret)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.a = self.register('a@example.com', 'Alpha')
        self.b = self.register('b@example.com', 'Beta')

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.temp.cleanup()

    def register(self, email, company):
        r = self.client.post('/api/auth/register', json={'email':email,'name':'Test Owner','company_name':company,'password':'Example password 123!'})
        self.assertEqual(r.status_code,201,r.text)
        return {'Authorization':'Bearer '+r.json()['access_token']}

    def product(self, headers, **extra):
        return self.client.post('/api/products',headers=headers,json={'sku':'P-01','name':'Product One','sale_price':'12.50',**extra})

    def test_registration_login_and_trial(self):
        me = self.client.get('/api/auth/me',headers=self.a).json()
        self.assertEqual(me['company']['name'],'Alpha')
        start = datetime.fromisoformat(me['company']['created_at'])
        end = datetime.fromisoformat(me['company']['trial_ends_at'])
        self.assertEqual(end-start,timedelta(days=30))
        self.assertFalse(me['subscription']['billing_enabled'])
        response = self.client.post('/api/auth/login',json={'email':'A@EXAMPLE.COM','password':'Example password 123!'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.post('/api/auth/login',json={'email':'a@example.com','password':'bad'}).status_code,401)

    def test_products_and_direct_ids_are_isolated(self):
        response = self.product(self.a)
        self.assertEqual(response.status_code,201,response.text)
        identity = response.json()['id']
        self.assertEqual(self.client.get('/api/products',headers=self.b).json(),[])
        self.assertEqual(self.client.get(f'/api/products/{identity}',headers=self.b).status_code,404)
        self.assertEqual(self.client.get(f'/api/products/{identity}',headers=self.a).status_code,200)
        self.assertEqual(self.product(self.b).status_code,201)
        self.assertEqual(self.product(self.a).status_code,409)

    def test_client_cannot_choose_tenant(self):
        self.product(self.a,company_id=2)
        self.assertEqual(len(self.client.get('/api/products',headers=self.a).json()),1)
        self.assertEqual(self.client.get('/api/products',headers=self.b).json(),[])

    def test_employee_permissions_and_isolation(self):
        for role in ('inventory','accountant'):
            response = self.client.post('/api/users',headers=self.a,json={'name':'Employee','email':role+'@example.com','password':'Employee password 123!','role':role,'company_id':2})
            self.assertEqual(response.status_code,201,response.text)
            session = self.client.post('/api/auth/login',json={'email':role+'@example.com','password':'Employee password 123!'}).json()
            headers = {'Authorization':'Bearer '+session['access_token']}
            self.assertEqual(self.client.get('/api/auth/me',headers=headers).json()['company']['name'],'Alpha')
            self.assertEqual(self.client.get('/api/users',headers=headers).status_code,403)
            self.assertEqual(self.client.get('/api/audit-logs',headers=headers).status_code,403)
            self.assertEqual(self.product(headers,sku=role).status_code,201 if role=='inventory' else 403)
        self.assertEqual(len(self.client.get('/api/users',headers=self.b).json()),1)

    def test_duplicate_registration_rolls_back_company(self):
        r = self.client.post('/api/auth/register',json={'email':'A@example.com','name':'Another Owner','company_name':'Orphan','password':'Example password 123!'})
        self.assertEqual(r.status_code,409)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM companies').fetchone()[0],2)
            self.assertNotIn('Example password', db.execute('SELECT password_hash FROM users').fetchone()[0])

    def test_audit_logs_are_isolated(self):
        self.product(self.a)
        self.assertEqual(len(self.client.get('/api/audit-logs',headers=self.a).json()),2)
        self.assertEqual(len(self.client.get('/api/audit-logs',headers=self.b).json()),1)

    def test_token_validation_and_deactivation(self):
        for claims in ({'sub':'1','company_id':2,'exp':datetime.now(timezone.utc)+timedelta(hours=1)}, {'sub':'1','company_id':1,'exp':datetime.now(timezone.utc)-timedelta(seconds=1)}, {'sub':'1','company_id':1}):
            claims.update(aud='numera-development',iss='numera')
            token = jwt.encode(claims,self.secret,algorithm='HS256')
            self.assertEqual(self.client.get('/api/products',headers={'Authorization':'Bearer '+token}).status_code,401)
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE users SET active=0 WHERE id=1')
        self.assertEqual(self.client.get('/api/products',headers=self.a).status_code,401)

    def test_anonymous_requests_denied(self):
        for endpoint in ('/api/auth/me','/api/products','/api/users','/api/audit-logs'):
            self.assertEqual(self.client.get(endpoint).status_code,401)

    def test_validation_rejects_bad_values(self):
        for changes in ({'sale_price':'-1'},{'sale_price':'NaN'},{'sale_price':'0.001'},{'name':'  '},{'sku':' '},{'reorder_level':'-1'}):
            self.assertEqual(self.product(self.a,**changes).status_code,422)
        r = self.client.post('/api/auth/register',json={'email':'invalid','name':'Owner','company_name':'Company','password':'short'})
        self.assertEqual(r.status_code,422)

    def test_health_and_static_pages(self):
        self.assertEqual(self.client.get('/api/health').json()['product'],'NUMERA ERP')
        for path in ('/','/app','/static/style.css','/static/workspace.js'):
            response = self.client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertIn('Content-Security-Policy',response.headers)

    def test_auth_rate_limit(self):
        results = [self.client.post('/api/auth/login',json={'email':'nobody@example.com','password':'bad'}).status_code for _ in range(20)]
        self.assertEqual(results[-1],429)

    def test_trial_expiry_is_reported_without_data_loss(self):
        self.product(self.a)
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE companies SET trial_ends_at=? WHERE id=1',((datetime.now(timezone.utc)-timedelta(days=1)).isoformat(),))
        self.assertEqual(self.client.get('/api/auth/me',headers=self.a).json()['subscription']['status'],'trial_expired')
        self.assertEqual(len(self.client.get('/api/products',headers=self.a).json()),1)

    def test_rejects_legacy_database_and_weak_secret(self):
        with self.assertRaises(RuntimeError): create_app('/tmp/erp.db',self.secret)
        with self.assertRaises(RuntimeError): create_app(self.path,'short')

if __name__ == '__main__':
    unittest.main()
