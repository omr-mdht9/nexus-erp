from datetime import datetime, timedelta
from typing import Optional
import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Boolean, UniqueConstraint, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./erp.db')
engine = create_engine(DATABASE_URL, connect_args={'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()
SECRET = os.getenv('JWT_SECRET')
if not SECRET:
    raise RuntimeError('JWT_SECRET must be set before starting NEXUS ERP.')
pwd = CryptContext(schemes=['bcrypt'], deprecated='auto')
oauth2 = OAuth2PasswordBearer(tokenUrl='/api/auth/login')

class User(Base):
    __tablename__='users'; id=Column(Integer,primary_key=True); username=Column(String(80),unique=True,nullable=False); password_hash=Column(String(255),nullable=False); role=Column(String(30),default='admin'); active=Column(Boolean,default=True)
class Account(Base):
    __tablename__='accounts'; id=Column(Integer,primary_key=True); code=Column(String(30),unique=True,nullable=False); name=Column(String(160),nullable=False); type=Column(String(30),nullable=False); parent_id=Column(Integer,ForeignKey('accounts.id'))
class Warehouse(Base):
    __tablename__='warehouses'; id=Column(Integer,primary_key=True); code=Column(String(30),unique=True,nullable=False); name=Column(String(160),nullable=False)
class Product(Base):
    __tablename__='products'; id=Column(Integer,primary_key=True); sku=Column(String(60),unique=True,nullable=False); name=Column(String(160),nullable=False); category=Column(String(80),default='General'); unit=Column(String(30),default='KG'); cost=Column(Float,default=0); sale_price=Column(Float,default=0); reorder_level=Column(Float,default=0); active=Column(Boolean,default=True)
class Party(Base):
    __tablename__='parties'; id=Column(Integer,primary_key=True); code=Column(String(40),unique=True,nullable=False); name=Column(String(160),nullable=False); kind=Column(String(20),nullable=False); phone=Column(String(60),default=''); tax_id=Column(String(80),default='')
class Stock(Base):
    __tablename__='stock'; id=Column(Integer,primary_key=True); product_id=Column(Integer,ForeignKey('products.id'),nullable=False); warehouse_id=Column(Integer,ForeignKey('warehouses.id'),nullable=False); qty=Column(Float,default=0); __table_args__=(UniqueConstraint('product_id','warehouse_id',name='uq_stock'),)
class StockMove(Base):
    __tablename__='stock_moves'; id=Column(Integer,primary_key=True); product_id=Column(Integer,ForeignKey('products.id'),nullable=False); warehouse_id=Column(Integer,ForeignKey('warehouses.id'),nullable=False); qty=Column(Float,nullable=False); direction=Column(String(10),nullable=False); ref_type=Column(String(30),nullable=False); ref_no=Column(String(50),nullable=False); created_at=Column(DateTime,default=datetime.utcnow)
class Journal(Base):
    __tablename__='journals'; id=Column(Integer,primary_key=True); entry_no=Column(String(50),unique=True,nullable=False); description=Column(String(255),default=''); created_at=Column(DateTime,default=datetime.utcnow)
class JournalLine(Base):
    __tablename__='journal_lines'; id=Column(Integer,primary_key=True); journal_id=Column(Integer,ForeignKey('journals.id'),nullable=False); account_id=Column(Integer,ForeignKey('accounts.id'),nullable=False); debit=Column(Float,default=0); credit=Column(Float,default=0)
class Invoice(Base):
    __tablename__='invoices'; id=Column(Integer,primary_key=True); invoice_no=Column(String(50),unique=True,nullable=False); kind=Column(String(20),nullable=False); party_id=Column(Integer,ForeignKey('parties.id'),nullable=False); warehouse_id=Column(Integer,ForeignKey('warehouses.id'),nullable=False); subtotal=Column(Float,default=0); tax_rate=Column(Float,default=0); tax_amount=Column(Float,default=0); total=Column(Float,default=0); status=Column(String(20),default='posted'); created_at=Column(DateTime,default=datetime.utcnow)
class InvoiceLine(Base):
    __tablename__='invoice_lines'; id=Column(Integer,primary_key=True); invoice_id=Column(Integer,ForeignKey('invoices.id'),nullable=False); product_id=Column(Integer,ForeignKey('products.id'),nullable=False); qty=Column(Float,nullable=False); unit_price=Column(Float,nullable=False); line_total=Column(Float,default=0)
class BOM(Base):
    __tablename__='boms'; id=Column(Integer,primary_key=True); product_id=Column(Integer,ForeignKey('products.id'),nullable=False); quantity=Column(Float,default=1); active=Column(Boolean,default=True)
class BOMLine(Base):
    __tablename__='bom_lines'; id=Column(Integer,primary_key=True); bom_id=Column(Integer,ForeignKey('boms.id'),nullable=False); component_id=Column(Integer,ForeignKey('products.id'),nullable=False); qty=Column(Float,nullable=False)
class Production(Base):
    __tablename__='productions'; id=Column(Integer,primary_key=True); production_no=Column(String(50),unique=True,nullable=False); bom_id=Column(Integer,ForeignKey('boms.id'),nullable=False); warehouse_id=Column(Integer,ForeignKey('warehouses.id'),nullable=False); qty=Column(Float,nullable=False); status=Column(String(20),default='posted'); total_cost=Column(Float,default=0); created_at=Column(DateTime,default=datetime.utcnow)
class Payment(Base):
    __tablename__='payments'; id=Column(Integer,primary_key=True); payment_no=Column(String(50),unique=True,nullable=False); kind=Column(String(20),nullable=False); party_id=Column(Integer,ForeignKey('parties.id'),nullable=False); amount=Column(Float,nullable=False); account_id=Column(Integer,ForeignKey('accounts.id'),nullable=False); created_at=Column(DateTime,default=datetime.utcnow)
class PaymentAllocation(Base):
    __tablename__='payment_allocations'; id=Column(Integer,primary_key=True); payment_id=Column(Integer,ForeignKey('payments.id'),nullable=False); invoice_id=Column(Integer,ForeignKey('invoices.id'),nullable=False); amount=Column(Float,nullable=False); created_at=Column(DateTime,default=datetime.utcnow)
class AuditLog(Base):
    __tablename__='audit_logs'; id=Column(Integer,primary_key=True); actor_id=Column(Integer,ForeignKey('users.id'),nullable=False); action=Column(String(80),nullable=False); entity_type=Column(String(50),nullable=False); entity_id=Column(Integer,nullable=True); detail=Column(String(255),default='',nullable=False); created_at=Column(DateTime,default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def db():
    s=SessionLocal()
    try: yield s
    finally: s.close()

def seed(s:Session):
    if not s.query(User).first():
        admin_username = os.getenv('NEXUS_INITIAL_ADMIN_USERNAME')
        admin_password = os.getenv('NEXUS_INITIAL_ADMIN_PASSWORD')
        if not admin_username or not admin_password:
            raise RuntimeError('Set NEXUS_INITIAL_ADMIN_USERNAME and NEXUS_INITIAL_ADMIN_PASSWORD for the first start.')
        s.add(User(username=admin_username,password_hash=pwd.hash(admin_password),role='admin'))
    reset_password=os.getenv('NEXUS_ADMIN_RESET_PASSWORD')
    if reset_password:
        admin=s.query(User).filter_by(username=os.getenv('NEXUS_INITIAL_ADMIN_USERNAME','admin')).first()
        if admin: admin.password_hash=pwd.hash(reset_password)
    if not s.query(Account).first():
        rows=[('1000','Cash','asset'),('1100','Bank','asset'),('1200','Accounts Receivable','asset'),('1300','Inventory','asset'),('1350','Input VAT','asset'),('2000','Accounts Payable','liability'),('2100','Output VAT','liability'),('3000','Capital','equity'),('4000','Sales Revenue','revenue'),('4100','Other Revenue','revenue'),('5000','Cost of Goods Sold','expense'),('5100','Purchases','expense'),('5200','Operating Expenses','expense'),('5300','Production Variance','expense')]
        s.add_all([Account(code=c,name=n,type=t) for c,n,t in rows])
    if not s.query(Warehouse).first(): s.add(Warehouse(code='WH-01',name='Main Warehouse'))
    if not s.query(Product).first():
        s.add_all([Product(sku='RM-001',name='Raw Material 001',category='Raw Material',unit='KG',cost=100,reorder_level=100),Product(sku='RM-002',name='Raw Material 002',category='Raw Material',unit='KG',cost=60,reorder_level=50),Product(sku='FG-001',name='Finished Product 001',category='Finished Goods',unit='KG',cost=140,sale_price=220,reorder_level=50)])
    if not s.query(Party).first(): s.add_all([Party(code='SUP-001',name='Default Supplier',kind='supplier'),Party(code='CUS-001',name='Default Customer',kind='customer')])
    s.commit(); wh=s.query(Warehouse).first()
    for p in s.query(Product).all():
        if not s.query(Stock).filter_by(product_id=p.id,warehouse_id=wh.id).first(): s.add(Stock(product_id=p.id,warehouse_id=wh.id,qty=0))
    # Demo BOM: 2kg RM-001 + 1kg RM-002 -> 1kg FG-001
    fg=s.query(Product).filter_by(sku='FG-001').first(); rm1=s.query(Product).filter_by(sku='RM-001').first(); rm2=s.query(Product).filter_by(sku='RM-002').first()
    if fg and rm1 and rm2 and not s.query(BOM).first():
        b=BOM(product_id=fg.id,quantity=1); s.add(b); s.flush(); s.add_all([BOMLine(bom_id=b.id,component_id=rm1.id,qty=2),BOMLine(bom_id=b.id,component_id=rm2.id,qty=1)])
    s.commit()
with SessionLocal() as s: seed(s)

app=FastAPI(title='Nexus ERP API',version='0.2.0')
app.mount('/static',StaticFiles(directory='app/static'),name='static')
@app.get('/')
def home(): return FileResponse('app/static/index.html')

class TokenOut(BaseModel): access_token:str; token_type:str='bearer'
class UserCreateIn(BaseModel): username:str=Field(min_length=3,max_length=80); password:str=Field(min_length=8,max_length=72); role:str='inventory'
class UserUpdateIn(BaseModel): role:Optional[str]=None; active:Optional[bool]=None; password:Optional[str]=Field(default=None,min_length=8,max_length=72)
class ProductIn(BaseModel): sku:str; name:str; category:str='General'; unit:str='KG'; cost:float=0; sale_price:float=0; reorder_level:float=0
class PartyIn(BaseModel): code:str; name:str; kind:str; phone:str=''; tax_id:str=''
class WarehouseIn(BaseModel): code:str; name:str
class InvoiceLineIn(BaseModel): product_id:int; qty:float=Field(gt=0); unit_price:float=Field(ge=0)
class InvoiceIn(BaseModel): kind:str; party_id:int; warehouse_id:int; lines:list[InvoiceLineIn]; tax_rate:float=14; post_now:bool=True
class InvoiceWorkflowIn(BaseModel): action:str
class BOMLineIn(BaseModel): component_id:int; qty:float=Field(gt=0)
class BOMIn(BaseModel): product_id:int; quantity:float=Field(gt=0); lines:list[BOMLineIn]
class ProductionIn(BaseModel): bom_id:int; warehouse_id:int; qty:float=Field(gt=0)
class PaymentIn(BaseModel): kind:str; party_id:int; amount:float=Field(gt=0); account_code:str='1000'; invoice_id:Optional[int]=None

@app.post('/api/auth/login',response_model=TokenOut)
def login(form:OAuth2PasswordRequestForm=Depends(),s:Session=Depends(db)):
    u=s.query(User).filter_by(username=form.username).first()
    if not u or not u.active or not pwd.verify(form.password,u.password_hash): raise HTTPException(401,'Invalid credentials')
    return {'access_token':jwt.encode({'sub':u.username,'role':u.role,'exp':datetime.utcnow()+timedelta(hours=12)},SECRET,algorithm='HS256'),'token_type':'bearer'}
def current_user(token:str=Depends(oauth2),s:Session=Depends(db)):
    try: data=jwt.decode(token,SECRET,algorithms=['HS256']); username=data.get('sub')
    except JWTError: raise HTTPException(401,'Invalid token')
    u=s.query(User).filter_by(username=username).first()
    if not u or not u.active: raise HTTPException(401,'Account is inactive or unavailable')
    return u

@app.get('/api/auth/me')
def auth_me(user:User=Depends(current_user)):
    return {'username':user.username,'role':user.role}

def require_roles(*roles):
    def role_guard(user:User=Depends(current_user)):
        if user.role not in roles: raise HTTPException(403,'Insufficient permission')
        return user
    return role_guard

def audit(s:Session, actor:User, action:str, entity_type:str, entity_id:Optional[int]=None, detail:str=''):
    s.add(AuditLog(actor_id=actor.id,action=action,entity_type=entity_type,entity_id=entity_id,detail=detail))

USER_ROLES = {'admin','accountant','inventory'}

def validate_password(value:str):
    if len(value.encode('utf-8')) > 72: raise HTTPException(400,'Password must be 72 bytes or fewer')

def acct(s,code):
    a=s.query(Account).filter_by(code=code).first()
    if not a: raise HTTPException(500,f'Account {code} missing')
    return a

def journal(s,desc,lines):
    if round(sum(x[1] for x in lines)-sum(x[2] for x in lines),2)!=0: raise HTTPException(500,'Unbalanced journal entry')
    no='JE-'+datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:18]; j=Journal(entry_no=no,description=desc); s.add(j); s.flush()
    for a,d,c in lines: s.add(JournalLine(journal_id=j.id,account_id=a.id,debit=d,credit=c))
    return j

def stock_row(s,pid,wid):
    st=s.query(Stock).filter_by(product_id=pid,warehouse_id=wid).first()
    if not st: st=Stock(product_id=pid,warehouse_id=wid,qty=0); s.add(st); s.flush()
    return st

def move(s,pid,wid,qty,direction,ref_type,ref_no):
    st=stock_row(s,pid,wid)
    if direction=='IN': st.qty += qty
    else:
        if st.qty < qty: raise HTTPException(400,f'Insufficient stock for product {pid}: available {st.qty}, required {qty}')
        st.qty -= qty
    s.add(StockMove(product_id=pid,warehouse_id=wid,qty=qty,direction=direction,ref_type=ref_type,ref_no=ref_no))

@app.get('/api/users')
def list_users(_:User=Depends(require_roles('admin')),s:Session=Depends(db)):
    return [{'id':u.id,'username':u.username,'role':u.role,'active':u.active} for u in s.query(User).order_by(User.username)]

@app.post('/api/users')
def create_user(x:UserCreateIn,actor:User=Depends(require_roles('admin')),s:Session=Depends(db)):
    if x.role not in USER_ROLES: raise HTTPException(400,'Unknown role')
    validate_password(x.password)
    if s.query(User).filter_by(username=x.username).first(): raise HTTPException(400,'Username already exists')
    user=User(username=x.username,password_hash=pwd.hash(x.password),role=x.role,active=True)
    s.add(user); s.flush(); audit(s,actor,'create','user',user.id,f'Username {user.username}; role {user.role}'); s.commit()
    return {'id':user.id,'username':user.username,'role':user.role,'active':user.active}

@app.patch('/api/users/{user_id}')
def update_user(user_id:int,x:UserUpdateIn,actor:User=Depends(require_roles('admin')),s:Session=Depends(db)):
    user=s.get(User,user_id)
    if not user: raise HTTPException(404,'User not found')
    if x.role is not None:
        if x.role not in USER_ROLES: raise HTTPException(400,'Unknown role')
        if user.id == actor.id and x.role != 'admin': raise HTTPException(400,'You cannot remove your own administrator role')
        user.role=x.role
    if x.active is not None:
        if user.id == actor.id and not x.active: raise HTTPException(400,'You cannot deactivate your own account')
        user.active=x.active
    if x.password is not None:
        validate_password(x.password); user.password_hash=pwd.hash(x.password)
    audit(s,actor,'update','user',user.id,f'Username {user.username}; role {user.role}; active {user.active}')
    s.commit(); return {'id':user.id,'username':user.username,'role':user.role,'active':user.active}

@app.get('/api/dashboard')
def dashboard(_:User=Depends(current_user),s:Session=Depends(db)):
    products=s.query(Product).all(); stock=s.query(Stock).all(); inventory_value=sum(x.qty*next((p.cost for p in products if p.id==x.product_id),0) for x in stock)
    low=[]
    for p in products:
        q=sum(x.qty for x in stock if x.product_id==p.id)
        if q<=p.reorder_level: low.append({'sku':p.sku,'name':p.name,'qty':q,'reorder_level':p.reorder_level})
    sales=sum(i.total for i in s.query(Invoice).filter_by(kind='sale',status='posted').all()); purchases=sum(i.total for i in s.query(Invoice).filter_by(kind='purchase',status='posted').all())
    return {'inventory_value':round(inventory_value,2),'sales':round(sales,2),'purchases':round(purchases,2),'products':len(products),'low_stock':low,'customers':s.query(Party).filter_by(kind='customer').count(),'suppliers':s.query(Party).filter_by(kind='supplier').count(),'productions':s.query(Production).count(),'workflow_pending':s.query(Invoice).filter(Invoice.status.in_(['submitted','approved'])).count()}
@app.get('/api/accounts')
def accounts(_:User=Depends(current_user),s:Session=Depends(db)): return [{'id':a.id,'code':a.code,'name':a.name,'type':a.type} for a in s.query(Account).order_by(Account.code)]
@app.get('/api/products')
def products(_:User=Depends(current_user),s:Session=Depends(db)):
    out=[]
    for p in s.query(Product).order_by(Product.sku): out.append({'id':p.id,'sku':p.sku,'name':p.name,'category':p.category,'unit':p.unit,'cost':p.cost,'sale_price':p.sale_price,'qty':sum(x.qty for x in s.query(Stock).filter_by(product_id=p.id)),'reorder_level':p.reorder_level})
    return out
@app.post('/api/products')
def add_product(x:ProductIn,actor:User=Depends(require_roles('admin','inventory')),s:Session=Depends(db)):
    if s.query(Product).filter_by(sku=x.sku).first(): raise HTTPException(400,'SKU already exists')
    p=Product(**x.model_dump()); s.add(p); s.flush();
    for w in s.query(Warehouse).all(): s.add(Stock(product_id=p.id,warehouse_id=w.id,qty=0))
    audit(s,actor,'create','product',p.id,f'SKU {p.sku}')
    s.commit(); return {'id':p.id}
@app.get('/api/parties')
def parties(_:User=Depends(current_user),s:Session=Depends(db)): return [{'id':p.id,'code':p.code,'name':p.name,'kind':p.kind,'phone':p.phone,'tax_id':p.tax_id} for p in s.query(Party).order_by(Party.code)]
@app.post('/api/parties')
def add_party(x:PartyIn,actor:User=Depends(require_roles('admin','accountant')),s:Session=Depends(db)):
    if x.kind not in ('customer','supplier'): raise HTTPException(400,'kind must be customer or supplier')
    p=Party(**x.model_dump()); s.add(p); s.flush(); audit(s,actor,'create','party',p.id,f'Code {p.code}'); s.commit(); return {'id':p.id}
@app.get('/api/warehouses')
def warehouses(_:User=Depends(current_user),s:Session=Depends(db)): return [{'id':w.id,'code':w.code,'name':w.name} for w in s.query(Warehouse).order_by(Warehouse.code)]
@app.post('/api/warehouses')
def add_wh(x:WarehouseIn,actor:User=Depends(require_roles('admin','inventory')),s:Session=Depends(db)):
    w=Warehouse(**x.model_dump()); s.add(w); s.flush()
    for p in s.query(Product).all(): s.add(Stock(product_id=p.id,warehouse_id=w.id,qty=0))
    audit(s,actor,'create','warehouse',w.id,f'Code {w.code}')
    s.commit(); return {'id':w.id}

@app.get('/api/stock-moves')
def moves(_:User=Depends(current_user),s:Session=Depends(db)):
    rows=s.query(StockMove).order_by(StockMove.id.desc()).limit(150).all(); out=[]
    for m in rows:
        p=s.get(Product,m.product_id); w=s.get(Warehouse,m.warehouse_id); out.append({'id':m.id,'product':p.name if p else '?','warehouse':w.name if w else '?','qty':m.qty,'direction':m.direction,'ref_type':m.ref_type,'ref_no':m.ref_no,'created_at':m.created_at.isoformat()})
    return out

@app.post('/api/invoices')
def create_invoice(x:InvoiceIn,actor:User=Depends(require_roles('admin','accountant')),s:Session=Depends(db)):
    if x.kind not in ('purchase','sale'): raise HTTPException(400,'kind must be purchase or sale')
    party=s.get(Party,x.party_id); wh=s.get(Warehouse,x.warehouse_id)
    expected='supplier' if x.kind=='purchase' else 'customer'
    if not party or not wh or party.kind!=expected: raise HTTPException(400,'Invalid party or warehouse')
    subtotal=sum(l.qty*l.unit_price for l in x.lines); tax=subtotal*(x.tax_rate/100); total=subtotal+tax
    prefix='PINV' if x.kind=='purchase' else 'SINV'; no=f'{prefix}-{datetime.utcnow().strftime("%Y%m%d%H%M%S%f")[:17]}'
    inv=Invoice(invoice_no=no,kind=x.kind,party_id=x.party_id,warehouse_id=x.warehouse_id,subtotal=subtotal,tax_rate=x.tax_rate,tax_amount=tax,total=total,status='posted' if x.post_now else 'draft'); s.add(inv); s.flush()
    if not x.post_now:
        for l in x.lines:
            if not s.get(Product,l.product_id): raise HTTPException(404,'Product not found')
            s.add(InvoiceLine(invoice_id=inv.id,product_id=l.product_id,qty=l.qty,unit_price=l.unit_price,line_total=l.qty*l.unit_price))
        audit(s,actor,'create_draft','invoice',inv.id,f'Invoice {inv.invoice_no}; {inv.kind}')
        s.commit(); return {'id':inv.id,'invoice_no':inv.invoice_no,'total':total,'tax':tax,'status':inv.status}
    inv_acct=acct(s,'1300'); party_acct=acct(s,'2000' if x.kind=='purchase' else '1200'); vat=acct(s,'1350' if x.kind=='purchase' else '2100'); main=acct(s,'5100' if x.kind=='purchase' else '4000')
    lines=[]; cogs=0
    for l in x.lines:
        p=s.get(Product,l.product_id)
        if not p: raise HTTPException(404,'Product not found')
        lines.append(InvoiceLine(invoice_id=inv.id,product_id=p.id,qty=l.qty,unit_price=l.unit_price,line_total=l.qty*l.unit_price))
        if x.kind=='purchase': move(s,p.id,wh.id,l.qty,'IN','purchase',no)
        else:
            move(s,p.id,wh.id,l.qty,'OUT','sale',no); cogs += l.qty*p.cost
        s.add(lines[-1])
    if x.kind=='purchase':
        j=journal(s,f'Purchase {no}',[(inv_acct,subtotal,0),(vat,tax,0),(party_acct,0,total)])
    else:
        j=journal(s,f'Sale {no}',[(party_acct,total,0),(main,0,subtotal),(vat,0,tax),(acct(s,'5000'),cogs,0),(inv_acct,0,cogs)])
    audit(s,actor,'post','invoice',inv.id,f'{x.kind} {no}')
    s.commit(); return {'invoice_no':no,'subtotal':subtotal,'tax':tax,'total':total,'journal_no':j.entry_no}

@app.post('/api/invoices/{invoice_id}/workflow')
def invoice_workflow(invoice_id:int,x:InvoiceWorkflowIn,actor:User=Depends(require_roles('admin','accountant')),s:Session=Depends(db)):
    inv=s.get(Invoice,invoice_id)
    if not inv: raise HTTPException(404,'Invoice not found')
    allowed={'draft':{'submit':'submitted','cancel':'cancelled'},'submitted':{'approve':'approved','return':'draft','cancel':'cancelled'},'approved':{'return':'draft','cancel':'cancelled'}}
    target=allowed.get(inv.status,{}).get(x.action)
    if not target: raise HTTPException(400,f'Action {x.action} is not allowed while invoice is {inv.status}')
    inv.status=target; audit(s,actor,'workflow_'+x.action,'invoice',inv.id,f'Invoice {inv.invoice_no}; status {target}'); s.commit()
    return {'id':inv.id,'invoice_no':inv.invoice_no,'status':inv.status}

@app.post('/api/invoices/{invoice_id}/post')
def post_approved_invoice(invoice_id:int,actor:User=Depends(require_roles('admin','accountant')),s:Session=Depends(db)):
    inv=s.get(Invoice,invoice_id)
    if not inv: raise HTTPException(404,'Invoice not found')
    if inv.status!='approved': raise HTTPException(400,'Only an approved invoice can be posted')
    wh=s.get(Warehouse,inv.warehouse_id)
    inv_acct=acct(s,'1300'); party_acct=acct(s,'2000' if inv.kind=='purchase' else '1200'); vat=acct(s,'1350' if inv.kind=='purchase' else '2100'); main=acct(s,'5100' if inv.kind=='purchase' else '4000')
    cogs=0
    for line in s.query(InvoiceLine).filter_by(invoice_id=inv.id):
        product=s.get(Product,line.product_id)
        if not product: raise HTTPException(404,'Product not found')
        if inv.kind=='purchase': move(s,product.id,wh.id,line.qty,'IN','purchase',inv.invoice_no)
        else:
            move(s,product.id,wh.id,line.qty,'OUT','sale',inv.invoice_no); cogs += line.qty*product.cost
    if inv.kind=='purchase':
        j=journal(s,f'Purchase {inv.invoice_no}',[(inv_acct,inv.subtotal,0),(vat,inv.tax_amount,0),(party_acct,0,inv.total)])
    else:
        j=journal(s,f'Sale {inv.invoice_no}',[(party_acct,inv.total,0),(main,0,inv.subtotal),(vat,0,inv.tax_amount),(acct(s,'5000'),cogs,0),(inv_acct,0,cogs)])
    inv.status='posted'; audit(s,actor,'post','invoice',inv.id,f'{inv.kind} {inv.invoice_no}; journal {j.entry_no}')
    s.commit(); return {'invoice_no':inv.invoice_no,'status':inv.status,'journal_no':j.entry_no}

@app.get('/api/invoices')
def invoices(_:User=Depends(current_user),s:Session=Depends(db)):
    out=[]
    for i in s.query(Invoice).order_by(Invoice.id.desc()).limit(100):
        p=s.get(Party,i.party_id); out.append({'id':i.id,'invoice_no':i.invoice_no,'kind':i.kind,'party':p.name if p else '?','subtotal':i.subtotal,'tax':i.tax_amount,'total':i.total,'status':i.status,'created_at':i.created_at.isoformat()})
    return out

@app.get('/api/boms')
def boms(_:User=Depends(current_user),s:Session=Depends(db)):
    out=[]
    for b in s.query(BOM).filter_by(active=True):
        p=s.get(Product,b.product_id); ls=[]
        for l in s.query(BOMLine).filter_by(bom_id=b.id):
            cp=s.get(Product,l.component_id); ls.append({'product_id':l.component_id,'sku':cp.sku,'name':cp.name,'qty':l.qty})
        out.append({'id':b.id,'product_id':b.product_id,'product':p.name,'sku':p.sku,'quantity':b.quantity,'lines':ls})
    return out
@app.post('/api/boms')
def create_bom(x:BOMIn,actor:User=Depends(require_roles('admin','inventory')),s:Session=Depends(db)):
    if not s.get(Product,x.product_id): raise HTTPException(404,'Finished product not found')
    b=BOM(product_id=x.product_id,quantity=x.quantity); s.add(b); s.flush()
    for l in x.lines:
        if not s.get(Product,l.component_id): raise HTTPException(404,'Component not found')
        s.add(BOMLine(bom_id=b.id,component_id=l.component_id,qty=l.qty))
    audit(s,actor,'create','bom',b.id,f'Product {b.product_id}')
    s.commit(); return {'id':b.id}
@app.get('/api/productions')
def productions(_:User=Depends(current_user),s:Session=Depends(db)):
    out=[]
    for p in s.query(Production).order_by(Production.id.desc()).limit(100):
        b=s.get(BOM,p.bom_id); fg=s.get(Product,b.product_id); w=s.get(Warehouse,p.warehouse_id); out.append({'production_no':p.production_no,'product':fg.name,'sku':fg.sku,'qty':p.qty,'warehouse':w.name,'total_cost':p.total_cost,'status':p.status,'created_at':p.created_at.isoformat()})
    return out
@app.post('/api/productions')
def create_production(x:ProductionIn,actor:User=Depends(require_roles('admin','inventory')),s:Session=Depends(db)):
    b=s.get(BOM,x.bom_id); w=s.get(Warehouse,x.warehouse_id)
    if not b or not w: raise HTTPException(404,'BOM or warehouse not found')
    fg=s.get(Product,b.product_id); no='PROD-'+datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:18]
    factor=x.qty/b.quantity; total=0
    requirements=[]
    for l in s.query(BOMLine).filter_by(bom_id=b.id):
        cp=s.get(Product,l.component_id); req=l.qty*factor; st=stock_row(s,cp.id,w.id)
        if st.qty<req: raise HTTPException(400,f'Insufficient {cp.name}: available {st.qty}, required {req}')
        requirements.append((cp,req)); total += req*cp.cost
    for cp,req in requirements: move(s,cp.id,w.id,req,'OUT','production',no)
    move(s,fg.id,w.id,x.qty,'IN','production',no)
    fg.cost = total/x.qty if x.qty else fg.cost
    p=Production(production_no=no,bom_id=b.id,warehouse_id=w.id,qty=x.qty,total_cost=total); s.add(p); s.flush()
    lines=[(acct(s,'1300'),total,0),(acct(s,'1300'),0,total)]
    j=journal(s,f'Production {no}',lines); audit(s,actor,'post','production',p.id,no); s.commit(); return {'production_no':no,'total_cost':total,'unit_cost':total/x.qty}

@app.get('/api/payments')
def payments(_:User=Depends(require_roles('admin','accountant')),s:Session=Depends(db)):
    out=[]
    for payment in s.query(Payment).order_by(Payment.id.desc()).limit(100):
        party=s.get(Party,payment.party_id); account=s.get(Account,payment.account_id)
        out.append({'id':payment.id,'payment_no':payment.payment_no,'kind':payment.kind,'party':party.name if party else '?','amount':payment.amount,'account':account.code+' - '+account.name if account else '?','created_at':payment.created_at.isoformat()})
    return out

@app.post('/api/payments')
def create_payment(x:PaymentIn,actor:User=Depends(require_roles('admin','accountant')),s:Session=Depends(db)):
    if x.kind not in ('receipt','payment'): raise HTTPException(400,'kind must be receipt or payment')
    party=s.get(Party,x.party_id); bank=acct(s,x.account_code)
    if not party or (x.kind=='receipt' and party.kind!='customer') or (x.kind=='payment' and party.kind!='supplier'): raise HTTPException(400,'Invalid party for payment')
    invoice_kind='sale' if x.kind=='receipt' else 'purchase'
    posted_total=sum(inv.total for inv in s.query(Invoice).filter_by(party_id=party.id,kind=invoice_kind,status='posted'))
    prior_paid=sum(p.amount for p in s.query(Payment).filter_by(party_id=party.id,kind=x.kind))
    if x.amount > round(posted_total-prior_paid,2)+0.0001: raise HTTPException(400,'Payment exceeds the party open balance; allocate or reconcile earlier payments first')
    no='PAY-'+datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:18]
    party_acct=acct(s,'1200' if x.kind=='receipt' else '2000')
    j=journal(s,f'{x.kind.title()} {no}',[(bank,x.amount,0),(party_acct,0,x.amount)] if x.kind=='receipt' else [(party_acct,x.amount,0),(bank,0,x.amount)])
    payment=Payment(payment_no=no,kind=x.kind,party_id=party.id,amount=x.amount,account_id=bank.id); s.add(payment); s.flush()
    if x.invoice_id is not None:
        inv=s.get(Invoice,x.invoice_id); expected='sale' if x.kind=='receipt' else 'purchase'
        if not inv or inv.status!='posted' or inv.party_id!=party.id or inv.kind!=expected: raise HTTPException(400,'Invalid invoice for this payment')
        allocated=sum(a.amount for a in s.query(PaymentAllocation).filter_by(invoice_id=inv.id))
        if x.amount>round(inv.total-allocated,2)+0.0001: raise HTTPException(400,'Payment exceeds invoice balance')
        s.add(PaymentAllocation(payment_id=payment.id,invoice_id=inv.id,amount=x.amount))
    audit(s,actor,'post','payment',payment.id,no); s.commit(); return {'payment_no':no,'journal_no':j.entry_no}

@app.get('/api/reconciliation')
def reconciliation(_:User=Depends(require_roles('admin','accountant')),s:Session=Depends(db)):
    rows=[]
    for inv in s.query(Invoice).filter_by(status='posted').order_by(Invoice.id.desc()).limit(100):
        party=s.get(Party,inv.party_id)
        allocations=s.query(PaymentAllocation).filter_by(invoice_id=inv.id).all()
        allocated=round(sum(a.amount for a in allocations),2)
        details=[]
        for allocation in allocations:
            payment=s.get(Payment,allocation.payment_id)
            if payment: details.append({'payment_no':payment.payment_no,'amount':allocation.amount,'created_at':payment.created_at.isoformat()})
        rows.append({'invoice_no':inv.invoice_no,'kind':inv.kind,'party':party.name if party else '?','total':inv.total,'allocated':allocated,'balance':round(inv.total-allocated,2),'status':'settled' if abs(inv.total-allocated)<0.0001 else 'open','payments':details})
    return rows

@app.get('/api/open-invoices')
def open_invoices(kind:str,party_id:int,_:User=Depends(require_roles('admin','accountant')),s:Session=Depends(db)):
    expected='sale' if kind=='receipt' else 'purchase'; out=[]
    for inv in s.query(Invoice).filter_by(status='posted',party_id=party_id,kind=expected):
        allocated=sum(a.amount for a in s.query(PaymentAllocation).filter_by(invoice_id=inv.id)); balance=round(inv.total-allocated,2)
        if balance>0.0001: out.append({'id':inv.id,'invoice_no':inv.invoice_no,'balance':balance})
    return out

@app.post('/api/payments/{payment_id}/void')
def void_payment(payment_id:int,actor:User=Depends(require_roles('admin','accountant')),s:Session=Depends(db)):
    payment=s.get(Payment,payment_id)
    if not payment: raise HTTPException(404,'Payment not found')
    payment_no=payment.payment_no
    bank=s.get(Account,payment.account_id); party_acct=acct(s,'1200' if payment.kind=='receipt' else '2000')
    lines=[(party_acct,payment.amount,0),(bank,0,payment.amount)] if payment.kind=='receipt' else [(bank,payment.amount,0),(party_acct,0,payment.amount)]
    j=journal(s,f'Void {payment.kind.title()} {payment.payment_no}',lines)
    for allocation in s.query(PaymentAllocation).filter_by(payment_id=payment.id).all(): s.delete(allocation)
    s.flush()
    audit(s,actor,'void','payment',payment.id,f'{payment_no}; reversal {j.entry_no}')
    s.delete(payment); s.commit(); return {'payment_no':payment_no,'journal_no':j.entry_no,'status':'voided'}


@app.post('/api/payments/by-reference/{payment_no}/void')
def void_payment_by_reference(payment_no:str,actor:User=Depends(require_roles('admin','accountant')),s:Session=Depends(db)):
    payment=s.query(Payment).filter_by(payment_no=payment_no).first()
    if not payment: raise HTTPException(404,'Payment not found')
    payment_no=payment.payment_no
    bank=s.get(Account,payment.account_id); party_acct=acct(s,'1200' if payment.kind=='receipt' else '2000')
    lines=[(party_acct,payment.amount,0),(bank,0,payment.amount)] if payment.kind=='receipt' else [(bank,payment.amount,0),(party_acct,0,payment.amount)]
    j=journal(s,f'Void {payment.kind.title()} {payment.payment_no}',lines)
    for allocation in s.query(PaymentAllocation).filter_by(payment_id=payment.id).all(): s.delete(allocation)
    s.flush()
    audit(s,actor,'void','payment',payment.id,f'{payment_no}; reversal {j.entry_no}')
    s.delete(payment); s.commit(); return {'payment_no':payment_no,'journal_no':j.entry_no,'status':'voided'}

@app.get('/api/audit-logs')
def audit_logs(_:User=Depends(require_roles('admin')),s:Session=Depends(db)):
    rows=s.query(AuditLog).order_by(AuditLog.id.desc()).limit(200).all()
    return [{'id':r.id,'actor_id':r.actor_id,'action':r.action,'entity_type':r.entity_type,'entity_id':r.entity_id,'detail':r.detail,'created_at':r.created_at.isoformat()} for r in rows]

@app.get('/api/journals')
def journals(_:User=Depends(current_user),s:Session=Depends(db)):
    out=[]
    for j in s.query(Journal).order_by(Journal.id.desc()).limit(100):
        ls=[]
        for l in s.query(JournalLine).filter_by(journal_id=j.id):
            a=s.get(Account,l.account_id); ls.append({'account':a.code+' - '+a.name,'debit':l.debit,'credit':l.credit})
        out.append({'entry_no':j.entry_no,'description':j.description,'created_at':j.created_at.isoformat(),'lines':ls})
    return out
@app.get('/api/trial-balance')
def trial_balance(_:User=Depends(current_user),s:Session=Depends(db)):
    rows=[]
    for a in s.query(Account).order_by(Account.code):
        d=sum(x.debit for x in s.query(JournalLine).filter_by(account_id=a.id)); c=sum(x.credit for x in s.query(JournalLine).filter_by(account_id=a.id))
        if d or c: rows.append({'code':a.code,'name':a.name,'debit':round(d,2),'credit':round(c,2),'balance':round(d-c,2)})
    return rows
@app.get('/api/health')
def health(s:Session=Depends(db)):
    try:
        s.execute(text('SELECT 1'))
    except Exception:
        raise HTTPException(503, 'Database is unavailable')
    return {'status':'ok','database':'connected','version':'0.2.0'}
