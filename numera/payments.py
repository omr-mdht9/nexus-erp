"""Document-linked settlement records; no actual transfer or bank integration."""
from datetime import date
from decimal import Decimal
import json
import sqlite3
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from numera.purchases import minor, money

SCHEMA='''
CREATE TABLE IF NOT EXISTS payments (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
 kind TEXT NOT NULL CHECK(kind IN ('receipt','payment')),
 sale_id INTEGER, purchase_id INTEGER,
 amount_minor INTEGER NOT NULL CHECK(amount_minor>0 AND amount_minor<=99999999999999),
 method TEXT NOT NULL CHECK(method IN ('cash','bank')),
 payment_date TEXT NOT NULL, reference TEXT NOT NULL, notes TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('posted','voided')),
 request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
 created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
 voided_by INTEGER REFERENCES users(id), voided_at TEXT, void_reason TEXT,
 FOREIGN KEY(company_id,sale_id) REFERENCES sales(company_id,id),
 FOREIGN KEY(company_id,purchase_id) REFERENCES purchases(company_id,id),
 CHECK((kind='receipt' AND sale_id IS NOT NULL AND purchase_id IS NULL) OR
       (kind='payment' AND purchase_id IS NOT NULL AND sale_id IS NULL)),
 UNIQUE(company_id,request_key));
CREATE UNIQUE INDEX IF NOT EXISTS payment_reference ON payments(company_id,kind,reference) WHERE reference<>'' AND status='posted';
CREATE INDEX IF NOT EXISTS payment_sale ON payments(company_id,sale_id,status);
CREATE INDEX IF NOT EXISTS payment_purchase ON payments(company_id,purchase_id,status);
'''

class PaymentIn(BaseModel):
    kind: Literal['receipt','payment']
    document_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0,max_digits=14,decimal_places=2)
    method: Literal['cash','bank'] = 'bank'
    payment_date: date
    reference: str = Field(default='',max_length=100)
    notes: str = Field(default='',max_length=500)
    request_key: str = Field(min_length=16,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')

    @field_validator('reference')
    @classmethod
    def trim_reference(cls,value): return value.strip()

class VoidIn(BaseModel):
    reason: str = Field(min_length=3,max_length=200)

    @field_validator('reason')
    @classmethod
    def trim_reason(cls,value):
        value=value.strip()
        if len(value)<3: raise ValueError('Enter a meaningful reason')
        return value


def document_config(kind):
    return ('sales','sale_id','customers','customer_id','posted','SAL') if kind=='receipt' else ('purchases','purchase_id','suppliers','supplier_id','received','PUR')


def paid_minor(conn,company,column,document_id):
    # column is supplied only by document_config, never by a client string.
    return conn.execute(f"SELECT COALESCE(SUM(amount_minor),0) FROM payments WHERE company_id=? AND {column}=? AND status='posted'",(company,document_id)).fetchone()[0]


def payment_out(conn,row):
    table,column,party_table,party_column,_,prefix=document_config(row['kind'])
    document_id=row[column]
    document=conn.execute(f'SELECT * FROM {table} WHERE company_id=? AND id=?',(row['company_id'],document_id)).fetchone()
    party=conn.execute(f'SELECT name FROM {party_table} WHERE company_id=? AND id=?',(row['company_id'],document[party_column])).fetchone()
    return {'id':row['id'],'number':f'PAY-{row["id"]:06d}','kind':row['kind'],'document_id':document_id,
        'document_number':f'{prefix}-{document_id:06d}','party':party['name'],'amount':money(row['amount_minor']),
        'method':row['method'],'payment_date':row['payment_date'],'reference':row['reference'],'notes':row['notes'],
        'status':row['status'],'created_at':row['created_at'],'voided_at':row['voided_at'],'void_reason':row['void_reason']}


def build_router(database,roles,audit,now):
    router=APIRouter(prefix='/api',tags=['Settlements'])
    financial=roles('owner','accountant')

    @router.get('/payments')
    def payments(user=Depends(financial),conn=Depends(database)):
        return [payment_out(conn,row) for row in conn.execute('SELECT * FROM payments WHERE company_id=? ORDER BY id DESC LIMIT 200',(user['company_id'],))]

    @router.post('/payments',status_code=201)
    def create_payment(data:PaymentIn,user=Depends(financial),conn=Depends(database)):
        company=user['company_id']; amount=minor(data.amount)
        table,column,_,_,required,_=document_config(data.kind)
        payload=data.model_dump(mode='json',exclude={'request_key'}); payload['amount']=money(amount)
        fingerprint=json.dumps(payload,sort_keys=True,separators=(',',':'))
        try:
            conn.execute('BEGIN IMMEDIATE')
            old=conn.execute('SELECT * FROM payments WHERE company_id=? AND request_key=?',(company,data.request_key)).fetchone()
            if old:
                if old['fingerprint']!=fingerprint: raise HTTPException(409,'Request key already used for a different settlement')
                result=payment_out(conn,old); conn.rollback(); return {**result,'replayed':True}
            document=conn.execute(f'SELECT * FROM {table} WHERE id=? AND company_id=?',(data.document_id,company)).fetchone()
            if not document: raise HTTPException(404,'Document not found')
            if document['status']!=required: raise HTTPException(409,'Only posted sales or received purchases can be settled')
            if data.payment_date<date.fromisoformat(document['document_date']): raise HTTPException(422,'Payment date cannot be before the document date')
            remaining=document['total_minor']-paid_minor(conn,company,column,data.document_id)
            if amount>remaining: raise HTTPException(409,f'Amount exceeds outstanding balance {money(remaining)}')
            identity=conn.execute('''INSERT INTO payments(company_id,kind,sale_id,purchase_id,amount_minor,method,payment_date,
                reference,notes,status,request_key,fingerprint,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,'posted',?,?,?,?)''',
                (company,data.kind,data.document_id if data.kind=='receipt' else None,data.document_id if data.kind=='payment' else None,
                amount,data.method,data.payment_date.isoformat(),data.reference,data.notes,data.request_key,fingerprint,user['id'],now().isoformat())).lastrowid
            audit(conn,user,'post','payment',identity)
            result=payment_out(conn,conn.execute('SELECT * FROM payments WHERE id=? AND company_id=?',(identity,company)).fetchone())
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback(); raise HTTPException(409,'This payment reference is already recorded')
        except Exception: conn.rollback(); raise
        return {**result,'replayed':False}

    @router.post('/payments/{payment_id}/void')
    def void(payment_id:int,data:VoidIn,user=Depends(financial),conn=Depends(database)):
        try:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM payments WHERE id=? AND company_id=?',(payment_id,user['company_id'])).fetchone()
            if not row: raise HTTPException(404,'Payment not found')
            if row['status']=='posted':
                conn.execute("UPDATE payments SET status='voided',voided_by=?,voided_at=?,void_reason=? WHERE id=? AND company_id=?",(user['id'],now().isoformat(),data.reason,payment_id,user['company_id']))
                audit(conn,user,'void','payment',payment_id)
            result=payment_out(conn,conn.execute('SELECT * FROM payments WHERE id=? AND company_id=?',(payment_id,user['company_id'])).fetchone())
            conn.commit()
        except Exception: conn.rollback(); raise
        return result

    @router.get('/outstanding')
    def outstanding(aging_date:date | None=None,user=Depends(financial),conn=Depends(database)):
        # Balances are current; aging_date controls overdue classification, not historical balance reconstruction.
        today=aging_date or now().date(); company=user['company_id']; rows=[]
        totals={'receipt':0,'payment':0}
        for kind in ('receipt','payment'):
            table,column,party_table,party_column,required,prefix=document_config(kind)
            documents=conn.execute(f'SELECT * FROM {table} WHERE company_id=? AND status=? ORDER BY due_date,id',(company,required))
            for document in documents:
                paid=paid_minor(conn,company,column,document['id']); remaining=document['total_minor']-paid
                totals[kind]+=remaining
                party=conn.execute(f'SELECT name FROM {party_table} WHERE company_id=? AND id=?',(company,document[party_column])).fetchone()
                rows.append({'kind':kind,'document_id':document['id'],'number':f'{prefix}-{document["id"]:06d}','party_id':document[party_column],
                    'party':party['name'],'document_date':document['document_date'],'due_date':document['due_date'],
                    'total':money(document['total_minor']),'paid':money(paid),'remaining':money(remaining),
                    'status':'settled' if remaining==0 else 'overdue' if date.fromisoformat(document['due_date'])<today else 'open'})
        company_row=conn.execute('SELECT currency FROM companies WHERE id=?',(company,)).fetchone()
        return {'aging_date':today.isoformat(),'balance_basis':'current','currency':company_row['currency'],
            'customer_outstanding':money(totals['receipt']),'supplier_outstanding':money(totals['payment']),'documents':rows}

    @router.get('/payment-summary')
    def summary(user=Depends(financial),conn=Depends(database)):
        result=[]
        for method in ('cash','bank'):
            amounts={kind:conn.execute("SELECT COALESCE(SUM(amount_minor),0) FROM payments WHERE company_id=? AND method=? AND kind=? AND status='posted'",(user['company_id'],method,kind)).fetchone()[0] for kind in ('receipt','payment')}
            result.append({'method':method,'receipts':money(amounts['receipt']),'payments':money(amounts['payment']),
                'net_recorded_settlements':money(amounts['receipt']-amounts['payment'])})
        return result

    return router
