"""Supplier records and draft purchases with atomic, single goods receipt."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import json
import sqlite3
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from numera.inventory import quantity_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS suppliers (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 code TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL, email TEXT NOT NULL,
 tax_id TEXT NOT NULL, UNIQUE(company_id,code), UNIQUE(company_id,id));
CREATE TABLE IF NOT EXISTS purchases (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 supplier_id INTEGER NOT NULL, supplier_reference TEXT NOT NULL,
 document_date TEXT NOT NULL, due_date TEXT NOT NULL, notes TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('draft','received','cancelled')),
 subtotal_minor INTEGER NOT NULL, tax_minor INTEGER NOT NULL, total_minor INTEGER NOT NULL,
 request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
 created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
 received_by INTEGER REFERENCES users(id), received_at TEXT,
 FOREIGN KEY(company_id,supplier_id) REFERENCES suppliers(company_id,id),
 UNIQUE(company_id,request_key), UNIQUE(company_id,id));
CREATE UNIQUE INDEX IF NOT EXISTS purchase_supplier_reference ON purchases(company_id,supplier_id,supplier_reference) WHERE supplier_reference<>'';
CREATE TABLE IF NOT EXISTS purchase_lines (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 purchase_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
 quantity_milli INTEGER NOT NULL, unit_price_minor INTEGER NOT NULL,
 tax_rate TEXT NOT NULL, subtotal_minor INTEGER NOT NULL, tax_minor INTEGER NOT NULL,
 FOREIGN KEY(company_id,purchase_id) REFERENCES purchases(company_id,id),
 FOREIGN KEY(company_id,product_id) REFERENCES products(company_id,id),
 UNIQUE(purchase_id,product_id));
CREATE TABLE IF NOT EXISTS purchase_receipt_links (
 company_id INTEGER NOT NULL, purchase_line_id INTEGER NOT NULL REFERENCES purchase_lines(id),
 movement_id INTEGER NOT NULL REFERENCES stock_movements(id),
 PRIMARY KEY(purchase_line_id), UNIQUE(movement_id));
"""

class SupplierIn(BaseModel):
    code: str = Field(min_length=1,max_length=40)
    name: str = Field(min_length=2,max_length=160)
    phone: str = Field(default='',max_length=60)
    email: str = Field(default='',max_length=254)
    tax_id: str = Field(default='',max_length=80)

    @field_validator('code','name')
    @classmethod
    def trim(cls,value):
        value=value.strip()
        if not value: raise ValueError('Cannot be blank')
        return value

    @field_validator('name')
    @classmethod
    def name_length(cls,value):
        if len(value)<2: raise ValueError('Enter a name of at least two characters')
        return value

class PurchaseLineIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0,max_digits=14,decimal_places=3)
    unit_price: Decimal = Field(ge=0,max_digits=12,decimal_places=2)
    tax_rate: Decimal = Field(default=Decimal('0'),ge=0,le=100,decimal_places=2)

class PurchaseIn(BaseModel):
    supplier_id: int = Field(gt=0)
    supplier_reference: str = Field(default='',max_length=100)
    document_date: date
    due_date: date
    notes: str = Field(default='',max_length=500)
    request_key: str = Field(min_length=16,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')
    lines: list[PurchaseLineIn] = Field(min_length=1,max_length=100)

    @field_validator('supplier_reference')
    @classmethod
    def trim_reference(cls,value): return value.strip()

    @model_validator(mode='after')
    def dates_and_lines(self):
        if self.due_date<self.document_date: raise ValueError('Due date must be on or after document date')
        if len({line.product_id for line in self.lines})!=len(self.lines): raise ValueError('Use one line per product')
        return self


def minor(value): return int((value*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def money(value): return format(Decimal(value)/100,'.2f')


def purchase_out(conn,row):
    supplier=conn.execute('SELECT name FROM suppliers WHERE id=? AND company_id=?',(row['supplier_id'],row['company_id'])).fetchone()
    company=conn.execute('SELECT currency FROM companies WHERE id=?',(row['company_id'],)).fetchone()
    lines=conn.execute('''SELECT l.*,p.sku,p.name,p.unit FROM purchase_lines l JOIN products p
        ON p.id=l.product_id AND p.company_id=l.company_id WHERE l.purchase_id=? AND l.company_id=? ORDER BY l.id''',(row['id'],row['company_id']))
    return {'id':row['id'],'number':f"PUR-{row['id']:06d}",'supplier_id':row['supplier_id'],'supplier':supplier['name'],
        'supplier_reference':row['supplier_reference'],'document_date':row['document_date'],'due_date':row['due_date'],
        'notes':row['notes'],'status':row['status'],'currency':company['currency'],
        'subtotal':money(row['subtotal_minor']),'tax':money(row['tax_minor']),'total':money(row['total_minor']),
        'created_at':row['created_at'],'received_at':row['received_at'],
        'lines':[{'id':line['id'],'product_id':line['product_id'],'sku':line['sku'],'name':line['name'],'unit':line['unit'],
            'quantity':quantity_text(line['quantity_milli']),'unit_price':money(line['unit_price_minor']),
            'tax_rate':line['tax_rate'],'subtotal':money(line['subtotal_minor']),'tax':money(line['tax_minor'])} for line in lines]}


def build_router(database,current_user,roles,audit,now):
    router=APIRouter(tags=['Purchases'])

    @router.get('/api/suppliers')
    def suppliers(user=Depends(current_user),conn=Depends(database)):
        return [dict(row) for row in conn.execute('SELECT id,code,name,phone,email,tax_id FROM suppliers WHERE company_id=? ORDER BY name',(user['company_id'],))]

    @router.post('/api/suppliers',status_code=201)
    def add_supplier(data:SupplierIn,user=Depends(roles('owner','accountant')),conn=Depends(database)):
        try:
            with conn:
                identity=conn.execute('INSERT INTO suppliers(company_id,code,name,phone,email,tax_id) VALUES(?,?,?,?,?,?)',
                    (user['company_id'],data.code,data.name,data.phone,data.email,data.tax_id)).lastrowid
                audit(conn,user,'create','supplier',identity)
        except sqlite3.IntegrityError: raise HTTPException(409,'Supplier code already exists in your company')
        return {'id':identity,**data.model_dump()}

    @router.get('/api/purchases')
    def purchases(user=Depends(roles('owner','accountant')),conn=Depends(database)):
        return [purchase_out(conn,row) for row in conn.execute('SELECT * FROM purchases WHERE company_id=? ORDER BY id DESC LIMIT 200',(user['company_id'],))]

    @router.get('/api/purchases/receiving')
    def receiving(user=Depends(roles('owner','inventory')),conn=Depends(database)):
        # Warehouse staff receive quantities without access to supplier prices.
        rows=conn.execute('SELECT * FROM purchases WHERE company_id=? AND status=? ORDER BY id DESC LIMIT 200',(user['company_id'],'draft'))
        result=[]
        for row in rows:
            data=purchase_out(conn,row)
            result.append({key:data[key] for key in ('id','number','supplier','supplier_reference','document_date','status')} | {
                'lines':[{key:line[key] for key in ('product_id','sku','name','unit','quantity')} for line in data['lines']]})
        return result

    @router.get('/api/purchases/{purchase_id}')
    def purchase(purchase_id:int,user=Depends(roles('owner','accountant')),conn=Depends(database)):
        row=conn.execute('SELECT * FROM purchases WHERE id=? AND company_id=?',(purchase_id,user['company_id'])).fetchone()
        if not row: raise HTTPException(404,'Purchase not found')
        return purchase_out(conn,row)

    @router.post('/api/purchases',status_code=201)
    def add_purchase(data:PurchaseIn,user=Depends(roles('owner','accountant')),conn=Depends(database)):
        company=user['company_id']
        payload=data.model_dump(mode='json',exclude={'request_key'})
        # Normalize decimal forms so 1 and 1.000 are the same retried quantity.
        for line,original in zip(payload['lines'],data.lines):
            line.update(quantity=format(original.quantity,'.3f'),unit_price=format(original.unit_price,'.2f'),tax_rate=format(original.tax_rate,'.2f'))
        fingerprint=json.dumps(payload,sort_keys=True,separators=(',',':'))
        try:
            conn.execute('BEGIN IMMEDIATE')
            old=conn.execute('SELECT * FROM purchases WHERE company_id=? AND request_key=?',(company,data.request_key)).fetchone()
            if old:
                if old['fingerprint']!=fingerprint: raise HTTPException(409,'Request key already used for another purchase')
                result=purchase_out(conn,old); conn.rollback(); return {**result,'replayed':True}
            if not conn.execute('SELECT id FROM suppliers WHERE id=? AND company_id=?',(data.supplier_id,company)).fetchone():
                raise HTTPException(404,'Supplier not found')
            lines=[]
            for line in data.lines:
                if not conn.execute('SELECT id FROM products WHERE id=? AND company_id=?',(line.product_id,company)).fetchone():
                    raise HTTPException(404,'Product not found')
                subtotal=minor(line.quantity*line.unit_price)
                tax=minor(Decimal(subtotal)/100*line.tax_rate/100)
                lines.append((line,subtotal,tax))
            subtotal=sum(item[1] for item in lines); tax=sum(item[2] for item in lines)
            if subtotal+tax>99999999999999: raise HTTPException(422,'Purchase total exceeds supported limit')
            identity=conn.execute('''INSERT INTO purchases(company_id,supplier_id,supplier_reference,document_date,due_date,notes,
                status,subtotal_minor,tax_minor,total_minor,request_key,fingerprint,created_by,created_at)
                VALUES(?,?,?,?,?,?,'draft',?,?,?,?,?,?,?)''',
                (company,data.supplier_id,data.supplier_reference,data.document_date.isoformat(),data.due_date.isoformat(),data.notes,
                 subtotal,tax,subtotal+tax,data.request_key,fingerprint,user['id'],now().isoformat())).lastrowid
            for line,sub,line_tax in lines:
                conn.execute('''INSERT INTO purchase_lines(company_id,purchase_id,product_id,quantity_milli,unit_price_minor,tax_rate,subtotal_minor,tax_minor)
                    VALUES(?,?,?,?,?,?,?,?)''',(company,identity,line.product_id,int(line.quantity*1000),minor(line.unit_price),str(line.tax_rate),sub,line_tax))
            audit(conn,user,'create','purchase',identity)
            row=conn.execute('SELECT * FROM purchases WHERE id=?',(identity,)).fetchone()
            result=purchase_out(conn,row); conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback(); raise HTTPException(409,'Supplier reference already exists for this supplier')
        except Exception: conn.rollback(); raise
        return {**result,'replayed':False}

    @router.post('/api/purchases/{purchase_id}/receive')
    def receive(purchase_id:int,user=Depends(roles('owner','inventory')),conn=Depends(database)):
        company=user['company_id']
        try:
            conn.execute('BEGIN IMMEDIATE')
            purchase=conn.execute('SELECT * FROM purchases WHERE id=? AND company_id=?',(purchase_id,company)).fetchone()
            if not purchase: raise HTTPException(404,'Purchase not found')
            if purchase['status']=='cancelled': raise HTTPException(409,'Cancelled purchase cannot be received')
            if purchase['status']=='received':
                conn.rollback(); return {'id':purchase_id,'status':'received','replayed':True}
            lines=conn.execute('SELECT * FROM purchase_lines WHERE purchase_id=? AND company_id=?',(purchase_id,company)).fetchall()
            for line in lines:
                balance=conn.execute('SELECT COALESCE(SUM(delta_milli),0) FROM stock_movements WHERE company_id=? AND product_id=?',(company,line['product_id'])).fetchone()[0]
                if balance+line['quantity_milli']>99999999999999: raise HTTPException(422,'Receiving would exceed the stock quantity limit')
                movement=conn.execute('''INSERT INTO stock_movements(company_id,product_id,kind,quantity_milli,delta_milli,reason,request_key,actor_id,created_at)
                    VALUES(?,?,'receipt',?,?,?,?,?,?)''',(company,line['product_id'],line['quantity_milli'],line['quantity_milli'],
                    f'Goods receipt PUR-{purchase_id:06d}',f'sys_purchase_{purchase_id}_line_{line["id"]}',user['id'],now().isoformat())).lastrowid
                conn.execute('INSERT INTO purchase_receipt_links(company_id,purchase_line_id,movement_id) VALUES(?,?,?)',(company,line['id'],movement))
                audit(conn,user,'post','stock_movement',movement)
            conn.execute("UPDATE purchases SET status='received',received_by=?,received_at=? WHERE id=? AND company_id=?",(user['id'],now().isoformat(),purchase_id,company))
            audit(conn,user,'receive','purchase',purchase_id)
            conn.commit()
        except Exception: conn.rollback(); raise
        return {'id':purchase_id,'status':'received','replayed':False}

    @router.post('/api/purchases/{purchase_id}/cancel')
    def cancel(purchase_id:int,user=Depends(roles('owner','accountant')),conn=Depends(database)):
        try:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM purchases WHERE id=? AND company_id=?',(purchase_id,user['company_id'])).fetchone()
            if not row: raise HTTPException(404,'Purchase not found')
            if row['status']=='received': raise HTTPException(409,'Received purchases require a return workflow; cancellation is not allowed')
            if row['status']!='cancelled':
                conn.execute("UPDATE purchases SET status='cancelled' WHERE id=? AND company_id=?",(purchase_id,user['company_id']))
                audit(conn,user,'cancel','purchase',purchase_id)
            conn.commit()
        except Exception: conn.rollback(); raise
        return {'id':purchase_id,'status':'cancelled'}

    return router
