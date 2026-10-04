'use strict';
function localDate() {
  const date=new Date(); return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
}
function syncPaymentDocuments(resetAmount=true) {
  const selected=$('payment-document').value; const kind=$('payment-kind').value;
  const docs=outstandingDocuments.filter(row=>row.kind===kind && row.status!=='settled');
  $('payment-document').replaceChildren();
  docs.forEach(row=>{ const option=document.createElement('option'); option.value=row.document_id; option.textContent=`${row.number} · ${row.party} · ${row.remaining}`; $('payment-document').append(option); });
  if(docs.some(row=>String(row.document_id)===selected)) $('payment-document').value=selected;
  const documentRow=docs.find(row=>String(row.document_id)===$('payment-document').value);
  $('save-payment').disabled=!documentRow;
  if(documentRow) {
    $('payment-amount').max=documentRow.remaining;
    if(resetAmount || !$('payment-amount').value) $('payment-amount').value=documentRow.remaining;
    $('payment-date').min=documentRow.document_date;
    if(!$('payment-date').value) $('payment-date').value=localDate();
  } else { $('payment-amount').value=''; $('payment-amount').removeAttribute('max'); }
}
async function refreshPayments(user) {
  const financial=['owner','accountant'].includes(user.role); $('payments-panel').hidden=!financial;
  if(!financial) { outstandingDocuments=[]; return; }
  const report=await api(`/api/outstanding?aging_date=${localDate()}`); outstandingDocuments=report.documents;
  $('customer-outstanding').textContent=`${report.customer_outstanding} ${report.currency}`;
  $('supplier-outstanding').textContent=`${report.supplier_outstanding} ${report.currency}`;
  const states={open:t('Open','مفتوح'),overdue:t('Overdue','متأخر'),settled:t('Settled','مسدد')};
  tableRows('document-balances',report.documents.map(row=>({...row,status:states[row.status]})),['number','party','due_date','total','paid','remaining','status']);
  syncPaymentDocuments(false);
  const history=await api('/api/payments'); $('payment-history').replaceChildren();
  if(!history.length) { const p=document.createElement('p'); p.className='muted'; p.textContent=t('No payments recorded yet.','لا توجد مدفوعات مسجلة بعد.'); $('payment-history').append(p); }
  history.forEach(row=>{
    const block=document.createElement('div'); block.className='payment-record';
    const title=document.createElement('strong'); title.textContent=`${row.number} · ${row.document_number} · ${row.party} · ${row.amount} ${report.currency}`; block.append(title);
    const detail=document.createElement('p'); detail.textContent=`${row.kind==='receipt'?t('Receipt','تحصيل'):t('Payment','دفع')} · ${row.method==='bank'?t('Bank','بنك'):t('Cash','نقدي')} · ${row.payment_date} · ${row.reference || '—'} · ${row.status==='posted'?t('Recorded','مسجل'):t('Voided','ملغى')}`; block.append(detail);
    if(row.notes) { const note=document.createElement('p'); note.textContent=row.notes; block.append(note); }
    if(row.status==='voided') { const reason=document.createElement('p'); reason.textContent=t(`Void reason: ${row.void_reason}`,`سبب الإلغاء: ${row.void_reason}`); block.append(reason); }
    else {
      const form=document.createElement('form'); form.className='void-payment-form';
      const label=document.createElement('label'); label.textContent=t('Reason for correcting this payment','سبب تصحيح هذا السجل');
      const input=document.createElement('input'); input.required=true; input.minLength=3; input.maxLength=200; label.append(input);
      const button=document.createElement('button'); button.type='submit'; button.className='secondary'; button.textContent=t('Void record','إلغاء السجل'); form.append(label,button);
      form.addEventListener('submit',async event=>{
        event.preventDefault(); button.disabled=true; message();
        try { await api(`/api/payments/${row.id}/void`,{reason:input.value}); await refresh(); message(t('Payment voided; balance restored.','تم إلغاء السجل واستعادة الرصيد المستحق.')); }
        catch(error) { message(error.message,true); } finally { button.disabled=false; }
      }); block.append(form);
    }
    $('payment-history').append(block);
  });
  const summary=await api('/api/payment-summary');
  tableRows('payment-summary',summary.map(row=>({...row,method:row.method==='bank'?t('Bank','بنك'):t('Cash','نقدي')})),['method','receipts','payments','net_recorded_settlements']);
}
function initializePayments() {
  Object.assign(ar,{settlementModule:'المدفوعات والأرصدة',settlements:'تحصيلات العملاء ومدفوعات الموردين',settlementIntro:'سجّل دفعة تمت بالفعل مقابل فاتورة مبيعات مرحّلة أو مشتريات مستلمة. هذا يسجّل التسوية ولا يحوّل الأموال أو يتصل بالبنك.',customerOutstanding:'المستحق على العملاء',supplierOutstanding:'المستحق للموردين',paymentKind:'النوع',customerReceipt:'تحصيل عميل',supplierPayment:'دفع لمورد',document:'المستند',amount:'المبلغ',paymentMethod:'الطريقة',bank:'بنك',cash:'نقدي',paymentDate:'تاريخ الدفع',paymentReference:'مرجع الدفع',recordPayment:'تسجيل الدفعة',outstandingDocs:'أرصدة المستندات',balanceIntro:'الأرصدة الحالية؛ التأخير حسب تاريخ اليوم. هذه سجلات تسوية وليست دفتر حسابات مكتمل.',party:'العميل / المورد',paid:'المسدد',remaining:'المتبقي',paymentHistory:'سجل المدفوعات',paymentLimit:'آخر ٢٠٠ سجل. ألغِ السجل الخطأ مع ذكر السبب؛ يبقى السجل الأصلي محفوظاً.',recordedSummary:'التسويات المسجلة للنقد والبنك',netIntro:'التحصيلات ناقص مدفوعات الموردين فقط. لا تشمل الأرصدة الافتتاحية أو المصروفات.',receipts:'التحصيلات',payments:'المدفوعات',netRecorded:'صافي المسجل'});
  $('payment-kind').addEventListener('change',()=>syncPaymentDocuments());
  $('payment-document').addEventListener('change',()=>syncPaymentDocuments());
  submit('payment-form',async(data,form)=>{
    data.document_id=Number(data.document_id); const signature=JSON.stringify(data);
    if(!pendingPayment || pendingPayment.signature!==signature) pendingPayment={signature,requestKey:randomRequestKey()};
    data.request_key=pendingPayment.requestKey;
    await api('/api/payments',data); pendingPayment=null; form.reset(); await refresh(); message(t('Payment recorded.','تم تسجيل الدفعة.'));
  });
}
