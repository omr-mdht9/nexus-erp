'use strict';
function randomRequestKey() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2,'0')).join('');
}
function purchaseLabel(key) { return (language === 'ar' ? ar : en)[key] || en[key]; }
function productOptions(select) {
  const previous = select.value;
  select.replaceChildren();
  catalogue.forEach(product => {
    const option = document.createElement('option'); option.value = product.id;
    option.textContent = `${product.sku} — ${product.name}`; select.append(option);
  });
  if (catalogue.some(product => String(product.id) === previous)) select.value = previous;
}
function addPurchaseLine() {
  const row = document.createElement('div'); row.className = 'purchase-line';
  const fields = [['product_id','productName','select'],['quantity','quantity','number'],['unit_price','unitPrice','number'],['tax_rate','taxRate','number']];
  fields.forEach(([name,key,type]) => {
    const label = document.createElement('label'); const span = document.createElement('span');
    span.dataset.i18n = key; span.textContent = purchaseLabel(key);
    const input = document.createElement(type === 'select' ? 'select' : 'input'); input.dataset.field = name; input.required = true;
    if (type === 'select') productOptions(input);
    else {
      input.type = type; input.min = name === 'quantity' ? '0.001' : '0';
      input.step = name === 'quantity' ? '0.001' : '0.01';
      if (name === 'tax_rate') { input.max = '100'; input.value = '0'; }
      if (name === 'unit_price') input.value = '0';
    }
    label.append(span,input); row.append(label);
  });
  const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'secondary';
  remove.dataset.i18n = 'removeLine'; remove.textContent = purchaseLabel('removeLine');
  remove.addEventListener('click', () => { if ($('purchase-lines').children.length > 1) row.remove(); });
  row.append(remove); $('purchase-lines').append(row);
}
function purchaseAction(documentId, action, label) {
  const button = document.createElement('button'); button.type = 'button'; button.className = action === 'receive' ? 'button' : 'secondary';
  button.textContent = label;
  button.addEventListener('click', async () => {
    button.disabled = true; message();
    try {
      await api(`/api/purchases/${documentId}/${action}`, {});
      await refresh(); message(action === 'receive' ? t('Goods received and stock updated.','تم استلام البضاعة وتحديث المخزون.') : t('Draft cancelled.','تم إلغاء المسودة.'));
    } catch (error) { message(error.message,true); }
    finally { button.disabled = false; }
  });
  return button;
}
async function refreshPurchases(user) {
  const financial = ['owner','accountant'].includes(user.role);
  $('suppliers-panel').hidden = !financial;
  $('purchase-form').hidden = !financial;
  if (financial) {
    const suppliers = await api('/api/suppliers');
    tableRows('suppliers', suppliers, ['code','name','phone','email','tax_id']);
    const selected = $('purchase-supplier').value; $('purchase-supplier').replaceChildren();
    suppliers.forEach(supplier => { const option = document.createElement('option'); option.value = supplier.id; option.textContent = supplier.name; $('purchase-supplier').append(option); });
    if (suppliers.some(supplier => String(supplier.id) === selected)) $('purchase-supplier').value = selected;
    $('save-purchase').disabled = !suppliers.length || !catalogue.length;
    $('add-purchase-line').disabled = !catalogue.length;
    if (!$('purchase-lines').children.length) addPurchaseLine();
    $('purchase-lines').querySelectorAll('select').forEach(productOptions);
    if (!$('purchase-date').value) {
      const date = new Date(); const local = `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
      $('purchase-date').value = local; $('purchase-due').value = local;
    }
  }
  const purchases = await api(financial ? '/api/purchases' : '/api/purchases/receiving');
  $('purchase-register').replaceChildren();
  if (!purchases.length) {
    const p = document.createElement('p'); p.className = 'muted'; p.textContent = t('No purchases yet.','لا توجد مشتريات بعد.'); $('purchase-register').append(p);
  }
  purchases.forEach(purchase => {
    const detail = document.createElement('details'); detail.className = 'purchase-document';
    const summary = document.createElement('summary');
    const status = {draft:t('Draft','مسودة'),received:t('Received','مستلم'),cancelled:t('Cancelled','ملغى')}[purchase.status];
    summary.textContent = `${purchase.number} · ${purchase.supplier} · ${status}${financial ? ` · ${purchase.total} ${purchase.currency}` : ''}`;
    detail.append(summary);
    const info = document.createElement('p');
    info.textContent = `${purchaseLabel('supplierReference')}: ${purchase.supplier_reference || '—'} · ${purchaseLabel('documentDate')}: ${purchase.document_date}${financial ? ` · ${purchaseLabel('dueDate')}: ${purchase.due_date}` : ''}`;
    detail.append(info);
    const wrap = document.createElement('div'); wrap.className = 'table-wrap'; const table = document.createElement('table');
    const keys = financial ? ['sku','name','quantity','unit_price','tax_rate','subtotal','tax'] : ['sku','name','quantity','unit'];
    const labels = {sku:'sku',name:'productName',quantity:'quantity',unit_price:'unitPrice',tax_rate:'taxRate',subtotal:'subtotal',tax:'tax',unit:'unit'};
    const head = document.createElement('thead'); const hr = document.createElement('tr');
    keys.forEach(key => { const th = document.createElement('th'); th.textContent = purchaseLabel(labels[key]); hr.append(th); }); head.append(hr); table.append(head);
    const body = document.createElement('tbody'); purchase.lines.forEach(line => { const tr = document.createElement('tr'); keys.forEach(key => { const td = document.createElement('td'); td.textContent = line[key]; tr.append(td); }); body.append(tr); });
    table.append(body); wrap.append(table); detail.append(wrap);
    if (financial) {
      const totals = document.createElement('p'); totals.textContent = `${purchaseLabel('subtotal')}: ${purchase.subtotal} · ${purchaseLabel('tax')}: ${purchase.tax} · ${purchaseLabel('total')}: ${purchase.total} ${purchase.currency}`; detail.append(totals);
      if (purchase.notes) { const notes = document.createElement('p'); notes.textContent = purchase.notes; detail.append(notes); }
    }
    if (purchase.status === 'draft') {
      const actions = document.createElement('div'); actions.className = 'actions';
      if (['owner','inventory'].includes(user.role)) actions.append(purchaseAction(purchase.id,'receive',purchaseLabel('receiveGoods')));
      if (financial) actions.append(purchaseAction(purchase.id,'cancel',purchaseLabel('cancelDraft')));
      detail.append(actions);
    }
    $('purchase-register').append(detail);
  });
}
function initializePurchases() {
  Object.assign(en,{unitPrice:'Unit price',taxRate:'Tax %',removeLine:'Remove',subtotal:'Subtotal',tax:'Tax',total:'Total',receiveGoods:'Receive all goods',cancelDraft:'Cancel draft'});
  Object.assign(ar,{purchaseModule:'وحدة المشتريات',suppliers:'الموردون',supplierCode:'كود المورد',phone:'الهاتف',taxId:'الرقم الضريبي',saveSupplier:'حفظ المورد',purchases:'المشتريات والاستلام',purchaseIntro:'أنشئ مسودة ثم استلم البضاعة لتحديث المخزون. الأسعار لا تشمل الضريبة. سجّل المدفوعات في وحدة التسويات. التقييم والقيود المحاسبية لاحقاً.',supplier:'المورد',supplierReference:'مرجع المورد',documentDate:'تاريخ المستند',dueDate:'تاريخ الاستحقاق',addLine:'إضافة صنف',notes:'ملاحظات',saveDraft:'حفظ مسودة المشتريات',purchaseRegister:'سجل المشتريات / قائمة الاستلام',purchaseLimit:'آخر ٢٠٠ مستند. الاستلام يرحّل جميع الأصناف بالكامل؛ الاستلام الجزئي والمرتجعات لاحقاً.',unitPrice:'سعر الوحدة',taxRate:'الضريبة %',removeLine:'حذف',subtotal:'الإجمالي قبل الضريبة',tax:'الضريبة',total:'الإجمالي',receiveGoods:'استلام كل البضاعة',cancelDraft:'إلغاء المسودة'});
  $('add-purchase-line').addEventListener('click', addPurchaseLine);
  submit('supplier-form', async (data, form) => { await api('/api/suppliers',data); form.reset(); await refresh(); message(t('Supplier saved.','تم حفظ المورد.')); });
  submit('purchase-form', async (data, form) => {
    data.supplier_id = Number(data.supplier_id);
    data.lines = Array.from($('purchase-lines').children, row => {
      const fields = Object.fromEntries(Array.from(row.querySelectorAll('[data-field]'), input => [input.dataset.field,input.value]));
      fields.product_id = Number(fields.product_id); return fields;
    });
    const signature = JSON.stringify(data);
    if (!pendingPurchase || pendingPurchase.signature !== signature) pendingPurchase = {signature,requestKey:randomRequestKey()};
    data.request_key = pendingPurchase.requestKey;
    const result = await api('/api/purchases',data); pendingPurchase = null;
    form.reset(); $('purchase-lines').replaceChildren();
    await refresh(); message(t(`Purchase ${result.number} saved: ${result.total} ${result.currency}. Stock changes when goods are received.`,`تم حفظ ${result.number} بإجمالي ${result.total} ${result.currency}. المخزون يتغير عند الاستلام.`));
  });
}
