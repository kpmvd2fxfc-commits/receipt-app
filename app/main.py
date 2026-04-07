from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, ForeignKey, func, text
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Any
import base64, json, os, re

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./receipts.db')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith('sqlite') else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class Receipt(Base):
    __tablename__ = 'receipts'
    id = Column(Integer, primary_key=True)
    store_name = Column(String(255))
    receipt_date = Column(Date, nullable=False)
    total_amount = Column(Float, default=0)
    currency = Column(String(10), default='AED')
    raw_text = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    items = relationship('ReceiptItem', back_populates='receipt', cascade='all, delete-orphan')

class ReceiptItem(Base):
    __tablename__ = 'receipt_items'
    id = Column(Integer, primary_key=True)
    receipt_id = Column(Integer, ForeignKey('receipts.id'))
    name = Column(String(255), nullable=False)
    normalized_name = Column(String(255), nullable=True)
    quantity = Column(Float, default=1)
    unit = Column(String(30), default='pcs')
    line_total = Column(Float, default=0)
    unit_price = Column(Float, default=0)
    category = Column(String(100), nullable=True)
    receipt = relationship('Receipt', back_populates='items')

Base.metadata.create_all(engine)

app = FastAPI(title='Receipt Cloud PWA')
static_dir = Path(__file__).parent / 'static'
templates = Jinja2Templates(directory=str(Path(__file__).parent / 'templates'))
app.mount('/static', StaticFiles(directory=str(static_dir)), name='static')

SYSTEM_PROMPT = '''You extract grocery receipt data from UAE/English receipts. Return JSON only with this schema:
{
  "store_name": string,
  "receipt_date": "YYYY-MM-DD",
  "currency": "AED",
  "total_amount": number,
  "items": [
    {"name": string, "normalized_name": string, "quantity": number, "unit": string, "line_total": number, "unit_price": number, "category": string}
  ],
  "raw_text": string
}
Rules:
- Focus on grocery/food/household items. Ignore VAT summary lines, subtotal lines, payment lines, loyalty points.
- If quantity is unclear use 1.
- If unit price is missing, derive unit_price = line_total / quantity when possible.
- Keep currency AED unless clearly another UAE currency notation is shown.
- For receipt_date, infer from receipt if visible; otherwise use today's date.
- normalized_name should be clean standardized English product name.
- Return valid JSON only.
'''

def call_openai_receipt_parser(file_bytes: bytes, mime_type: str) -> dict[str, Any]:
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail='OPENAI_API_KEY is not set.')
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        b64 = base64.b64encode(file_bytes).decode('utf-8')
        input_payload = [{
            'role': 'user',
            'content': [
                {'type': 'input_text', 'text': SYSTEM_PROMPT},
                {'type': 'input_image', 'image_url': f'data:{mime_type};base64,{b64}'}
            ]
        }]
        resp = client.responses.create(
            model=os.getenv('OPENAI_MODEL', 'gpt-5.4-mini'),
            input=input_payload,
        )
        text_out = getattr(resp, 'output_text', None)
        if not text_out:
            text_out = str(resp)
        match = re.search(r'\{.*\}', text_out, flags=re.S)
        if not match:
            raise ValueError('Model did not return JSON.')
        return json.loads(match.group(0))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'AI parsing failed: {e}')

@app.get('/', response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse('index.html', {'request': request})

@app.get('/manifest.json')
def manifest():
    return JSONResponse({
        'name': 'Receipt Tracker AI',
        'short_name': 'Receipts',
        'start_url': '/',
        'display': 'standalone',
        'background_color': '#ffffff',
        'theme_color': '#111827',
        'icons': []
    })

@app.get('/health')
def health():
    return {'ok': True}

@app.post('/api/upload')
async def upload_receipt(file: UploadFile = File(...)):
    content = await file.read()
    mime = file.content_type or 'image/jpeg'
    parsed = call_openai_receipt_parser(content, mime)
    session = SessionLocal()
    try:
        receipt_date = parsed.get('receipt_date') or str(date.today())
        receipt = Receipt(
            store_name=parsed.get('store_name') or 'Unknown store',
            receipt_date=datetime.strptime(receipt_date, '%Y-%m-%d').date(),
            total_amount=float(parsed.get('total_amount') or 0),
            currency=parsed.get('currency') or 'AED',
            raw_text=parsed.get('raw_text') or ''
        )
        session.add(receipt)
        session.flush()
        for item in parsed.get('items', []):
            qty = float(item.get('quantity') or 1)
            line_total = float(item.get('line_total') or 0)
            unit_price = float(item.get('unit_price') or (line_total / qty if qty else 0))
            session.add(ReceiptItem(
                receipt_id=receipt.id,
                name=item.get('name') or 'Unknown item',
                normalized_name=item.get('normalized_name') or item.get('name') or 'Unknown item',
                quantity=qty,
                unit=item.get('unit') or 'pcs',
                line_total=line_total,
                unit_price=unit_price,
                category=item.get('category') or 'Other',
            ))
        session.commit()
        return {'success': True, 'receipt_id': receipt.id, 'parsed': parsed}
    finally:
        session.close()

@app.get('/api/daily-spend')
def daily_spend():
    session = SessionLocal()
    try:
        rows = session.query(Receipt.receipt_date, func.sum(Receipt.total_amount)).group_by(Receipt.receipt_date).order_by(Receipt.receipt_date.desc()).all()
        return [{'date': str(r[0]), 'total': round(float(r[1] or 0), 2)} for r in rows]
    finally:
        session.close()

@app.get('/api/average-prices')
def average_prices():
    session = SessionLocal()
    try:
        rows = session.query(
            ReceiptItem.normalized_name,
            func.avg(ReceiptItem.unit_price),
            func.count(ReceiptItem.id)
        ).group_by(ReceiptItem.normalized_name).order_by(func.count(ReceiptItem.id).desc()).all()
        return [{'item': r[0], 'avg_unit_price': round(float(r[1] or 0), 2), 'times_bought': int(r[2])} for r in rows]
    finally:
        session.close()

@app.get('/api/receipts')
def list_receipts():
    session = SessionLocal()
    try:
        receipts = session.query(Receipt).order_by(Receipt.receipt_date.desc(), Receipt.created_at.desc()).all()
        result = []
        for r in receipts:
            result.append({
                'id': r.id,
                'store_name': r.store_name,
                'receipt_date': str(r.receipt_date),
                'total_amount': r.total_amount,
                'currency': r.currency,
                'items': [
                    {
                        'name': i.name,
                        'normalized_name': i.normalized_name,
                        'quantity': i.quantity,
                        'unit': i.unit,
                        'line_total': i.line_total,
                        'unit_price': i.unit_price,
                        'category': i.category,
                    } for i in r.items
                ]
            })
        return result
    finally:
        session.close()
