
# AI Refund Request Processor

## Goal

Build a back-office e-commerce tool that receives a refund request, evaluates it with a LangGraph multi-agent system, and produces one of three decisions:

- `auto_approve`
- `deny`
- `escalate`

The system uses:

- **LangGraph** for multi-agent orchestration and state management
- **AWS Bedrock** for LLM inference
- **AWS DynamoDB** for persistence and checkpointing
- **LangSmith** for agent tracing
- **React + FastAPI** for the back-office UI

---

## 1. Core Product Scope

### Input

The system accepts:

- Customer refund request text
- Mock order data

### Mock Order Fields

- `order_id`
- `item`
- `purchase_date`
- `order_amount`
- `delivery_date`
- `delivery_status`

---

## 2. Refund Reason Categories

The Classifier Agent supports:

- `damaged`
- `wrong_item`
- `changed_mind`
- `late_delivery`
- `missing_item`

---

## 3. Policy Checks

The Policy Checker Agent evaluates the request against a seeded policy table.

Policy dimensions:

- Reason-based refund window
- Delivery status check
- Order amount threshold

Example policy shape:

```json
{
  "damaged": {
    "refund_window_days": 30,
    "eligible_delivery_statuses": ["delivered"],
    "max_order_amount": 500
  }
}
```

Policies are loaded from a structured JSON file at startup.

---

## 4. Decision Output

For each refund request, the Decision Agent returns:

- `decision`: `auto_approve`, `deny`, or `escalate`
- `reasoning`: short explanation
- `matched_policy_rule`: the policy rule used
- `confidence_score`: model confidence

---

## 5. Escalation Rules

A request is escalated to human review if any of the following occur:

- Policy rule conflict
- Missing required order data
- Low classifier confidence

Escalated requests appear in the queue for manual review.

---

## 6. Agent Architecture

Use LangGraph for orchestration and state management.

### Agents

All agents use LLMs via AWS Bedrock.

#### 1. Classifier Agent

Responsibilities:

- Reads refund request text
- Returns refund category and confidence

Supported categories:

- `damaged`
- `wrong_item`
- `changed_mind`
- `late_delivery`
- `missing_item`

#### 2. Policy Checker Agent

Responsibilities:

- Reads classified reason and order data
- Checks request against policy JSON
- Returns one of:
  - `pass`
  - `fail`
  - `ambiguous`

#### 3. Decision Agent

Responsibilities:

- Combines classifier and policy outputs
- Produces final decision
- Returns:
  - decision
  - reasoning
  - matched policy rule
  - confidence score

---

## 7. LangGraph Workflow

```text
Refund Request
   ↓
Intake / Validate
   ↓
Classifier Agent
   ↓
Policy Checker Agent
   ↓
Decision Agent
   ↓
Escalate or Auto-Decide
   ↓
Save to DynamoDB
   ↓
UI Displays Result
```

### Conditional Edge

If the Policy Checker returns `ambiguous`, route the request to human escalation.

Otherwise, route the request to final automated decision.

### State Persistence

Use a DynamoDB checkpointer so interrupted or failed workflows can be resumed or retried.

---

## 8. Data Storage

Use Amazon DynamoDB for:

- Refund requests
- Order data
- Agent decisions
- Reasoning
- Matched policy rule
- Confidence score
- Escalation status
- LangGraph checkpoints

Initial mock orders are seeded from a static JSON file into DynamoDB.

---

## 9. UI Scope

### Stack

- Frontend: React
- Backend: FastAPI

### UI Features

The MVP includes:

- Refund queue table
- Decision badges:
  - Approved
  - Denied
  - Escalated
- Reasoning display
- Matched policy rule display
- Confidence score display
- Manual override action:
  - Approve
  - Deny

### Out of Scope for MVP UI

- Customer-facing portal
- Authentication
- Role-based access control
- File uploads
- Policy editor
- Analytics dashboard

---

## 10. API Behavior

The UI uses asynchronous processing.

### Expected Flow

1. Frontend submits refund request
2. Backend creates refund record
3. LangGraph workflow starts
4. Frontend polls status endpoint
5. Final decision appears in queue when complete

### Likely API Endpoints

```text
POST /refunds
GET /refunds
GET /refunds/{id}
POST /refunds/{id}/override
```

---

## 11. AWS and Model Strategy

Use:

- AWS Bedrock for LLM calls
- Same Bedrock model for all agents in MVP
- Model ID should be configurable via environment variable

AWS services:

- DynamoDB
- ECS / Fargate for deployment

---

## 12. Observability

Use LangSmith for tracing.

MVP tracing includes:

- Detailed inputs per agent
- Detailed outputs per agent
- Agent run traces
- Decision metadata where useful

---

## 13. Explicitly Out of Scope

The MVP does not include:

- Real e-commerce order system integration
- Payment processor refunds
- External notifications
- File or image uploads
- Customer authentication
- Admin policy editing UI
- Multi-tenant support
- Advanced analytics
- Production-grade audit controls

---

## 14. Success Criteria

The project is successful if:

1. A refund request with mock order data can be submitted.
2. The Classifier Agent categorizes the refund reason.
3. The Policy Checker Agent evaluates the request against seeded policies.
4. The Decision Agent returns a final decision with reasoning.
5. Ambiguous cases are escalated.
6. The UI displays the refund queue with decision badges and reasoning.
7. A human user can manually override a decision.
8. LangSmith shows detailed agent inputs and outputs.

---

## 15. Architectural & Business Decisions (Post-MVP Extensions)

This section records formal design decisions and business rule refinements adopted during development that extend beyond the initial plan:

### 15.1 Human-in-the-Loop Clarification Workflow
- **Intermediate Pause State (`awaiting_clarification`)**: When customer request text is ambiguous or classifier confidence is low (`< 0.70`), the workflow pauses execution rather than immediately escalating or deciding.
- **Clarification Turn Limit**: Maximum of 2 clarification cycles allowed (`clarification_count >= 2`). If ambiguity persists after 2 customer responses, the request automatically escalates to human review.
- **Resumption Endpoint**: Customer submits answers via `POST /refunds/{refund_id}/clarify` (JSON or multipart), which merges clarification text into state and resumes the LangGraph evaluation.
- **Diagnostics Persistence**: During clarification pause, the classifier's `category`, `confidence_score`, and `reasoning` are persisted to DynamoDB while leaving `decision: null` until final resolution.

### 15.2 Automated Customer Communication Emails
- **Approval Email & RMA Generation**: All approved claims automatically generate formal approval email text (`approval_email_text`) containing a unique Return Merchandise Authorization (RMA) code (e.g. `RMA-1007-XXXXXX`), an explicit 14-day return window deadline, packaging instructions, and shipping label guidelines.
- **Denial Email Generation**: Denied claims automatically generate an empathetic denial email (`denial_email_text`) detailing the specific policy violation (e.g., return window expiration) with customer support contact info, strictly excluding RMA numbers or return instructions.

### 15.3 External Verification Tools & High-Value Order Rule
- **Autonomous Multi-Turn Tool Calling**: The Policy Checker Agent dynamically invokes external audit tools when required:
  - `query_carrier_tracking`: Fetches carrier transit status, tracking events, and delivery timestamps for package delay or lost shipment claims.
  - `query_payment_transaction`: Inspects Stripe payment transaction status, charge amount, and dispute history.
- **Mandatory Dual Verification Threshold**: High-value claims (`order_amount >= $400.00`) strictly mandate autonomous execution of *both* external verification tools (carrier tracking and payment verification) before any approval can be granted.

### 15.4 Customer Evidence Upload Pipeline & Multimodal Vision
- **Image Upload Support**: Implemented multipart evidence uploads via `POST /refunds/{refund_id}/evidence`, clarification attachments via `POST /refunds/{refund_id}/clarify`, and upfront intake attachments via `POST /refunds`.
- **Media Whitelist & Size Limit**: Strictly restricted to image formats (`image/jpeg`, `image/png`, `image/webp`) with a strict 5MB maximum file size limit. Video uploads are rejected with HTTP 400.
- **Multimodal Bedrock Vision Agent**: For damage claims with attached images, the policy checker bypasses deterministic approval and invokes Bedrock's multimodal vision capabilities to inspect image bytes for physical damage.
- **Mandatory Proof for Damage**: Damage claims require physical proof. If no image proof is provided, requests must pause for clarification rather than auto-approving.

### 15.5 Reviewer Proof Inquiries from Escalation
- **Supervisor-Initiated Proof Requests**: Human reviewers inspecting escalated requests can trigger `POST /refunds/{refund_id}/request-proof` with a targeted inquiry.
- **Lifecycle Reset**: The refund transitions from `status: "escalated"` to `status: "awaiting_clarification"`, resets `decision: null`, increments clarification count, and generates an instructional email outlining supported image formats and upload instructions.

### 15.6 Order Amount Escalation vs. Denial
- **Threshold Escalation**: Orders exceeding the category maximum order amount threshold (`order_amount > max_order_amount`, e.g. $750 > $500 for damaged items) are *not* automatically denied. Instead, they route to `status: "escalated"` with `decision: "escalate"` and `policy_status: "ambiguous"` for human supervisor discretion.

### 15.7 Product Mismatch Discrepancy Handling
- **Order Item Reconciliation**: Customer refund claims referencing an explicit product that conflicts with the item in the order record (e.g., claiming for a "camera" on an order for a "Smart Fitness Watch") are detected by the intake and policy verification layer.
- **Clarification Routing**: Discrepancies prompt customer clarification to confirm which item from the order is being claimed for, preventing unintended auto-approvals.

### 15.8 Strict Input Validation Boundaries
- **Order ID Format**: Enforced strict regex format validation `^ORD-\d{4}$` across all API request models, rejecting lowercase prefixes (`ord-1001`), incorrect prefixes (`INV-1001`), or invalid digit counts with `HTTP 422 Unprocessable Entity`.