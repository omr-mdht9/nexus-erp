"""Company-scoped, exact-quantity inventory for the single-warehouse first release."""
from decimal import Decimal
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

SCHEMA = """
CREATE UNIQUE INDEX IF NOT EXISTS products_company_identity ON products(company_id,id);
CREATE TABLE IF NOT EXISTS stock_movements (
 id INTEGER PRIMARY KEY,
 company_id INTEGER NOT NULL REFERENCES companies(id),
 product_id INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('opening','receipt','issue','adjustment_in','adjustment_out')),
 quantity_milli INTEGER NOT NULL CHECK(quantity_milli>0 AND quantity_milli<=99999999999999),
 delta_milli INTEGER NOT NULL,
 reason TEXT NOT NULL,
 request_key TEXT NOT NULL,
 actor_id INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 FOREIGN KEY(company_id,product_id) REFERENCES products(company_id,id),
 UNIQUE(company_id,request_key),
 CHECK(delta_milli=CASE WHEN kind IN ('issue','adjustment_out') THEN -quantity_milli ELSE quantity_milli END)
);
CREATE INDEX IF NOT EXISTS movements_company_product ON stock_movements(company_id,product_id);
CREATE UNIQUE INDEX IF NOT EXISTS one_opening_per_product ON stock_movements(company_id,product_id) WHERE kind='opening';
"""


class MovementIn(BaseModel):
    product_id: int = Field(gt=0)
    kind: Literal['opening','receipt','issue','adjustment_in','adjustment_out']
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    reason: str = Field(min_length=3, max_length=200)
    request_key: str = Field(min_length=16, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')

    @field_validator('reason')
    @classmethod
    def reason_text(cls, value):
        value = value.strip()
        if len(value) < 3:
            raise ValueError('Give a meaningful reason of at least three characters')
        return value


def quantity_text(milli):
    return format(Decimal(milli)/1000, '.3f')


def movement_out(row):
    return {'id':row['id'],'product_id':row['product_id'],'kind':row['kind'],
            'quantity':quantity_text(row['quantity_milli']),'change':quantity_text(row['delta_milli']),
            'reason':row['reason'],'request_key':row['request_key'],'actor_id':row['actor_id'],
            'created_at':row['created_at']}


def build_router(database, current_user, roles, audit, now):
    router = APIRouter(prefix='/api/inventory', tags=['Inventory'])

    @router.get('/balances')
    def balances(user=Depends(current_user), conn=Depends(database)):
        rows = conn.execute('''SELECT p.id,p.sku,p.name,p.unit,p.reorder_level,
            COALESCE(SUM(m.delta_milli),0) AS balance_milli,
            MAX(CASE WHEN m.kind='opening' THEN 1 ELSE 0 END) AS has_opening,
            COUNT(m.id) AS movement_count
            FROM products p LEFT JOIN stock_movements m
            ON m.company_id=p.company_id AND m.product_id=p.id
            WHERE p.company_id=? GROUP BY p.id ORDER BY p.sku''', (user['company_id'],))
        return [{'product_id':r['id'],'sku':r['sku'],'name':r['name'],'unit':r['unit'],
                 'quantity':quantity_text(r['balance_milli']), 'reorder_level':r['reorder_level'],
                 'low_stock':Decimal(r['balance_milli'])/1000<=Decimal(r['reorder_level']),
                 'opening_allowed':r['movement_count']==0} for r in rows]

    @router.get('/movements')
    def movements(product_id: int | None = None, user=Depends(current_user), conn=Depends(database)):
        if product_id is not None:
            product = conn.execute('SELECT id FROM products WHERE id=? AND company_id=?', (product_id,user['company_id'])).fetchone()
            if not product:
                raise HTTPException(404,'Product not found')
        sql = '''SELECT m.*,p.sku,p.name FROM stock_movements m
                 JOIN products p ON p.company_id=m.company_id AND p.id=m.product_id
                 WHERE m.company_id=?'''
        args = [user['company_id']]
        if product_id is not None:
            sql += ' AND m.product_id=?'
            args.append(product_id)
        rows = conn.execute(sql+' ORDER BY m.id DESC LIMIT 200', args)
        return [{**movement_out(r),'sku':r['sku'],'name':r['name']} for r in rows]

    @router.post('/movements', status_code=201)
    def create_movement(data:MovementIn,user=Depends(roles('owner','inventory')),conn=Depends(database)):
        company_id = user['company_id']
        quantity_milli = int(data.quantity*1000)
        delta = -quantity_milli if data.kind in ('issue','adjustment_out') else quantity_milli
        # Serialize balance checks and posting in SQLite; two simultaneous issues cannot oversell.
        try:
            conn.execute('BEGIN IMMEDIATE')
            product = conn.execute('SELECT id FROM products WHERE id=? AND company_id=?',(data.product_id,company_id)).fetchone()
            if not product:
                raise HTTPException(404,'Product not found')
            previous = conn.execute('SELECT * FROM stock_movements WHERE company_id=? AND request_key=?',(company_id,data.request_key)).fetchone()
            if previous:
                if (previous['product_id'],previous['kind'],previous['quantity_milli'],previous['reason']) != (data.product_id,data.kind,quantity_milli,data.reason):
                    raise HTTPException(409,'This request key was already used for a different movement')
                conn.rollback()
                return {**movement_out(previous),'replayed':True}
            totals = conn.execute('SELECT COALESCE(SUM(delta_milli),0),COUNT(*) FROM stock_movements WHERE company_id=? AND product_id=?',(company_id,data.product_id)).fetchone()
            if data.kind=='opening' and totals[1]:
                raise HTTPException(409,'Opening stock can only be set before the first movement; use a reasoned adjustment')
            balance = totals[0]+delta
            if balance < 0:
                raise HTTPException(409,f'Insufficient stock: available {quantity_text(totals[0])}')
            if balance > 99999999999999:
                raise HTTPException(422,'Stock quantity exceeds the supported limit')
            identity = conn.execute('''INSERT INTO stock_movements
                (company_id,product_id,kind,quantity_milli,delta_milli,reason,request_key,actor_id,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)''',
                (company_id,data.product_id,data.kind,quantity_milli,delta,data.reason,data.request_key,user['id'],now().isoformat())).lastrowid
            audit(conn,user,'post','stock_movement',identity)
            row = conn.execute('SELECT * FROM stock_movements WHERE id=? AND company_id=?',(identity,company_id)).fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return {**movement_out(row),'replayed':False}

    return router
