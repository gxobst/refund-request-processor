
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
                  Refund Request Intake (POST /refunds)
                                    ↓
                           intake_validate_node
                                    ↓
                         classifier_node (Agent)
                                    ↓
                           route_classifier
                            /               \
   (low conf & count < 2)  /                 \  (confident or count >= 2)
                          ↓                   ↓
                 clarification_node     policy_checker_node (Agent)
                          ↓             (tools: FedEx, Stripe, Multimodal Vision)
               awaiting_clarification         ↓
                    (pauses at END)    route_policy_check
                          |              /     |     \
               (POST /clarify or        /      |      \
               POST /evidence resumes) /       |       \
                          \           /        |        \
                           \         / (unproven/mismatch) \ (pass/fail/proof)
                            \       /          |          \
                             v     v           v           v
                          classifier     clarification   decision_node (Agent)
                                               ↓             /     |     \
                                    awaiting_clarification  /      |      \
                                                           v       v       v
                                                   auto_approve   deny   escalate
                                                           ↓       ↓       ↓
                                                   approval_email denial_email DynamoDB
                                                           ↓       ↓       ↓
                                                          END     END     END
```

### Conditional Routing Edges

1. **Classifier Router (`route_classifier`)**:
   - If classifier confidence `< 0.70` and `clarification_count < 2`: routes to `clarification_node`, which crafts a customer inquiry and pauses in `status: "awaiting_clarification"`.
   - If classifier confidence `< 0.70` and `clarification_count >= 2`: routes to `decision_node` for supervisor escalation (`decision: "escalate"`).
   - If classifier confidence `>= 0.70`: routes to `policy_checker_node`.

2. **Policy Checker Router (`route_policy_check`)**:
   - If a product mismatch is detected, or if a `damaged` or `wrong_item` claim lacks photo proof, and `clarification_count < 2`: routes to `clarification_node` to request customer clarification or evidence.
   - If policy status is `pass`, `fail`, or `ambiguous` with attached proof: routes to `decision_node`.

3. **Decision Router (`route_decision`)**:
   - If `decision == "auto_approve"`: routes to `approval_notifier` to generate formal approval email text with a unique RMA code.
   - If `decision == "deny"`: routes to `denial_notifier` to generate empathetic denial email text with policy reasoning.
   - If `decision == "escalate"`: terminates at `END` in `status: "escalated"` awaiting supervisor review.

### State Persistence & Resumption

Use a DynamoDB checkpointer (`RefundCheckpoints` table) so interrupted or paused workflows can be resumed seamlessly upon customer clarification or evidence upload.

---

## 8. Data Storage

Use Amazon DynamoDB for:

- Refund requests table (`RefundRequests`):
  - `refund_id`, `order_id`, `customer_request_text`, `status`, `decision`, `reasoning`
  - `matched_policy_rule`, `confidence_score`, `category`
  - `clarification_prompt`, `clarification_response`, `clarification_count`
  - `clarification_history`: structured array of `ClarificationTurn` objects
  - `evidence`: array of uploaded photo metadata (`id`, `filename`, `content_type`, `storage_path`, `uploaded_at`)
  - `tool_calls`: structured array of `ToolCallAudit` objects (carrier tracking and Stripe lookups)
  - `approval_email_text`, `denial_email_text`, `clarification_email_text`
  - `override_decision`, `override_reason`, `overridden_at`
  - `created_at`, `updated_at`
- Mock orders table (`MockOrders`): seeded from static JSON data (`orders.json`)
- LangGraph checkpoints table (`RefundCheckpoints`): serialized workflow execution state

---

## 9. UI Scope

### Stack

- Frontend: React + Vite + Tailwind CSS
- Backend: FastAPI + Pydantic

### UI Features

The back-office interface provides:

- Refund queue table with status filters (`pending`, `completed`, `escalated`, `awaiting_clarification`)
- Decision badges (`Approved`, `Denied`, `Escalated`, `Awaiting Clarification`)
- Detailed reasoning, matched policy rules, and classifier confidence scores
- Customer evidence gallery displaying uploaded damage/item photos
- Clarification history audit trail inspector
- External tool verification execution audit view (FedEx carrier events & Stripe payment logs)
- Manual supervisor actions:
  - Override to `Approve` or `Deny` with mandatory reasoning
  - Request Customer Proof (`POST /refunds/{id}/request-proof`) with targeted instructions

---

## 10. API Behavior

The application exposes asynchronous REST APIs with Swagger UI OpenAPI documentation:

### API Endpoints

```text
POST /refunds                      # Submit refund request (JSON or multipart with initial evidence)
GET  /refunds                      # List refunds (with optional ?status= filter)
GET  /refunds/{id}                 # Get detailed refund record with full audit trails
POST /refunds/{id}/override        # Supervisor manual override (approve / deny)
POST /refunds/{id}/clarify         # Customer clarification response (JSON or multipart with evidence)
POST /refunds/{id}/evidence        # Multipart image evidence upload (auto-resumes paused workflows)
POST /refunds/{id}/request-proof   # Supervisor proof inquiry (transitions escalated to awaiting_clarification)
GET  /health                       # Service health check
```

---

## 11. AWS and Model Strategy

### AWS Bedrock Model Configuration

- **Model ID**: `us.amazon.nova-2-lite-v1:0` (Amazon Nova 2 Lite via Bedrock Converse API)
- **Thinking / Reasoning**: Configured with `reasoningConfig: {"type": "enabled", "budget_tokens": 1024}` for deep policy evaluation and audit synthesis.
- **Strict Temperature Rule**: Bedrock requires `temperature=1.0` (or omitting temperature) when `reasoningConfig` is enabled on Amazon Nova models; non-1.0 values trigger AWS Bedrock `ValidationException`.
- **Multimodal Capabilities**: Native support for image bytes (`image/jpeg`, `image/png`, `image/webp`) in Converse API content blocks for visual damage inspection and product verification.

### AWS Cloud Architecture

- **AWS Bedrock**: LLM inference, structured output generation, and multimodal vision
- **AWS DynamoDB**: Operational persistence (`RefundRequests`, `MockOrders`, `RefundCheckpoints`)
- **Amazon S3**: Secure object storage for customer evidence images with local filesystem fallback
- **LangSmith**: Distributed observability, prompt tracking, and multi-turn tool tracing (EU region)

---

## 12. Observability

Use LangSmith for tracing:

- Detailed inputs, system prompts, and structured outputs per agent
- Autonomous tool execution traces (FedEx tracking events and Stripe charges)
- Multimodal Bedrock vision inference traces
- Workflow routing and pause/resume lifecycle transitions

---

## 13. Evolution from Initial MVP Scope

The initial MVP definition set several features out of scope that were subsequently incorporated as production-grade requirements:

- **Customer Communication Emails**: Automated generation of RMA-backed approval emails and policy-justified denial notices.
- **Multimodal Customer Evidence Uploads**: Full multipart image intake, evidence storage (S3/local), and Bedrock visual inspection.
- **Autonomous External Tool Verifications**: FedEx carrier tracking and Stripe payment lookup with dual-verification mandates for high-value orders.
- **Human-in-the-Loop Clarification Engine**: Two-turn customer clarification loop and supervisor-directed proof inquiries.

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

### 15.9 Mandatory Damage Proof Precedence over Order Amount Escalation
- **Proof-First Evaluation Order**: For `category == "damaged"`, the check for attached photo evidence strictly precedes the `max_order_amount` threshold check.
- **Queue Protection**: If a high-value damaged item claim lacks photos, it pauses in `status: "awaiting_clarification"` to collect customer photo proof rather than escalating directly to human supervisors. Only after photo evidence is attached is the amount threshold evaluated for supervisor escalation.

### 15.10 Automatic Background Workflow Resumption on Evidence Upload
- **Zero-Friction Customer Experience**: Calling `POST /refunds/{refund_id}/evidence` on a refund in `status: "awaiting_clarification"` automatically enqueues background workflow execution (`resume_refund_workflow`) via FastAPI `BackgroundTasks`.
- **Status Transition**: Immediately updates status to `"pending"` and resumes Bedrock evaluation without requiring the customer to submit a separate text call to `POST /refunds/{refund_id}/clarify`.

### 15.11 Mandatory Photo Proof for Wrong Item Category Claims
- **Proof Requirement**: Similar to physical damage claims, `category == "wrong_item"` claims unconditionally require photo proof before evaluation.
- **Clarification Routing**: Claims submitted without photos pause in `status: "awaiting_clarification"` with `failed_rules: ["wrong_item_verification"]`, prompting the customer for clear photos of the incorrect item received along with the shipping label or packing slip.

### 15.12 Structured Clarification History Audit Trail
- **Audit Logging**: Added `clarification_history: list[ClarificationTurn]` to `RefundRecord` and API response schemas.
- **Turn Immutability**: Each clarification cycle or supervisor proof inquiry appends a structured record containing `cycle`, `prompt`, `response`, `timestamp`, and `evidence_ids`, preserving the complete multi-turn audit trail across all clarification interactions.

### 15.13 Multimodal Bedrock Vision Verification for Wrong Item Claims
- **Visual Discrepancy Inspection**: When customer photo evidence is attached to a `wrong_item` claim, Policy Checker invokes multimodal Bedrock vision to compare the received item appearance, model, packaging, and shipping label against the ordered product specifications.
- **Tri-State Resolution**:
  - Distinct incorrect item verified -> `policy_status: "pass"` (auto-approved, or escalated if amount limits apply).
  - Depiction of correct ordered item -> `policy_status: "fail"` (denied with refutation reasoning).
  - Blurry, unrecognizable, or inconclusive evidence -> `policy_status: "ambiguous"` (escalated for human supervisor review).

### 15.14 Bedrock Nova 2 ReasoningConfig & Strict Temperature Compatibility
- **Thinking Budget Configuration**: The primary model `us.amazon.nova-2-lite-v1:0` enables deep policy evaluation via `reasoningConfig: {"type": "enabled", "budget_tokens": 1024}`.
- **Strict Temperature Rule**: AWS Bedrock requires `temperature=1.0` (or omitting temperature) whenever `reasoningConfig` is active on Amazon Nova models. Supplying lower temperatures (e.g. `0.0` or `0.2`) causes an immediate Bedrock `ValidationException`. All LLM factory methods and agent invocations strictly enforce this invariant.

### 15.15 External Tool Execution Tracing & Multi-Turn Audit Log
- **Audit Logging**: Every autonomous invocation of external tools (`query_carrier_tracking`, `query_payment_transaction`) is permanently recorded in `RefundRecord.tool_calls: list[ToolCallAudit]`.
- **Recorded Metadata**: Captures tool name, input arguments, raw tool output payload, execution duration, and ISO timestamps, providing complete non-repudiation and auditability for financial reviews.

### 15.16 Unmasked Exception Handling & Ambiguity Surfacing in Policy Evaluation
- **Error Preservation**: When tool loop execution or LLM synthesis encounters unhandled exceptions (carrier API outages, malformed responses, network timeouts), Policy Checker avoids masking errors behind static pass strings.
- **Ambiguity Routing**: Trapped exceptions yield `policy_status: "ambiguous"` with explicit diagnostic reasoning (`External verification failed: <error>`), preventing false-positive auto-approvals during infrastructure degradation.

### 15.17 Hybrid S3 and Local Filesystem Evidence Storage
- **Dual-Backend Storage**: `EvidenceStorageService` provides seamless binary persistence across environments. In production with AWS credentials, customer photos are persisted to Amazon S3. In offline local environments, CI runs, or when S3 is unreachable, the service transparently falls back to local filesystem storage in `backend/uploads/`.
- **Consistent Interface**: All metadata schemas, URI references (`storage_path`), and binary retrieval APIs operate identically regardless of whether the physical backing store is S3 or local disk.

### 15.18 Resilient Multipart Form Boundary Parsing & Swagger UI Integration
- **Boundary Robustness**: Custom multipart parsing (`_parse_multipart_request`) handles case-insensitive headers, irregular boundary quotes, and diverse client encodings across Swagger UI, curl, and modern web browsers.
- **Interactive OpenAPI Schemas**: Endpoints accepting file uploads (`/refunds`, `/refunds/{id}/clarify`, `/refunds/{id}/evidence`) configure explicit dual-content-type OpenAPI schemas (`application/json` and `multipart/form-data`) enabling native file upload widgets in interactive Swagger UI.