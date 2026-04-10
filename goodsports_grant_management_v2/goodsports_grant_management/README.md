# GoodSports Grant Management — Odoo v18 Custom Module

## Overview
Full grant lifecycle management module for nonprofit organizations, designed for GoodSports.org.
Modeled after industry-standard grant management workflows (comparable to NetSuite's grant management).

## Features

### 1. Funder / Grantor CRM
- Track grantor organizations (foundations, corporate, government, community)
- Relationship status, program officer contacts, focus areas
- Total awarded, active grant count per funder

### 2. Grant Opportunity Pipeline (Pre-Award)
- Kanban pipeline with configurable stages (Research → Eligibility → Writing → Review → Submitted)
- Deadline tracking with color-coded urgency alerts
- Eligibility scoring and strategic fit rating
- One-click conversion from Opportunity → Active Grant

### 3. Grant Management (Award & Active)
- Full lifecycle: Draft → Submitted → Under Review → Awarded → Active → Reporting → Closed
- Auto-creates Analytic Account on award for seamless expense tracking
- Budget line management by expense category (Personnel, Travel, Equipment, etc.)
- Variance tracking: budgeted vs. actual per line item
- Match/cost-share tracking

### 4. Milestone & Deliverable Tracking
- Define milestones with quantitative targets (e.g. "500 youth served")
- Achievement % calculation
- Milestone completion triggers payment status updates
- Overdue milestone alerts with dashboard badges

### 5. Payment Schedule
- Track payment tranches (advance, reimbursement, milestone-based, final)
- Link payments to milestone completion events
- Journal entry linkage to accounting

### 6. Compliance Reporting
- Report schedule management (progress, financial, combined, final)
- Overdue report tracking
- Report submission workflow with chatter logging

### 7. PDF Reports
- **Grant Status Report**: Per-grant printable summary with budget breakdown, milestone status, compliance notes
- **Grant Portfolio Report**: Cross-grant overview with totals, utilization %, overdue milestone table

### 8. Dashboards & Analytics
- Pivot view: awarded vs. spent by funder and status
- Bar chart: portfolio by funder
- Configurable search filters (overdue, closing soon, report due)

## Module Dependencies
- `account`, `analytic`, `project`, `mail`, `contacts`, `crm`, `hr_expense`, `board`

## Security Groups
| Group | Access |
|---|---|
| Grant User | Read + edit own assigned grants |
| Grant Manager | Create, edit all grants and opportunities |
| Grant Administrator | Full access + configuration |

## Installation
1. Copy module folder to your Odoo addons path
2. Update Apps list in Odoo Settings
3. Install "GoodSports Grant Management"
4. Configure Focus Areas and Pipeline Stages under Configuration menu
