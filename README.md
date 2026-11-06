# Resolve for PayPal

### From refund promise to verified resolution.

Resolve is an AI-powered payment aftercare platform for PayPal merchants. It connects customer-support commitments with payment records, identifies incomplete refunds, and helps merchants coordinate authorized remedies.

A successful payment does not always mean a successful purchase. Resolve helps buyers and merchants understand what was agreed, what has happened, and what still needs to be done.

> **Status:** Early development. The repository has been initialized. The capabilities below describe the planned product.

## The Problem

When a purchase goes wrong, the information needed to resolve it is often scattered across:

- Customer-support conversations
- Order and return records
- Payment transactions
- Refund history
- Delivery evidence

A merchant may promise a refund without completing it. A refund may be partial, pending, or failed. Customers contact support repeatedly while teams reconstruct the same case.

Resolve aims to connect these records and track each commitment through to its outcome.

## How Resolve Works

1. **Capture the issue**
   Create a case from a customer complaint or support conversation.

2. **Identify the commitment**
   Extract the proposed or agreed remedy, amount, conditions, deadline, and source message.

3. **Connect the records**
   Match the case to the correct order, PayPal payment, and relevant evidence.

4. **Reconcile the outcome**
   Compare the agreement with completed and pending refund activity.

5. **Coordinate the next action**
   Request missing information or present an appropriate action for merchant approval.

6. **Verify and communicate**
   Track the payment outcome and maintain a shared resolution history.

## Example

A merchant agrees to refund a $100 purchase after receiving the return.

The return arrives, but only a $20 refund has completed.

Resolve checks for additional pending or completed refunds, identifies any remaining commitment, and presents the merchant with the next appropriate action.

After authorization, the system requests the eligible refund and tracks its reported outcome.

The buyer receives a resolution record showing:

- The agreed remedy
- Completed payment actions
- Outstanding conditions or amounts
- The next action and its owner

## Planned Features

### Commitment Tracking

- Extract refund commitments from support conversations.
- Preserve the original message and supporting evidence.
- Track conditions, deadlines, and revisions.
- Distinguish proposed remedies from accepted agreements.

### Payment Reconciliation

- Link commitments to PayPal payments.
- Track completed, partial, pending, and failed refunds.
- Identify incomplete outcomes.
- Calculate remaining amounts using deterministic backend logic.

### Resolution Coordination

- Request missing evidence.
- Present merchant-approved remedy options.
- Record buyer acceptance.
- Route exceptions to human review.

### Shared Resolution History

- Merchant case workspace
- Buyer status page
- Evidence timeline
- Action history
- Final resolution receipt

### Future Extensions

- Commerce and helpdesk integrations
- Return and replacement workflows
- Dispute evidence preparation
- Supported PayPal Disputes API workflows

## AI and Backend Responsibilities

AI will help interpret conversations, identify missing information, and explain recommendations.

Backend code will control:

- Payment and merchant identity checks
- Authorization
- Currency and amount validation
- Remaining refundable balance
- Pending refund checks
- Duplicate-action prevention
- Payment execution and status updates

An AI recommendation alone will not authorize a financial action.

## Planned Technology Stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js, React, TypeScript |
| Styling | Tailwind CSS, shadcn/ui |
| Backend | Python, FastAPI |
| Validation | Pydantic |
| Database | PostgreSQL through Supabase |
| Authentication | Supabase Auth |
| Evidence storage | Supabase Storage |
| AI integration | OpenAI API with structured outputs |
| Payment integration | PayPal REST APIs |
| Background processing | Python worker and Supabase Queues |
| Testing | pytest and Playwright |

Development begins with the backend.

## Proposed Repository Structure

```text
resolve/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── models/
│   │   ├── services/
│   │   └── integrations/
│   └── tests/
├── frontend/
├── docs/
└── README.md
```

This structure is a development plan and will evolve with the implementation.

## Development Roadmap

- [x] Initialize the repository
- [ ] Create the FastAPI application and health endpoint
- [ ] Define case, commitment, payment, and refund models
- [ ] Add database persistence
- [ ] Implement reconciliation using sample records
- [ ] Integrate PayPal Sandbox payments and refunds
- [ ] Add merchant authorization and duplicate-action protection
- [ ] Add AI commitment extraction
- [ ] Implement webhook verification and status reconciliation
- [ ] Build the merchant workspace and buyer status page
- [ ] Evaluate complete resolution workflows

## First Milestone

Complete one sandbox workflow:

```text
Payment
  → Customer complaint
  → Recorded refund commitment
  → Payment reconciliation
  → Merchant approval
  → Sandbox refund
  → Verified outcome
  → Resolution record
```

## Evaluation Plan

The initial evaluation will measure:

- Commitment-extraction accuracy
- Correct matching between cases and payments
- Detection of incomplete refund commitments
- Correct treatment of pending refunds
- Duplicate and excessive refund attempts blocked
- Recovery from interrupted payment requests
- Time to verified resolution

Any reported results will distinguish sample-data tests, sandbox behavior, and live merchant evidence.

## Project Scope

Resolve is an independent project designed to work with supported PayPal capabilities.

It assists merchants and buyers with resolution workflows. Formal dispute decisions remain with PayPal or the relevant financial institution.

Live merchant integrations will require the appropriate access, consent, and operational controls.