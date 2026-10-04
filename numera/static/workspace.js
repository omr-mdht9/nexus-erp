'use strict';
let token = null;
let profile = null;
let language = 'en';
const $ = id => document.getElementById(id);
const en = {};
document.querySelectorAll('[data-i18n]').forEach(el => { en[el.dataset.i18n] = el.textContent; });
const ar = {logout:'تسجيل الخروج',banner:'بيئة تطوير · استخدم بيانات تجريبية فقط · الدفع غير مفعّل',welcome:'مرحباً بك في بداية جديدة.',intro:'أنشئ مساحة شركتك وابدأ تنظيم منتجاتك.',back:'العودة إلى NUMERA ←',register:'إنشاء حساب',login:'تسجيل الدخول',companyTitle:'شركتك، مساحة عملك.',company:'اسم الشركة',name:'الاسم',email:'البريد الإلكتروني',password:'كلمة المرور (١٢ حرفاً على الأقل)',passwordSimple:'كلمة المرور',currency:'العملة',create:'إنشاء مساحة العمل',loginTitle:'مرحباً بعودتك.',workspace:'مساحة عملك',products:'المنتجات',catalogue:'كتالوج شركتك. حركات المخزون ستُضاف في المرحلة التالية.',sku:'كود الصنف',productName:'اسم المنتج',unit:'الوحدة',price:'سعر البيع',reorder:'حد إعادة الطلب',addProduct:'إضافة منتج',saveProduct:'حفظ المنتج',team:'فريق العمل',roles:'موظف المخزون يدير المنتجات. المحاسب يستعرض الكتالوج. المالك يدير الموظفين.',role:'الدور',inventory:'المخزون',accountant:'محاسب',addEmployee:'إضافة موظف',audit:'سجل النشاط'};
function t(enText, arText) { return language === 'ar' ? arText : enText; }
function message(text = '', error = false) { $('message').textContent = text; $('message').classList.toggle('error', error); }
function translate() {
  document.documentElement.lang = language;
  document.documentElement.dir = language === 'ar' ? 'rtl' : 'ltr';
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = (language === 'ar' ? ar : en)[el.dataset.i18n] || en[el.dataset.i18n]; });
  $('language').textContent = language === 'ar' ? 'English' : 'العربية';
}
function showAuth() {
  const login = location.hash === '#login';
  $('login-form').hidden = !login;
  $('register-form').hidden = login;
  $('show-login').setAttribute('aria-selected', String(login));
  $('show-register').setAttribute('aria-selected', String(!login));
}
function logout() {
  token = null; profile = null;
  $('dashboard').hidden = true; $('auth').hidden = false; $('logout').hidden = true;
  ['products','team','audit','company-heading','account-detail','trial-status'].forEach(id => { $(id).replaceChildren(); });
  document.querySelectorAll('form').forEach(form => form.reset());
}
async function api(path, data) {
  const headers = {};
  if (data) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, {method:data ? 'POST' : 'GET', headers, body:data ? JSON.stringify(data) : undefined, cache:'no-store'});
  const payload = await response.json();
  if (!response.ok) {
    if (response.status === 401 && token) logout();
    const detail = Array.isArray(payload.detail) ? payload.detail.map(e => e.msg).join('; ') : payload.detail;
    throw new Error(detail || 'Request failed');
  }
  return payload;
}
function tableRows(id, rows, keys) {
  const body = $(id); body.replaceChildren();
  if (!rows.length) {
    const tr = document.createElement('tr'); const td = document.createElement('td');
    td.colSpan = keys.length; td.className = 'empty'; td.textContent = t('Nothing here yet. Add your first record.', 'لا توجد سجلات بعد. أضف أول سجل.'); tr.append(td); body.append(tr); return;
  }
  rows.forEach(row => { const tr = document.createElement('tr'); keys.forEach(key => { const td = document.createElement('td'); td.textContent = String(row[key]); tr.append(td); }); body.append(tr); });
}
async function refresh() {
  profile = await api('/api/auth/me');
  const {user,company,subscription} = profile;
  $('auth').hidden = true; $('dashboard').hidden = false; $('logout').hidden = false;
  $('company-heading').textContent = company.name;
  $('account-detail').textContent = `${user.name} · ${user.role} · ${company.currency}`;
  const date = new Date(company.trial_ends_at).toLocaleDateString(language === 'ar' ? 'ar-EG' : 'en-GB');
  $('trial-status').textContent = subscription.status === 'trial' ? t(`Development trial until ${date}`, `التجربة التطويرية حتى ${date}`) : t('Development trial expired', 'انتهت التجربة التطويرية');
  $('product-panel').hidden = !['owner','inventory'].includes(user.role);
  $('team-panel').hidden = user.role !== 'owner'; $('audit-panel').hidden = user.role !== 'owner';
  tableRows('products', await api('/api/products'), ['sku','name','unit','sale_price','reorder_level']);
  if (user.role === 'owner') {
    tableRows('team', await api('/api/users'), ['name','email','role']);
    const entries = await api('/api/audit-logs'); $('audit').replaceChildren();
    entries.forEach(entry => { const li = document.createElement('li'); li.textContent = `${new Date(entry.created_at).toLocaleString()} · ${entry.action} · ${entry.entity_type} #${entry.entity_id}`; $('audit').append(li); });
  }
}
function submit(id, handler) {
  $(id).addEventListener('submit', async event => {
    event.preventDefault(); message(); const form = event.currentTarget; const button = form.querySelector('button'); button.disabled = true;
    try { await handler(Object.fromEntries(new FormData(form)), form); }
    catch (error) { message(error.message, true); }
    finally { button.disabled = false; }
  });
}
submit('register-form', async (data, form) => { data.language = language; const result = await api('/api/auth/register', data); token = result.access_token; form.reset(); await refresh(); });
submit('login-form', async (data, form) => { const result = await api('/api/auth/login', data); token = result.access_token; form.reset(); await refresh(); });
submit('product-form', async (data, form) => { await api('/api/products', data); form.reset(); await refresh(); message(t('Product saved.', 'تم حفظ المنتج.')); });
submit('team-form', async (data, form) => { await api('/api/users', data); form.reset(); await refresh(); message(t('Employee added.', 'تمت إضافة الموظف.')); });
$('show-register').addEventListener('click', () => { location.hash = 'register'; });
$('show-login').addEventListener('click', () => { location.hash = 'login'; });
$('logout').addEventListener('click', () => { logout(); message(t('Signed out.', 'تم تسجيل الخروج.')); });
$('language').addEventListener('click', async () => { language = language === 'en' ? 'ar' : 'en'; translate(); if (token) { try { await refresh(); } catch (error) { message(error.message, true); } } });
window.addEventListener('hashchange', showAuth);
translate(); showAuth();
