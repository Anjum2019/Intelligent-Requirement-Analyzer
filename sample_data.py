"""Realistic sample analysis so the UI can be explored without an API key.

The text is written in the same Markdown shape the LLM is prompted to return,
so the parsers and exporters are exercised exactly as with a live analysis.
"""

SAMPLE_META = {
    "project": "Loan Management System",
    "source": "SRS_Loan_Management_System.pdf",
    "pages": 42,
    "characters": 14850,
    "model": "openai/gpt-oss-120b (Groq)",
}

SAMPLE_STORIES = """### User Stories

- **US-01** As a loan officer, I want to log in with my credentials, so that I can access only my assigned applications.
- **US-02** As a loan officer, I want to create a new loan application with applicant and financial details, so that the application enters the workflow.
- **US-03** As a loan officer, I want the system to calculate EMI and validate the maximum loan amount, so that ineligible requests are flagged early.
- **US-04** As a credit analyst, I want to view the credit-score grid and verification checklist, so that I can decide eligibility with full context.
- **US-05** As a loan officer, I want to upload supporting documents in bulk, so that the file is complete before verification.
- **US-06** As a verification officer, I want to approve or reject each document, so that only verified documents move forward.
- **US-07** As a loan officer, I want to generate the sanctioning agreement as a PDF, so that the customer receives a formal offer.
- **US-08** As a customer, I want to review and e-sign the loan agreement, so that acceptance is recorded without paperwork.
- **US-09** As a finance manager, I want to review and approve the agreement, so that disbursement is authorised.
- **US-10** As an auditor, I want a complete audit trail of every status change, so that compliance reviews are possible.
- **US-11** As a branch manager, I want dashboard tiles with pending counts by stage, so that bottlenecks are visible at a glance.
- **US-12** As a loan officer, I want to export the monthly disbursement report, so that reporting to head office is quick.
"""

SAMPLE_ACCEPTANCE = """### Acceptance Criteria

- **AC-01** Given a loan officer is logged in, When they submit the application form with valid data, Then the application is saved with status "Submitted" and a unique Loan ID is generated.
- **AC-02** Given an applicant's requested amount exceeds the maximum eligible loan, When the officer submits the form, Then the system shows a validation error and the application is not saved.
- **AC-03** Given a credit analyst opens the eligibility view, When the credit-score service returns a score below 650, Then the application is marked "Needs Review" and the analyst is notified.
- **AC-04** Given a verification officer uploads 5 documents, When one document fails the virus scan, Then the upload is blocked and the officer sees which file failed.
- **AC-05** Given all documents are verified, When the officer clicks "Generate Sanction Letter", Then a PDF is generated and attached to the application.
- **AC-06** Given a customer receives the agreement link, When they e-sign within 7 days, Then the agreement status becomes "Customer Approved".
- **AC-07** Given the finance manager approves the agreement, When disbursement is triggered, Then the loan status becomes "Disbursed" and an audit entry is written.
- **AC-08** Given an auditor opens the audit trail, When they filter by Loan ID, Then all status changes with user, timestamp and reason are listed in order.
"""

SAMPLE_TESTCASES = """### Test Cases

| ID | Scenario | Steps | Expected Result | Priority |
| --- | --- | --- | --- | --- |
| TC-001 | Successful officer login | 1. Open login page 2. Enter valid credentials 3. Submit | Dashboard opens with officer's queue | High |
| TC-002 | Login with wrong password | 1. Enter valid username 2. Enter wrong password 3. Submit | Error message shown, account locked after 5 attempts | High |
| TC-003 | Create loan application | 1. Open new application 2. Fill applicant + financial details 3. Save | Application saved with unique Loan ID and status Submitted | High |
| TC-004 | EMI calculation accuracy | 1. Enter principal, rate, tenure 2. Save | EMI matches standard amortisation formula to 2 decimals | Medium |
| TC-005 | Max loan validation | 1. Enter amount above eligibility limit 2. Save | Validation error, application not saved | High |
| TC-006 | Bulk document upload | 1. Select 5 files 2. Upload | All files listed with scan status; infected file blocked | High |
| TC-007 | Document verification flow | 1. Open verification grid 2. Approve all docs 3. Submit | Application moves to Sanction stage | Medium |
| TC-008 | Sanction letter PDF generation | 1. Click Generate 2. Download PDF | PDF contains merged applicant data and terms | Medium |
| TC-009 | Customer e-sign | 1. Open agreement link 2. Sign 3. Confirm | Status becomes Customer Approved with timestamp | High |
| TC-010 | Audit trail completeness | 1. Filter audit by Loan ID 2. Review entries | Every status change present with user and reason | Medium |
"""
