// Kayaşehir (TONALLI, company 2, POS 6) — same cash-control set-up as Metrokent (company 10, POS 13).
// Run in a browser tab logged in as admin on the target DB: staging first, then production.
// Idempotent: everything is looked up by code / name first. The Kayaşehir register must be CLOSED
// (Odoo refuses to change a payment method while one of its sessions is open).
//
// What it does
//   1. "Cash" payment method of the Kayaşehir POS -> cash journal "Cash" (KASA, 100001) instead of the bank
//      journal "Sales Collections": the drawer becomes a real, counted cash drawer (like Metrokent "Nakit").
//   2. Branch safe on the journal "küçük kasaya" (SAFE, 100002), transfer account 999000.
//   3. Categories: copied one by one from Metrokent (same codes, rules, icons), accounts mapped by code.
//   4. pos.config flags copied from the Metrokent POS; accountants / manager to notify.
//   5. Groups, and the employees missing from the Kayaşehir staff list.
(async () => {
  const SRC_COMPANY = 10, SRC_POS = 13;          // Metrokent = the model
  const DST_COMPANY = 2, DST_POS = 6;            // TONALLI / "Choco Zuma kayaşehir"
  const DRAWER_JOURNAL_CODE = 'KASA';            // journal "Cash"            (account 100001)
  const SAFE_JOURNAL_CODE = 'SAFE';              // journal "küçük kasaya"    (account 100002)
  const CASH_METHOD_NAME = 'Cash';
  const SAFE_NAME = 'Kayaşehir Küçük Kasa';
  const USER_MANAGER = 11;                       // Kayasehir manager (Zeynep Berre Alay)
  const USERS_ACCT = [14, 7];                    // Esmaa, muhamed
  const NEW_STAFF = ['Yaman', 'Abdullah', 'Narin', 'Muhammed Numani', 'Hacı'];   // paid from the drawer, not in Employees yet
  const SHARED_LOGINS = ['M', 'X', 'kaya kasa garc'];                            // generic POS logins: never "the staff member"
  // Same categories as Metrokent, but TONALLI books these three differently all year (safe journal 2026):
  // advances on 135001, salaries against the payroll accrual 335001, rent against 336003.
  const ACCOUNT_OVERRIDE = { AVANS: '135001', MAAS: '335001', KIRA: '336003' };
  const SAFE_CAP = 30000;                                                        // owner's approval above this

  const ctx = { allowed_company_ids: [DST_COMPANY, SRC_COMPANY, 9, 1], lang: 'en_US', active_test: false };
  const rpc = async (model, method, args = [], kwargs = {}) => {
    const r = await fetch(`/web/dataset/call_kw/${model}/${method}`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { model, method, args, kwargs: { context: ctx, ...kwargs } } }) }).then(r => r.json());
    if (r.error) throw new Error(`${model}.${method}: ${r.error.data?.message || r.error.message}`);
    return r.result;
  };
  const out = { host: location.host, steps: [] };
  const step = (s) => out.steps.push(s);

  // ---- 0. guards
  const open = await rpc('pos.session', 'search_read', [[['config_id', '=', DST_POS], ['state', '!=', 'closed']]], { fields: ['name'] });
  if (open.length) throw new Error(`Close the Kayaşehir register first (${open.map(s => s.name).join(', ')} is open).`);
  const journal = async (code) => {
    const j = await rpc('account.journal', 'search_read', [[['code', '=', code], ['company_id', '=', DST_COMPANY], ['type', '=', 'cash']]],
      { fields: ['name', 'default_account_id', 'profit_account_id', 'loss_account_id'] });
    if (j.length !== 1) throw new Error(`cash journal ${code}: found ${j.length}`);
    if (!j[0].profit_account_id || !j[0].loss_account_id) throw new Error(`journal ${code} has no profit / loss account`);
    return j[0];
  };
  const drawerJ = await journal(DRAWER_JOURNAL_CODE), safeJ = await journal(SAFE_JOURNAL_CODE);
  const dstAcc = async (code) => {
    const a = await rpc('account.account', 'search_read', [[['code', '=', code], ['company_ids', 'in', [DST_COMPANY]]]], { fields: ['id'], context: { allowed_company_ids: [DST_COMPANY] } });
    if (a.length !== 1) throw new Error(`account ${code} in company ${DST_COMPANY}: found ${a.length}`);
    return a[0].id;
  };

  // ---- 1. cash payment method on the cash journal
  const pm = await rpc('pos.payment.method', 'search_read', [[['name', '=', CASH_METHOD_NAME], ['company_id', '=', DST_COMPANY], ['config_ids', 'in', [DST_POS]]]],
    { fields: ['journal_id', 'is_cash_count', 'outstanding_account_id'] });
  if (pm.length !== 1) throw new Error(`payment method "${CASH_METHOD_NAME}": found ${pm.length}`);
  if (pm[0].journal_id[0] !== drawerJ.id) {
    await rpc('pos.payment.method', 'write', [[pm[0].id], { journal_id: drawerJ.id, outstanding_account_id: false }]);
    step(`payment method ${CASH_METHOD_NAME}: journal ${pm[0].journal_id[1]} -> ${drawerJ.name}`);
  }
  out.cash_method = (await rpc('pos.payment.method', 'read', [[pm[0].id]], { fields: ['name', 'journal_id', 'is_cash_count', 'type'] }))[0];
  if (!out.cash_method.is_cash_count) throw new Error('cash method is still not a cash-count method');

  // ---- 2. safe
  const transferAcc = await dstAcc('999000');
  let safe = await rpc('cz.cash.safe', 'search', [[['journal_id', '=', safeJ.id]]]);
  if (!safe.length) {
    safe = [await rpc('cz.cash.safe', 'create', [{ name: SAFE_NAME, company_id: DST_COMPANY, journal_id: safeJ.id, transfer_account_id: transferAcc, responsible_id: USER_MANAGER, max_balance_alert: 150000 }])];
    step('safe created');
  }
  out.safe = safe[0];

  // ---- 3. categories: exact copy of the model branch
  const meta = await rpc('cz.cash.category', 'fields_get', [], { attributes: ['type', 'readonly', 'store'] });
  const COPY = Object.keys(meta).filter(n => meta[n].store !== false && !meta[n].readonly && !['id', 'company_id', 'account_id', 'currency_id', 'display_name'].includes(n)
    && !['one2many', 'many2many', 'many2one'].includes(meta[n].type) && !/^(create_|write_|message_|activity_)/.test(n));
  const srcCats = await rpc('cz.cash.category', 'search_read', [[['company_id', '=', SRC_COMPANY]]], { fields: [...COPY, 'account_id'], order: 'sequence, id' });
  const srcAcc = Object.fromEntries((await rpc('account.account', 'read', [[...new Set(srcCats.filter(c => c.account_id).map(c => c.account_id[0]))]],
    { fields: ['code'], context: { allowed_company_ids: [9, SRC_COMPANY] } })).map(a => [a.id, a.code]));
  out.categories = {};
  for (const c of srcCats) {
    const vals = Object.fromEntries(COPY.map(n => [n, c[n]]));
    if (!vals.max_amount && vals.safe_pos_available) vals.max_amount = SAFE_CAP;
    vals.company_id = DST_COMPANY;
    vals.account_id = c.account_id ? await dstAcc(ACCOUNT_OVERRIDE[c.code] || srcAcc[c.account_id[0]]) : false;
    const ex = await rpc('cz.cash.category', 'search', [[['code', '=', c.code], ['company_id', '=', DST_COMPANY]]]);
    if (ex.length) await rpc('cz.cash.category', 'write', [ex, vals]); else ex.push(await rpc('cz.cash.category', 'create', [vals]));
    out.categories[c.code] = ex[0];
  }
  step(`${srcCats.length} categories copied from company ${SRC_COMPANY}`);

  // ---- 3b. Kayaşehir only: found in its 2026 cash book, booked the way TONALLI's accountant books them today
  const EXTRA = [
    { code: 'CZADINA', name: 'Choco Zuma Adına Ödeme', kind: 'other', direction: 'out', account: '320000', requires_reason: true, requires_pin: true,
      pos_available: true, safe_pos_available: true, icon: 'fa-exchange', color: 9, sequence: 13,
      note: 'Choco Zuma (merkez) adına kasadan ödenen her şey: merkez personeline avans/taksi/yemek, pazarlama, depo kargosu… Açıklamaya KİM ve NE yazılır. Karşı hesap 320000 Suppliers — muhasebe onaydan önce satırda partner = CHOCO ZUMA seçer.' },
    { code: 'MUHASEBE', name: 'Muhasebeye / Merkeze Teslim', kind: 'other', direction: 'out', account: '100005', requires_reason: true,
      pos_available: false, safe_pos_available: true, icon: 'fa-briefcase', color: 8, sequence: 14,
      note: 'Küçük kasadan muhasebeye / merkeze teslim edilen nakit. Karşı hesap 100005 Internal Transfers (Clearing) — muhasebe paranın nereye gittiğine göre kapatır.' },
    { code: 'PAKET', name: 'Kurye Paket Başı', kind: 'expense', direction: 'out', account: '770107', requires_employee: true, typical_amount: 165,
      pos_available: true, safe_pos_available: false, icon: 'fa-motorcycle', color: 2, sequence: 4, note: 'Kuryeye paket başı ödeme. Karşı hesap 770107 Order delivery fees.' },
    { code: 'BAHSIS', name: 'Karttan Bahşiş / Fazla Çekim İadesi', kind: 'other', direction: 'out', account: '999000', requires_reason: true, requires_pin: true,
      pos_available: true, safe_pos_available: false, icon: 'fa-credit-card', color: 6, sequence: 9,
      note: 'Karttan fazla çekilen tutarın müşteriye nakit iadesi veya karttan çekilen bahşişin personele nakit ödenmesi. Satış iadesi DEĞİLDİR. Karşı hesap 999000.' },
  ];
  for (const { account, ...c } of EXTRA) {
    const vals = { ...c, account_id: await dstAcc(account), company_id: DST_COMPANY };
    const ex = await rpc('cz.cash.category', 'search', [[['code', '=', c.code], ['company_id', '=', DST_COMPANY]]]);
    if (ex.length) await rpc('cz.cash.category', 'write', [ex, vals]); else ex.push(await rpc('cz.cash.category', 'create', [vals]));
    out.categories[c.code] = ex[0];
  }
  // Nothing above SAFE_CAP leaves the drawer or the safe from the POS on the manager's PIN alone: a bigger payment is a
  // backend Safe Movement the accountant approves after the owner's OK. (Advances keep their own lower cap.)
  const capIds = await rpc('cz.cash.category', 'search', [[['company_id', '=', DST_COMPANY], ['safe_pos_available', '=', true], ['max_amount', '=', 0]]]);
  await rpc('cz.cash.category', 'write', [capIds, { max_amount: SAFE_CAP }]);
  step(`${EXTRA.length} Kayaşehir categories, ${capIds.length} categories capped at ${SAFE_CAP}`);

  // ---- 4. POS flags: same as the model POS
  const FLAGS = ['cz_blind_count', 'cz_zero_count_pin', 'cz_diff_pin_above', 'cz_cash_out_pin_above', 'cz_opening_float', 'cz_enable_eod', 'cz_show_recent', 'cz_digest_lang'];
  const src = (await rpc('pos.config', 'read', [[SRC_POS]], { fields: FLAGS }))[0];
  const flags = Object.fromEntries(FLAGS.map(f => [f, src[f]]));
  await rpc('pos.config', 'write', [[DST_POS], { ...flags, cz_cash_control: true, cz_safe_id: out.safe, cz_accountant_ids: [[6, 0, USERS_ACCT]], cz_manager_ids: [[6, 0, [USER_MANAGER]]] }]);
  out.pos = (await rpc('pos.config', 'read', [[DST_POS]], { fields: ['name', 'cash_control', 'cz_cash_control', 'cz_safe_id', ...FLAGS, 'cz_accountant_ids', 'cz_manager_ids'] }))[0];
  if (!out.pos.cash_control) throw new Error('Odoo cash control is still off on the POS');

  // ---- 5. groups + staff
  const g = async (xmlid) => (await rpc('ir.model.data', 'check_object_reference', ['cz_cash_control', xmlid]))[1];
  await rpc('res.users', 'write', [USERS_ACCT, { groups_id: [[4, await g('group_cz_cash_accountant')], [4, await g('group_cz_cash_manager')]] }]);
  await rpc('res.users', 'write', [[USER_MANAGER], { groups_id: [[4, await g('group_cz_cash_manager')]] }]);
  out.staff_added = [];
  for (const name of NEW_STAFF) {
    const ex = await rpc('hr.employee', 'search', [[['name', '=ilike', name], ['company_id', '=', DST_COMPANY]]]);
    if (!ex.length) { await rpc('hr.employee', 'create', [{ name, company_id: DST_COMPANY }]); out.staff_added.push(name); }
  }
  const empFields = await rpc('hr.employee', 'fields_get', [['cz_shared_login']], { attributes: ['type'] });
  if (empFields.cz_shared_login) {                                               // module >= 18.0.1.6.1
    const shared = await rpc('hr.employee', 'search', [[['name', 'in', SHARED_LOGINS], ['company_id', '=', DST_COMPANY]]]);
    await rpc('hr.employee', 'write', [shared, { cz_shared_login: true }]);
    step(`${shared.length} shared logins excluded from the staff list`);
  } else step('module < 18.0.1.6.1: shared logins (M, X, kaya kasa garc) still appear in the staff list');
  out.staff = (await rpc('pos.config', 'read', [[DST_POS]], { fields: ['cz_staff'], context: { allowed_company_ids: [DST_COMPANY] } }))[0].cz_staff.map(s => s.name);
  const s = (await rpc('cz.cash.safe', 'read', [[out.safe]], { fields: ['balance', 'expected_balance'] }))[0];
  out.safe_book_balance = s.balance;
  return out;
})()
