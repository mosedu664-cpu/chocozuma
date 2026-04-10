# -*- coding: utf-8 -*-
{
    'name': 'GoodSports Grant Management',
    'version': '18.0.2.0.0',
    'category': 'Nonprofit',
    'summary': 'Full grant lifecycle management + IRS Form 990 reporting for nonprofits',
    'description': """
        GoodSports Grant Management Module v2
        =======================================
        - Grant Opportunity Research & Pipeline
        - Grant Application Tracking (Pre-Award)
        - Award Management with Budget Control
        - Milestone & Deliverable Tracking
        - Expense Allocation per Grant (Analytic Integration)
        - Funder/Grantor CRM
        - Compliance Reporting & Dashboards
        - Grant Closure & Post-Award Reporting
        - IRS Form 990 System-Generated Annual Return
        - Form 990 Schedule I (auto-populated from Grant records)
        - Functional Expense Allocation (Part IX)
        - Program Accomplishments (Part III)
    """,
    'author': 'GoodSports Implementation Team',
    'website': 'https://www.goodsports.org',
    'depends': [
        'base',
        'mail',
        'account',
        'analytic',
        'project',
        'contacts',
        'crm',
        'hr_expense',
        'board',
    ],
    'data': [
        'security/grant_security.xml',
        'security/ir.model.access.csv',
        'data/grant_stage_data.xml',
        'data/grant_sequence_data.xml',
        'views/grant_views.xml',
        'views/grant_funder_views.xml',
        'views/grant_opportunity_views.xml',
        'views/grant_milestone_views.xml',
        'views/grant_expense_allocation_views.xml',
        'views/grant_report_views.xml',
        'views/form990_views.xml',
        'views/grant_menu_views.xml',
        'report/grant_status_report.xml',
        'report/grant_budget_report.xml',
        'report/form990_report.xml',
        'wizard/grant_close_wizard_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
