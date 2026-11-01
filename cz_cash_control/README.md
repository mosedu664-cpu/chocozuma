# cz_cash_control — Choco Zuma Cash Control (Kasa Köprüsü)

Replaces the branch "kasa" Excel sheets with a controlled, auditable flow inside Odoo 18.

## Roles

| Who | Where | What they can do |
|---|---|---|
| Cashier | POS → **Masraf** button | Cash out with a fixed category (taxi, fuel, food, daily wage, market, cleaning, transfer to safe…), staff member, receipt no. Never sees accounts, cannot edit/delete afterwards. |
| Branch manager | POS PIN / Cash Control → Branch Safes | Authorises sensitive movements with his PIN (pos_hr), records safe movements (salaries, advances, rent, bank deposit), counts the safe. |
| Accountant | Cash Control → Daily Cash Sheets | Reviews one sheet per branch per day, fixes categories, decides what to do with a difference, **Approve & Post**. Nothing hits the books before that. |

## Flow

1. **During the day** – every drawer movement goes through POS *Cash In/Out* with a category.
   Rules per category: staff required, receipt no. above X, manager PIN, max amount.
   The movement is a normal `account.bank.statement.line` on the POS cash journal
   (so Odoo's expected cash at closing is always right) with `cz_category_id`.
2. **Closing** – blind count (expected hidden). *Gün Sonu* button: the whole counted
   drawer is moved to the safe with one manager PIN and the register closes at 0;
   the difference stays exactly counted − expected and the sheet shows the
   pre-transfer figures. Otherwise standard close. Count = 0 with cash sales, or
   |difference| > threshold → closing note + manager PIN. Odoo posts its own
   difference line as usual.
3. **Daily Cash Sheet** (`cz.cash.day`) – auto-created per POS per business day
   (sessions opened before 04:00 belong to the previous day). Shows opening,
   cash sales, expenses by category, safe transfers, expected, counted, difference,
   alerts, Excel parallel-run figures.
4. **Approve & Post** – for each movement the suspense leg is replaced by the
   category account (same mechanism as the reconciliation widget). Safe transfers
   go through the safe's *transfer clearing account* and a mirrored **Safe
   Movement** (type *in*) is created in the safe journal, so the clearing account
   nets to zero and the safe balance is live. Difference options: keep (profit/loss),
   "cash went to the safe without a cash-out" (re-points the difference and feeds the
   safe), or reclassify to another account.
5. **Safe** (`cz.cash.safe`) – one per branch, wraps the safe cash journal.
   Balance = posted lines of the safe journal. Manager movements are drafts until
   the accountant approves. Count = movement of type *count*, difference booked to
   the journal profit/loss accounts.
6. **Cron (06:30)** – refresh open sheets, chase sheets unapproved for 2+ days,
   safe alerts (balance above threshold, not counted for 7+ days).

## POS ergonomics (18.0.1.2.0)

* **Category tiles** – icon + colour per category (`icon` = FontAwesome 4 class,
  `color` = Odoo palette 0-11); categories that need a manager PIN have a red border.
* **Smart order** – tiles sorted by 30-day usage (`usage_count`), the 8 most used are
  shown, the rest behind *Diğer (n)*.
* **Repeat chips** – `pos.session.cz_recent_moves(config_id)` returns the last distinct
  movements (category, staff, amount, reason); one tap pre-fills the popup. Every rule
  (PIN, receipt, cap) still applies on confirm.
* **Receipt photo** – camera button next to the receipt number (`<input capture>`), the
  picture is downscaled in the browser (≤1280 px JPEG) and stored in
  `account.bank.statement.line.cz_receipt_image`; a photo satisfies the "receipt above X"
  rule. The accountant opens it from the daily sheet (camera icon on the line).
* **Gün Sonu** is optional per POS (`cz_enable_eod`, off by default — Mo's choice: the
  cashier only counts, transfers go through *Masraf → Küçük Kasaya Aktar*).
* **Gün Sonu slip** – after the manager PIN the cashier types the envelope / bag number
  (optional, stored in `cz_envelope_ref` and in the closing note); the slip
  (`CzEodReceipt`, data from `pos.session.cz_eod_summary`) prints opening, cash sales,
  expenses by category, in-day safe transfers, expected, counted, difference,
  transferred amount, cashier, manager, signatures. A printer problem never blocks the closing.

## Back office (18.0.1.2.0)

* **Cash Control → Dashboard** – one tile per POS: today's cash sales / drawer expenses /
  to safe, safe balance, last closing difference, 30-day expenses, sheets waiting for
  approval, alerts; buttons to today's sheet, approvals, 30-day graph, safe.
* **Reporting → 30-day Graph** – stacked bar of drawer expenses by category per day.
* **Reporting → Staff Expenses (Monthly)** – pivot staff × category (taxi, food, advances…)
  on the statement lines, with filters *without receipt / photo*, approved / not approved.

## Setup checklist (per branch)

1. Install, then *Cash Control → Configuration → Cash Categories*: create the
   categories for the company with their counterpart accounts
   (expenses 7701xx–7704xx, transfer = internal transfer clearing, refund = 610000).
2. *Cash Control → Branch Safes*: create the safe → safe cash journal, transfer
   clearing account (same as the transfer category account), responsible manager.
3. POS → Settings → *Choco Zuma Cash Control*: enable, pick the safe, thresholds,
   accountants/managers to notify. The POS must have a cash payment method with
   cash count enabled (`cash_control`).
4. Give the branch manager employee a PIN in pos_hr and role *Manager*.
   Set an `icon` / `color` on each category (the 18.0.1.2.0 migration fills them for the
   standard codes).
5. Users: accountants → group *Cash Accountant (Approve)*; branch managers →
   *Branch Manager (Safe)* and set as responsible on their safe.
6. Parallel run: keep the Excel for two weeks, type its CASH SALES into the sheet's
   *Excel* fields; the alert shows any gap.

## Design notes

* No new journals, no new accounts: everything lands in the existing POS cash
  journal and safe cash journal, in the company's own chart.
* Statement lines approved by the accountant are frozen (`cz_approved`).
* Multi-company safe: all models carry `company_id`, record rules restrict
  managers to their own safes.
* Server-side validation of every POS rule (`_cz_validate_cash_move`) — the POS UI
  is a convenience, not the guard.
