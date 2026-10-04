"""Isolated NUMERA development service; never imports or opens the legacy ERP."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from jose import jwt, JWTError
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parent
SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, currency TEXT NOT NULL,
 language TEXT NOT NULL, created_at TEXT NOT NULL, trial_ends_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('owner','accountant','inventory')), active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 sku TEXT NOT NULL, name TEXT NOT NULL, unit TEXT NOT NULL,
 sale_price TEXT NOT NULL, reorder_level TEXT NOT NULL,
 UNIQUE(company_id,sku));
CREATE TABLE IF NOT EXISTS audit_logs (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 actor_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL,
 entity_type TEXT NOT NULL, entity_id INTEGER NOT NULL, created_at TEXT NOT NULL);
"""


def connection(app):
    conn = sqlite3.connect(app.state.database_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def database(request: Request):
    conn = connection(request.app)
    try:
        yield conn
    finally:
        conn.close()


def now():
    return datetime.now(timezone.utc)


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return salt + ':' + digest.hex()


def verify_password(password, stored):
    salt, digest = stored.split(':')
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(candidate.hex(), digest)


class Registration(BaseModel):
    company_name: str = Field(min_length=2, max_length=160)
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)
    currency: Literal['EGP', 'AED', 'USD'] = 'EGP'
    language: Literal['en', 'ar'] = 'en'

    @field_validator('company_name', 'name')
    @classmethod
    def trim_names(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError('Enter at least two characters')
        return value

    @field_validator('email')
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if value.count('@') != 1 or any(c.isspace() for c in value):
            raise ValueError('Enter a valid email address')
        local, domain = value.split('@')
        if not local or '.' not in domain or domain.startswith('.') or domain.endswith('.'):
            raise ValueError('Enter a valid email address')
        return value


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class EmployeeIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)
    role: Literal['accountant', 'inventory']
    normalize_email = field_validator('email')(Registration.normalize_email.__func__)
    trim_names = field_validator('name')(Registration.trim_names.__func__)


class ProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=2, max_length=160)
    unit: str = Field(min_length=1, max_length=30, default='Piece')
    sale_price: Decimal = Field(default=Decimal('0'), ge=0, max_digits=14, decimal_places=2)
    reorder_level: Decimal = Field(default=Decimal('0'), ge=0, max_digits=14, decimal_places=3)

    @field_validator('sku', 'name', 'unit')
    @classmethod
    def trim(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Cannot be blank')
        return value


bearer = HTTPBearer(auto_error=False)


def current_user(request: Request, credentials: HTTPAuthorizationCredentials = Depends(bearer), conn=Depends(database)):
    if not credentials:
        raise HTTPException(401, 'Please sign in')
    try:
        claims = jwt.decode(credentials.credentials, request.app.state.secret, algorithms=['HS256'],
                            audience='numera-development', issuer='numera', options={'require_exp': True, 'require_sub': True})
        user_id = int(claims['sub'])
        company_id = int(claims['company_id'])
    except (JWTError, KeyError, ValueError, TypeError):
        raise HTTPException(401, 'Invalid or expired session')
    row = conn.execute('SELECT * FROM users WHERE id=? AND company_id=? AND active=1', (user_id, company_id)).fetchone()
    if not row:
        raise HTTPException(401, 'Account unavailable')
    return dict(row)


def roles(*allowed):
    def check(user=Depends(current_user)):
        if user['role'] not in allowed:
            raise HTTPException(403, 'Your role does not allow this action')
        return user
    return check


def audit(conn, user, action, entity, entity_id):
    conn.execute('INSERT INTO audit_logs(company_id,actor_id,action,entity_type,entity_id,created_at) VALUES(?,?,?,?,?,?)',
                 (user['company_id'], user['id'], action, entity, entity_id, now().isoformat()))


def create_app(database_path=None, secret=None):
    path = database_path or os.getenv('NUMERA_DATABASE_PATH', './numera-development.db')
    key = secret or os.getenv('NUMERA_JWT_SECRET')
    if not key or len(key) < 32:
        raise RuntimeError('Set a separate NUMERA_JWT_SECRET of at least 32 characters')
    # Refuse obvious reuse of the legacy database; use an explicit, fresh NUMERA file.
    if Path(path).name == 'erp.db':
        raise RuntimeError('NUMERA must use a separate development database')

    @asynccontextmanager
    async def lifespan(app):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = connection(app)
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()
        yield

    app = FastAPI(title='NUMERA ERP development', version='0.1.0', lifespan=lifespan)
    app.state.database_path = str(path)
    app.state.secret = key
    app.state.auth_attempts = {}
    app.state.auth_lock = threading.Lock()
    app.state.dummy_hash = password_hash(secrets.token_urlsafe(24))
    app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

    @app.middleware('http')
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def limit_auth(request):
        # Single-process development limiter. Distributed rate limiting is a hosted-release gate.
        identity = request.client.host if request.client else 'unknown'
        timestamp = time.monotonic()
        with app.state.auth_lock:
            for identity_key in list(app.state.auth_attempts):
                recent = [t for t in app.state.auth_attempts[identity_key] if timestamp-t < 60]
                if recent:
                    app.state.auth_attempts[identity_key] = recent
                else:
                    del app.state.auth_attempts[identity_key]
            attempts = app.state.auth_attempts.setdefault(identity, [])
            if len(attempts) >= 20:
                raise HTTPException(429, 'Too many attempts. Try again in a minute.')
            attempts.append(timestamp)

    def token(user):
        return {'access_token': jwt.encode({'sub': str(user['id']), 'company_id': user['company_id'],
                'aud': 'numera-development', 'iss': 'numera', 'exp': now()+timedelta(hours=2)}, key, algorithm='HS256'),
                'token_type': 'bearer'}

    @app.get('/')
    def home():
        return FileResponse(ROOT / 'static/index.html')

    @app.get('/app')
    def workspace():
        return FileResponse(ROOT / 'static/workspace.html')

    @app.get('/api/health')
    def health(conn=Depends(database)):
        conn.execute('SELECT 1')
        return {'status': 'ok', 'product': 'NUMERA ERP', 'version': '0.1.0', 'environment': 'development'}

    @app.post('/api/auth/register', status_code=201)
    def register(data: Registration, request: Request, conn=Depends(database)):
        limit_auth(request)
        stamp = now()
        hashed = password_hash(data.password)
        try:
            with conn:
                company_id = conn.execute('INSERT INTO companies(name,currency,language,created_at,trial_ends_at) VALUES(?,?,?,?,?)',
                    (data.company_name,data.currency,data.language,stamp.isoformat(),(stamp+timedelta(days=30)).isoformat())).lastrowid
                user_id = conn.execute('INSERT INTO users(company_id,email,name,password_hash,role) VALUES(?,?,?,?,?)',
                    (company_id,data.email,data.name,hashed,'owner')).lastrowid
                audit(conn, {'id':user_id,'company_id':company_id}, 'register', 'company', company_id)
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Email is already registered')
        return token({'id':user_id,'company_id':company_id})

    @app.post('/api/auth/login')
    def login(data: Login, request: Request, conn=Depends(database)):
        limit_auth(request)
        user = conn.execute('SELECT * FROM users WHERE email=? AND active=1', (data.email.strip().lower(),)).fetchone()
        valid = verify_password(data.password, user['password_hash'] if user else app.state.dummy_hash)
        if not user or not valid:
            raise HTTPException(401, 'Incorrect email or password')
        return token(user)

    @app.get('/api/auth/me')
    def me(user=Depends(current_user), conn=Depends(database)):
        company = dict(conn.execute('SELECT * FROM companies WHERE id=?', (user['company_id'],)).fetchone())
        return {'user': {k:user[k] for k in ('id','email','name','role')}, 'company':company,
                'subscription': {'status':'trial' if now() < datetime.fromisoformat(company['trial_ends_at']) else 'trial_expired',
                                 'billing_enabled':False}}

    @app.get('/api/users')
    def users(user=Depends(roles('owner')), conn=Depends(database)):
        return [dict(r) for r in conn.execute('SELECT id,name,email,role,active FROM users WHERE company_id=? ORDER BY id', (user['company_id'],))]

    @app.post('/api/users', status_code=201)
    def add_user(data: EmployeeIn, user=Depends(roles('owner')), conn=Depends(database)):
        try:
            with conn:
                identity = conn.execute('INSERT INTO users(company_id,email,name,password_hash,role) VALUES(?,?,?,?,?)',
                    (user['company_id'],data.email,data.name,password_hash(data.password),data.role)).lastrowid
                audit(conn,user,'create','user',identity)
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Email is already registered')
        return {'id':identity,'name':data.name,'email':data.email,'role':data.role}

    @app.get('/api/products')
    def products(user=Depends(current_user), conn=Depends(database)):
        return [dict(r) for r in conn.execute('SELECT id,sku,name,unit,sale_price,reorder_level FROM products WHERE company_id=? ORDER BY id DESC', (user['company_id'],))]

    @app.get('/api/products/{product_id}')
    def product(product_id: int, user=Depends(current_user), conn=Depends(database)):
        row = conn.execute('SELECT id,sku,name,unit,sale_price,reorder_level FROM products WHERE id=? AND company_id=?', (product_id,user['company_id'])).fetchone()
        if not row:
            raise HTTPException(404, 'Product not found')
        return dict(row)

    @app.post('/api/products', status_code=201)
    def add_product(data: ProductIn, user=Depends(roles('owner','inventory')), conn=Depends(database)):
        try:
            with conn:
                identity = conn.execute('INSERT INTO products(company_id,sku,name,unit,sale_price,reorder_level) VALUES(?,?,?,?,?,?)',
                    (user['company_id'],data.sku,data.name,data.unit,str(data.sale_price),str(data.reorder_level))).lastrowid
                audit(conn,user,'create','product',identity)
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'SKU already exists in your company')
        return {'id':identity, **data.model_dump(mode='json')}

    @app.get('/api/audit-logs')
    def audit_logs(user=Depends(roles('owner')), conn=Depends(database)):
        return [dict(r) for r in conn.execute('SELECT id,actor_id,action,entity_type,entity_id,created_at FROM audit_logs WHERE company_id=? ORDER BY id DESC LIMIT 200', (user['company_id'],))]

    return app
