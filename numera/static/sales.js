'use strict';
function saleRequestKey() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2,'0')).join('');
}
function saleLabel(key) { return (language === 'ar' ? ar : en)[key] || en[key]; }
function saleProductOptions(select) {
  const previous = select.value;
  select.replaceChildren();
  catalogue.forEach(product => {
    const option = document.createElement('option'); option.value = product.id;
    option.textContent = `${product.sku} — ${product.name}`; select.append(option);
  });
  if (catalogue.some(product => String(product.id) === previous)) select.value = previous;
}
function addSaleLine() {
  const row = document.createElement('div'); row.className = 'sale-line';
  const fields = [['product_id','productName','select'],['quantity','quantity','number'],['unit_price','unitPrice','number'],['tax_rate','taxRate','number']];
  fields.forEach(([name,key,type]) => {
    const label = document.createElement('label'); const span = document.createElement('span');
    span.dataset.i18n = key; span.textContent = saleLabel(key);
    const input = document.createElement(type === 'select' ? 'select' : 'input'); input.dataset.field = name; input.required = true;
    if (type === 'select') saleProductOptions(input);
    else {
      input.type = type; input.min = name === 'quantity' ? '0.001' : '0';
      input.step = name === 'quantity' ? '0.001' : '0.01';
      if (name === 'tax_rate') { input.max = '100'; input.value = '0'; }
      if (name === 'unit_price') input.value = '0';
    }
    label.append(span,input); row.append(label);
  });
  const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'secondary';
  remove.dataset.i18n = 'removeLine'; remove.textContent = saleLabel('removeLine');
  remove.addEventListener('click', () => { if ($('sale-lines').children.length > 1) row.remove(); });
  row.append(remove); $('sale-lines').append(row);
  const product = row.querySelector('select'); const price = row.querySelector('[data-field=unit_price]');
  const defaultPrice = () => { price.value = catalogue.find(item => String(item.id) === product.value)?.sale_price || '0'; };
  product.addEventListener('change', defaultPrice); defaultPrice();
}
function saleAction(documentId, action, label) {
  const button = document.createElement('button'); button.type = 'button'; button.className = action === 'post' ? 'button' : 'secondary';
  button.textContent = label;
  button.addEventListener('click', async () => {
    button.disabled = true; message();
    try {
      await api(`/api/sales/${documentId}/${action}`, {});
      await refresh(); message(action === 'post' ? t('Invoice posted and stock deducted.','تم ترحيل الفاتورة وخصم المخزون.') : t('Draft cancelled.','تم إلغاء المسودة.'));
    } catch (error) { message(error.message,true); }
    finally { button.disabled = false; }
  });
  return button;
}
async function refreshSales(user) {
  const financial = ['owner','accountant'].includes(user.role);
  $('customers-panel').hidden = !financial;
  $('sales-panel').hidden = !financial;
  if (!financial) { $('customers').replaceChildren(); $('sale-register').replaceChildren(); return; }
  $('sale-form').hidden = !financial;
  if (financial) {
    const customers = await api('/api/customers');
    tableRows('customers', customers, ['code','name','phone','email','tax_id']);
    const selected = $('sale-customer').value; $('sale-customer').replaceChildren();
    customers.forEach(customer => { const option = document.createElement('option'); option.value = customer.id; option.textContent = customer.name; $('sale-customer').append(option); });
    if (customers.some(customer => String(customer.id) === selected)) $('sale-customer').value = selected;
    $('save-sale').disabled = !customers.length || !catalogue.length;
    $('add-sale-line').disabled = !catalogue.length;
    if (!$('sale-lines').children.length) addSaleLine();
    $('sale-lines').querySelectorAll('select').forEach(saleProductOptions);
    if (!$('sale-date').value) {
      const date = new Date(); const local = `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
      $('sale-date').value = local; $('sale-due').value = local;
    }
  }
  const sales = await api('/api/sales');
  $('sale-register').replaceChildren();
  if (!sales.length) {
    const p = document.createElement('p'); p.className = 'muted'; p.textContent = t('No sales yet.','لا توجد مبيعات بعد.'); $('sale-register').append(p);
  }
  sales.forEach(sale => {
    const detail = document.createElement('details'); detail.className = 'sale-document';
    const summary = document.createElement('summary');
    const status = {draft:t('Draft','مسودة'),posted:t('Posted','مرحّل'),cancelled:t('Cancelled','ملغى')}[sale.status];
    summary.textContent = `${sale.number} · ${sale.customer} · ${status}${financial ? ` · ${sale.total} ${sale.currency}` : ''}`;
    detail.append(summary);
    const info = document.createElement('p');
    info.textContent = `${saleLabel('customerReference')}: ${sale.customer_reference || '—'} · ${saleLabel('documentDate')}: ${sale.document_date}${financial ? ` · ${saleLabel('dueDate')}: ${sale.due_date}` : ''}`;
    detail.append(info);
    const wrap = document.createElement('div'); wrap.className = 'table-wrap'; const table = document.createElement('table');
    const keys = financial ? ['sku','name','quantity','unit_price','tax_rate','subtotal','tax'] : ['sku','name','quantity','unit'];
    const labels = {sku:'sku',name:'productName',quantity:'quantity',unit_price:'unitPrice',tax_rate:'taxRate',subtotal:'subtotal',tax:'tax',unit:'unit'};
    const head = document.createElement('thead'); const hr = document.createElement('tr');
    keys.forEach(key => { const th = document.createElement('th'); th.textContent = saleLabel(labels[key]); hr.append(th); }); head.append(hr); table.append(head);
    const body = document.createElement('tbody'); sale.lines.forEach(line => { const tr = document.createElement('tr'); keys.forEach(key => { const td = document.createElement('td'); td.textContent = line[key]; tr.append(td); }); body.append(tr); });
    table.append(body); wrap.append(table); detail.append(wrap);
    if (financial) {
      const totals = document.createElement('p'); totals.textContent = `${saleLabel('subtotal')}: ${sale.subtotal} · ${saleLabel('tax')}: ${sale.tax} · ${saleLabel('total')}: ${sale.total} ${sale.currency}`; detail.append(totals);
      if (sale.notes) { const notes = document.createElement('p'); notes.textContent = sale.notes; detail.append(notes); }
    }
    if (sale.status === 'draft') {
      const actions = document.createElement('div'); actions.className = 'actions';
      if (financial) actions.append(saleAction(sale.id,'post',saleLabel('postInvoice')));
      if (financial) actions.append(saleAction(sale.id,'cancel',saleLabel('cancelDraft')));
      detail.append(actions);
    }
    $('sale-register').append(detail);
  });
}
function initializeSales() {
  Object.assign(en,{unitPrice:'Unit price',taxRate:'Tax %',removeLine:'Remove',subtotal:'Subtotal',tax:'Tax',total:'Total',postInvoice:'Post invoice & deduct stock',cancelDraft:'Cancel draft'});
  Object.assign(ar,{saleModule:'وحدة المبيعات',customers:'العملاء',customerCode:'كود العميل',phone:'الهاتف',taxId:'الرقم الضريبي',saveCustomer:'حفظ العميل',sales:'فواتير المبيعات',saleIntro:'أنشئ مسودة ثم رحّل الفاتورة لخصم المخزون. الأسعار لا تشمل الضريبة. سجّل المدفوعات في وحدة التسويات. المرتجعات والقيود المحاسبية لاحقاً.',customer:'العميل',customerReference:'مرجع العميل',documentDate:'تاريخ المستند',dueDate:'تاريخ الاستحقاق',addLine:'إضافة صنف',notes:'ملاحظات',saveSaleDraft:'حفظ مسودة المبيعات',saleRegister:'سجل المبيعات',saleLimit:'آخر ٢٠٠ فاتورة. الترحيل يخصم كل الأصناف؛ المسودات لا تحجز المخزون. المرتجعات لاحقاً.',unitPrice:'سعر الوحدة',taxRate:'الضريبة %',removeLine:'حذف',subtotal:'الإجمالي قبل الضريبة',tax:'الضريبة',total:'الإجمالي',postInvoice:'ترحيل الفاتورة وخصم المخزون',cancelDraft:'إلغاء المسودة'});
  $('add-sale-line').addEventListener('click', addSaleLine);
  submit('customer-form', async (data, form) => { await api('/api/customers',data); form.reset(); await refresh(); message(t('Customer saved.','تم حفظ العميل.')); });
  submit('sale-form', async (data, form) => {
    data.customer_id = Number(data.customer_id);
    data.lines = Array.from($('sale-lines').children, row => {
      const fields = Object.fromEntries(Array.from(row.querySelectorAll('[data-field]'), input => [input.dataset.field,input.value]));
      fields.product_id = Number(fields.product_id); return fields;
    });
    const signature = JSON.stringify(data);
    if (!pendingSale || pendingSale.signature !== signature) pendingSale = {signature,requestKey:saleRequestKey()};
    data.request_key = pendingSale.requestKey;
    const result = await api('/api/sales',data); pendingSale = null;
    form.reset(); $('sale-lines').replaceChildren();
    await refresh(); message(t(`Sale ${result.number} saved: ${result.total} ${result.currency}. Stock is deducted when you post the invoice.`,`تم حفظ ${result.number} بإجمالي ${result.total} ${result.currency}. المخزون يُخصم عند ترحيل الفاتورة.`));
  });
}
