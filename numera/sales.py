"""Customer records and sales drafts with atomic stock deductions."""
from datetime import date
from decimal import Decimal
import json
import sqlite3
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from numera.purchases import SupplierIn, PurchaseLineIn as SaleLineIn, minor, money
from numera.inventory import quantity_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 code TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL, email TEXT NOT NULL,
 tax_id TEXT NOT NULL, UNIQUE(company_id,code), UNIQUE(company_id,id));
CREATE TABLE IF NOT EXISTS sales (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 customer_id INTEGER NOT NULL, customer_reference TEXT NOT NULL,
 document_date TEXT NOT NULL, due_date TEXT NOT NULL, notes TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('draft','posted','cancelled')),
 subtotal_minor INTEGER NOT NULL, tax_minor INTEGER NOT NULL, total_minor INTEGER NOT NULL,
 request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
 created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
 posted_by INTEGER REFERENCES users(id), posted_at TEXT,
 FOREIGN KEY(company_id,customer_id) REFERENCES customers(company_id,id),
 UNIQUE(company_id,request_key), UNIQUE(company_id,id));
CREATE UNIQUE INDEX IF NOT EXISTS sale_customer_reference ON sales(company_id,customer_id,customer_reference) WHERE customer_reference<>'';
CREATE TABLE IF NOT EXISTS sale_lines (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 sale_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
 quantity_milli INTEGER NOT NULL, unit_price_minor INTEGER NOT NULL,
 tax_rate TEXT NOT NULL, subtotal_minor INTEGER NOT NULL, tax_minor INTEGER NOT NULL,
 FOREIGN KEY(company_id,sale_id) REFERENCES sales(company_id,id),
 FOREIGN KEY(company_id,product_id) REFERENCES products(company_id,id), UNIQUE(sale_id,product_id));
CREATE TABLE IF NOT EXISTS sale_stock_links (
 company_id INTEGER NOT NULL, sale_line_id INTEGER NOT NULL REFERENCES sale_lines(id),
 movement_id INTEGER NOT NULL REFERENCES stock_movements(id),
 PRIMARY KEY(sale_line_id), UNIQUE(movement_id));
"""

class CustomerIn(SupplierIn):
    """Customer contacts use the same validated contact fields as suppliers."""


class SaleIn(BaseModel):
    customer_id: int = Field(gt=0)
    customer_reference: str = Field(default='',max_length=100)
    document_date: date
    due_date: date
    notes: str = Field(default='',max_length=500)
    request_key: str = Field(min_length=16,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')
    lines: list[SaleLineIn] = Field(min_length=1,max_length=100)

    @field_validator('customer_reference')
    @classmethod
    def trim_reference(cls,value): return value.strip()

    @model_validator(mode='after')
    def validate_document(self):
        if self.due_date<self.document_date: raise ValueError('Due date must be on or after document date')
        if len({line.product_id for line in self.lines})!=len(self.lines): raise ValueError('Use one line per product')
        return self

def sale_out(conn,row):
    customer=conn.execute('SELECT name FROM customers WHERE id=? AND company_id=?',(row['customer_id'],row['company_id'])).fetchone()
    company=conn.execute('SELECT currency FROM companies WHERE id=?',(row['company_id'],)).fetchone()
    lines=conn.execute('''SELECT l.*,p.sku,p.name,p.unit FROM sale_lines l JOIN products p
        ON p.id=l.product_id AND p.company_id=l.company_id WHERE l.sale_id=? AND l.company_id=? ORDER BY l.id''',(row['id'],row['company_id']))
    return {'id':row['id'],'number':f"SAL-{row['id']:06d}",'customer_id':row['customer_id'],'customer':customer['name'],
        'customer_reference':row['customer_reference'],'document_date':row['document_date'],'due_date':row['due_date'],
        'notes':row['notes'],'status':row['status'],'currency':company['currency'],
        'subtotal':money(row['subtotal_minor']),'tax':money(row['tax_minor']),'total':money(row['total_minor']),
        'created_at':row['created_at'],'posted_at':row['posted_at'],
        'lines':[{'id':line['id'],'product_id':line['product_id'],'sku':line['sku'],'name':line['name'],'unit':line['unit'],
            'quantity':quantity_text(line['quantity_milli']),'unit_price':money(line['unit_price_minor']),
            'tax_rate':line['tax_rate'],'subtotal':money(line['subtotal_minor']),'tax':money(line['tax_minor'])} for line in lines]}


def build_router(database,current_user,roles,audit,now):
    router=APIRouter(tags=['Sales'])

    @router.get('/api/customers')
    def customers(user=Depends(current_user),conn=Depends(database)):
        return [dict(row) for row in conn.execute('SELECT id,code,name,phone,email,tax_id FROM customers WHERE company_id=? ORDER BY name',(user['company_id'],))]

    @router.post('/api/customers',status_code=201)
    def add_customer(data:CustomerIn,user=Depends(roles('owner','accountant')),conn=Depends(database)):
        try:
            with conn:
                identity=conn.execute('INSERT INTO customers(company_id,code,name,phone,email,tax_id) VALUES(?,?,?,?,?,?)',
                    (user['company_id'],data.code,data.name,data.phone,data.email,data.tax_id)).lastrowid
                audit(conn,user,'create','customer',identity)
        except sqlite3.IntegrityError: raise HTTPException(409,'Customer code already exists in your company')
        return {'id':identity,**data.model_dump()}

    @router.get('/api/sales')
    def sales(user=Depends(roles('owner','accountant')),conn=Depends(database)):
        return [sale_out(conn,row) for row in conn.execute('SELECT * FROM sales WHERE company_id=? ORDER BY id DESC LIMIT 200',(user['company_id'],))]

    @router.get('/api/sales/{sale_id}')
    def sale(sale_id:int,user=Depends(roles('owner','accountant')),conn=Depends(database)):
        row=conn.execute('SELECT * FROM sales WHERE id=? AND company_id=?',(sale_id,user['company_id'])).fetchone()
        if not row: raise HTTPException(404,'Sale not found')
        return sale_out(conn,row)

    @router.post('/api/sales',status_code=201)
    def add_sale(data:SaleIn,user=Depends(roles('owner','accountant')),conn=Depends(database)):
        company=user['company_id']
        payload=data.model_dump(mode='json',exclude={'request_key'})
        # Normalize decimal forms so 1 and 1.000 are the same retried quantity.
        for line,original in zip(payload['lines'],data.lines):
            line.update(quantity=format(original.quantity,'.3f'),unit_price=format(original.unit_price,'.2f'),tax_rate=format(original.tax_rate,'.2f'))
        fingerprint=json.dumps(payload,sort_keys=True,separators=(',',':'))
        try:
            conn.execute('BEGIN IMMEDIATE')
            old=conn.execute('SELECT * FROM sales WHERE company_id=? AND request_key=?',(company,data.request_key)).fetchone()
            if old:
                if old['fingerprint']!=fingerprint: raise HTTPException(409,'Request key already used for another sale')
                result=sale_out(conn,old); conn.rollback(); return {**result,'replayed':True}
            if not conn.execute('SELECT id FROM customers WHERE id=? AND company_id=?',(data.customer_id,company)).fetchone():
                raise HTTPException(404,'Customer not found')
            lines=[]
            for line in data.lines:
                if not conn.execute('SELECT id FROM products WHERE id=? AND company_id=?',(line.product_id,company)).fetchone():
                    raise HTTPException(404,'Product not found')
                subtotal=minor(line.quantity*line.unit_price)
                tax=minor(Decimal(subtotal)/100*line.tax_rate/100)
                lines.append((line,subtotal,tax))
            subtotal=sum(item[1] for item in lines); tax=sum(item[2] for item in lines)
            if subtotal+tax>99999999999999: raise HTTPException(422,'Sale total exceeds supported limit')
            identity=conn.execute('''INSERT INTO sales(company_id,customer_id,customer_reference,document_date,due_date,notes,
                status,subtotal_minor,tax_minor,total_minor,request_key,fingerprint,created_by,created_at)
                VALUES(?,?,?,?,?,?,'draft',?,?,?,?,?,?,?)''',
                (company,data.customer_id,data.customer_reference,data.document_date.isoformat(),data.due_date.isoformat(),data.notes,
                 subtotal,tax,subtotal+tax,data.request_key,fingerprint,user['id'],now().isoformat())).lastrowid
            for line,sub,line_tax in lines:
                conn.execute('''INSERT INTO sale_lines(company_id,sale_id,product_id,quantity_milli,unit_price_minor,tax_rate,subtotal_minor,tax_minor)
                    VALUES(?,?,?,?,?,?,?,?)''',(company,identity,line.product_id,int(line.quantity*1000),minor(line.unit_price),str(line.tax_rate),sub,line_tax))
            audit(conn,user,'create','sale',identity)
            row=conn.execute('SELECT * FROM sales WHERE id=?',(identity,)).fetchone()
            result=sale_out(conn,row); conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback(); raise HTTPException(409,'Customer reference already exists for this customer')
        except Exception: conn.rollback(); raise
        return {**result,'replayed':False}

    @router.post('/api/sales/{sale_id}/post')
    def post(sale_id:int,user=Depends(roles('owner','accountant')),conn=Depends(database)):
        company=user['company_id']
        try:
            conn.execute('BEGIN IMMEDIATE')
            sale=conn.execute('SELECT * FROM sales WHERE id=? AND company_id=?',(sale_id,company)).fetchone()
            if not sale: raise HTTPException(404,'Sale not found')
            if sale['status']=='cancelled': raise HTTPException(409,'Cancelled sale cannot be posted')
            if sale['status']=='posted':
                conn.rollback(); return {'id':sale_id,'status':'posted','replayed':True}
            lines=conn.execute('SELECT * FROM sale_lines WHERE sale_id=? AND company_id=?',(sale_id,company)).fetchall()
            for line in lines:
                balance=conn.execute('SELECT COALESCE(SUM(delta_milli),0) FROM stock_movements WHERE company_id=? AND product_id=?',(company,line['product_id'])).fetchone()[0]
                if balance<line['quantity_milli']:
                    raise HTTPException(409,f'Insufficient stock for product {line["product_id"]}: available {quantity_text(balance)}')
                movement=conn.execute("""INSERT INTO stock_movements(company_id,product_id,kind,quantity_milli,delta_milli,reason,request_key,actor_id,created_at)
                    VALUES(?,?,'issue',?,?,?,?,?,?)""",(company,line['product_id'],line['quantity_milli'],-line['quantity_milli'],
                    f'Sale SAL-{sale_id:06d}',f'sys_sale_{sale_id}_line_{line["id"]}',user['id'],now().isoformat())).lastrowid
                conn.execute('INSERT INTO sale_stock_links(company_id,sale_line_id,movement_id) VALUES(?,?,?)',(company,line['id'],movement))
                audit(conn,user,'post','stock_movement',movement)
            conn.execute("UPDATE sales SET status='posted',posted_by=?,posted_at=? WHERE id=? AND company_id=?",(user['id'],now().isoformat(),sale_id,company))
            audit(conn,user,'post','sale',sale_id)
            conn.commit()
        except Exception: conn.rollback(); raise
        return {'id':sale_id,'status':'posted','replayed':False}

    @router.post('/api/sales/{sale_id}/cancel')
    def cancel(sale_id:int,user=Depends(roles('owner','accountant')),conn=Depends(database)):
        try:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM sales WHERE id=? AND company_id=?',(sale_id,user['company_id'])).fetchone()
            if not row: raise HTTPException(404,'Sale not found')
            if row['status']=='posted': raise HTTPException(409,'Posted sales require a return workflow; cancellation is not allowed')
            if row['status']!='cancelled':
                conn.execute("UPDATE sales SET status='cancelled' WHERE id=? AND company_id=?",(sale_id,user['company_id']))
                audit(conn,user,'cancel','sale',sale_id)
            conn.commit()
        except Exception: conn.rollback(); raise
        return {'id':sale_id,'status':'cancelled'}

    return router
