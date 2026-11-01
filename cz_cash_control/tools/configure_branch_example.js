// Run in a browser tab logged into the target Odoo DB (staging first, then production).
// Idempotent: looks up existing records by code/name before creating.
window.rpc = async (model, method, args=[], kwargs={}) => { const r = await fetch('/web/dataset/call_kw',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{model,method,args,kwargs:{context:{allowed_company_ids:[10,9,2,1],lang:'en_US'},...kwargs}}})}).then(r=>r.json()); if(r.error) return {error:(r.error.data?.message||r.error.message), debug:(r.error.data?.debug||'').split('\n').slice(-5).join('\n')}; return r.result;};
const out = {};
const C10 = 10;             // METROKENT ŞUBESİ (branch of Mayapan)
const POS = 13;             // Choco Zuma Metrokent
const SAFE_JOURNAL = 155;   // "kuçuk kasaya" cash journal (company 10)
const USER_MANAGER = 11;    // Kayasehir manager (Zeynep Berre Alay)
const USERS_ACCT = [14, 7]; // Esmaa, muhamed
const EMP_MANAGER = 39;     // hr.employee "Zeynep Berre Alay" (Metrokent)

const acc = async (code) => { const r = await rpc('account.account','search_read',[[['code','=',code],['company_ids','in',[9]]]],{fields:['id'],context:{allowed_company_ids:[9]}}); if(!r.length) throw new Error('missing account '+code); return r[0].id; };
const A = {};
for (const c of ['999000','770302','770301','770108','770105','770308','770310','770305','610000','136001','770101','770201','770106','770202','103001','320000','770306','770303','770304']) A[c] = await acc(c);
out.accounts = A;

// 1. Safe
let safe = await rpc('cz.cash.safe','search',[[['journal_id','=',SAFE_JOURNAL]]]);
if (!safe.length) {
  safe = [await rpc('cz.cash.safe','create',[{name:'Metrokent Küçük Kasa', company_id:C10, journal_id:SAFE_JOURNAL, transfer_account_id:A['999000'], responsible_id:USER_MANAGER, max_balance_alert:150000}])];
}
out.safe = safe[0];

// 2. Categories (POS-visible first, then safe-only)
const CATS = [
  // code, name, kind, account, opts
  ['TAKSI',   'Taksi',                 'expense',       '770302', {icon:'fa-taxi', color:3, requires_employee:true, typical_amount:350, sequence:1}],
  ['BENZIN',  'Benzin / Yakıt',        'expense',       '770301', {icon:'fa-car', color:2, requires_employee:true, typical_amount:400, sequence:2}],
  ['YEMEK',   'Personel Yemek',        'expense',       '770108', {icon:'fa-cutlery', color:10, requires_employee:true, typical_amount:300, sequence:3}],
  ['GUNLUK',  'Günlük Ödeme (bulaşıkçı / kurye)', 'expense', '770105', {icon:'fa-user-circle-o', color:7, requires_employee:true, typical_amount:1500, pin_above:2000, sequence:4}],
  ['MARKET',  'Market / Manav Alışverişi', 'expense',   '770308', {icon:'fa-shopping-basket', color:4, requires_receipt_above:300, typical_amount:400, sequence:5}],
  ['TEMIZLIK','Temizlik Malzemesi',    'expense',       '770310', {icon:'fa-tint', color:4, requires_receipt_above:300, sequence:6}],
  ['TAMIR',   'Tamir / Bakım',         'expense',       '770303', {icon:'fa-wrench', color:8, requires_receipt_above:0, requires_pin:true, sequence:7}],
  ['DIGER',   'Diğer Masraf',          'expense',       '770305', {icon:'fa-question-circle', color:0, requires_pin:true, sequence:8}],
  ['IADE',    'Müşteriye Nakit İade',  'refund',        '610000', {icon:'fa-undo', color:6, requires_pin:true, sequence:9}],
  ['AVANS',   'Personel Avans',        'advance',       '136001', {icon:'fa-hand-paper-o', color:9, requires_employee:true, requires_pin:true, max_amount:10000, sequence:10}],
  ['KASA',    'Küçük Kasaya Aktar',    'safe_transfer', '999000', {icon:'fa-archive', color:1, requires_pin:true, sequence:11}],
  ['KASADAN', 'Küçük Kasadan Bozukluk','cash_in',       '999000', {icon:'fa-plus-circle', color:10, direction:'in', requires_pin:true, sequence:12}],
  // safe-only (manager, backend)
  ['MAAS',    'Maaş Ödemesi',          'salary',        '770101', {icon:'fa-money', color:5, pos_available:false, requires_employee:true, sequence:20}],
  ['KIRA',    'Kira',                  'expense',       '770201', {icon:'fa-home', color:8, pos_available:false, sequence:21}],
  ['SGK',     'SGK / Vergi',           'expense',       '770106', {icon:'fa-institution', color:8, pos_available:false, sequence:22}],
  ['ELEKTRIK','Elektrik / Su / Gaz',   'expense',       '770202', {icon:'fa-bolt', color:3, pos_available:false, sequence:23}],
  ['TEDARIK', 'Tedarikçi Nakit Ödeme', 'other',         '320000', {icon:'fa-truck', color:7, pos_available:false, sequence:24}],
  ['BANKA',   'Bankaya Yatırma',       'bank_deposit',  '103001', {icon:'fa-university', color:8, pos_available:false, sequence:25}],
];
out.cats = {};
for (const [code, name, kind, account, opts] of CATS) {
  const ex = await rpc('cz.cash.category','search',[[['code','=',code],['company_id','=',C10]]]);
  const vals = Object.assign({name, code, kind, direction:'out', account_id:A[account], company_id:C10, pos_available:true}, opts);
  out.cats[code] = ex.length ? (await rpc('cz.cash.category','write',[ex, vals]), ex[0]) : await rpc('cz.cash.category','create',[vals]);
}

// 3. POS config
out.pos = await rpc('pos.config','write',[[POS],{cz_cash_control:true, cz_safe_id:out.safe, cz_blind_count:true, cz_zero_count_pin:true, cz_diff_pin_above:50, cz_cash_out_pin_above:5000, cz_opening_float:0, cz_accountant_ids:[[6,0,USERS_ACCT]], cz_manager_ids:[[6,0,[USER_MANAGER]]]}]);

// 4. Groups
const g = async (xmlid) => (await rpc('ir.model.data','check_object_reference',['cz_cash_control', xmlid]))[1];
const gAcct = await g('group_cz_cash_accountant'), gMgr = await g('group_cz_cash_manager'), gAdmin = await g('group_cz_cash_admin');
out.groups = await rpc('res.users','write',[USERS_ACCT,{groups_id:[[4,gAcct]]}]) && await rpc('res.users','write',[[USER_MANAGER],{groups_id:[[4,gMgr]]}]) && await rpc('res.users','write',[[2],{groups_id:[[4,gAdmin]]}]);

// 5. Manager employee in the Metrokent POS: link to the manager user so pos_hr gives the "manager" role; PIN set separately
out.emp = await rpc('hr.employee','write',[[EMP_MANAGER],{user_id:USER_MANAGER}]);
const posMgrGroup = (await rpc('pos.config','read',[[POS]],{fields:['group_pos_manager_id']}))[0].group_pos_manager_id[0];
out.posMgr = await rpc('res.users','write',[[USER_MANAGER],{groups_id:[[4,posMgrGroup]]}]);
out
