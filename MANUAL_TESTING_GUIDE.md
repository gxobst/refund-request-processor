# AI Refund Request Processor - Manual Testing Guide

This guide provides end-to-end test scenarios designed to verify all capabilities of the LangGraph multi-agent refund processing system directly via FastAPI Swagger UI at **`http://127.0.0.1:8000/docs`**.

---

## Prerequisites & Server Launch

1. Ensure dependencies are installed and the mock DynamoDB orders table is seeded:
   ```bash
   cd backend
   uv run python -m app.db.seed
   ```
2. Start the FastAPI development server:
   ```bash
   uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
3. Open your browser and navigate to:
   ```text
   http://127.0.0.1:8000/docs
   ```

---

## Summary Matrix of Test Scenarios

| Scenario # | Test Name | Key Mechanism Verified | Target Order | Expected Decision / Status |
| :---: | :--- | :--- | :---: | :---: |
| **TC-01** | System Health Check | DynamoDB & API connectivity | N/A | `status: "healthy"` (HTTP 200) |
| **TC-02** | Clear-Cut Approval & Return Email | Fast deterministic bypass + approval email with RMA | `ORD-1007` | `auto_approve` / `completed` |
| **TC-03** | Max Order Amount Denial | Deterministic constraint enforcement | `ORD-1003` | `deny` / `completed` |
| **TC-04** | Expired Return Window Denial | Date window policy evaluation | `ORD-1004` | `deny` / `completed` |
| **TC-05** | Single Tool Carrier Verification | Autonomous `query_carrier_tracking` tool call | `ORD-1005` | `auto_approve` / `completed` |
| **TC-06** | Dual Tool Verification (FedEx & Stripe) | High-value order dual external verification | `ORD-1010` | `auto_approve` / `completed` |
| **TC-07** | Clarification Loop Lifecycle | Low confidence pause -> customer response -> resolution | `ORD-1008` | `awaiting_clarification` -> `auto_approve` |
| **TC-08** | Clarification Exhaustion to Escalation | 2-cycle clarification exhaustion (low confidence < 0.70) -> human escalation | `ORD-1009` | `awaiting_clarification` (cycles 1 & 2) -> `escalate` / `escalated` |
| **TC-09** | Supervisor Manual Override | Supervisor manual override on escalated TC-08 refund (approve / deny) | `ORD-1009` | `approve` or `deny` / `completed` |
| **TC-10** | Multipart Damage Evidence Upload | Image file storage & metadata attachment | Any active refund | HTTP 201 (`evidence` array populated) |
| **TC-11** | Multimodal Image Inspection | Multimodal Bedrock vision agent verifies damage | `ORD-1001` | `auto_approve` (damage verified) |
| **TC-12** | Queue Listing and Filtering | DynamoDB querying with status filter | N/A | HTTP 200 (filtered list) |
| **TC-13** | Input Validation & Error Boundaries | Rejection of blank inputs, 404s, invalid files | N/A | HTTP 400, 404, 413, 422 |

---

## Detailed Test Cases

### TC-01: System Health & Connectivity Check
- **Endpoint**: `GET /health`
- **Goal**: Confirm backend server is up and DynamoDB table is reachable.
- **Input**: None (Click **Try it out** -> **Execute**).
- **Expected Status**: `200 OK`
- **Expected Output**:
  ```json
  {
    "status": "healthy",
    "timestamp": "2026-09-24T...",
    "dynamodb": "connected"
  }
  ```

---

### TC-02: Clear-Cut Policy Approval & Return Email Generation
- **Endpoint**: `POST /refunds` followed by polling `GET /refunds/{refund_id}`
- **Goal**: Verify fast deterministic pass for low-value requests within policy window, and confirm automated generation of approval email text with RMA and return instructions.
- **Input (`POST /refunds`)**:
  ```json
  {
    "order_id": "ORD-1007",
    "customer_request_text": "I changed my mind about this mouse. It is brand new and unopened in original packaging, I just do not need it anymore."
  }
  ```
- **Step 1 Expected Output (`POST /refunds`)**: `201 Created`
  ```json
  {
    "refund_id": "ref_...",
    "order_id": "ORD-1007",
    "status": "pending",
    "created_at": "..."
  }
  ```
  *(Copy the returned `refund_id` for Step 2)*.
- **Step 2 Input (`GET /refunds/{refund_id}`)**:
  - Wait 2–3 seconds for the async background worker.
  - Execute `GET /refunds/{refund_id}` using the copied `refund_id`.
- **Step 2 Expected Output**: `200 OK`
  - `status`: `"completed"`
  - `decision`: `"auto_approve"`
  - `confidence_score`: `>= 0.80`
  - `approval_email_text`: Non-null string containing:
    - Customer greeting
    - Confirmation that refund for `ORD-1007` is approved
    - Unique RMA number (e.g. `RMA-1007-...`)
    - 14-day return window deadline
    - Return packaging and mailing instructions

---

### TC-03: Hard Constraint Policy Denial (Max Order Amount Exceeded)
- **Endpoint**: `POST /refunds` followed by `GET /refunds/{refund_id}`
- **Goal**: Confirm that orders exceeding policy threshold (`$750.00 > $500.00` max limit for `damaged`) are deterministically denied without unneeded LLM tokens.
- **Input (`POST /refunds`)**:
  ```json
  {
    "order_id": "ORD-1003",
    "customer_request_text": "The gaming monitor arrived with a completely shattered OLED panel and cracked stand."
  }
  ```
- **Step 1 Expected Output**: `201 Created`
- **Step 2 (`GET /refunds/{refund_id}`) Expected Output**: `200 OK`
  - `status`: `"completed"`
  - `decision`: `"deny"`
  - `reasoning`: Contains `"max_order_amount"` failure explanation (order amount $750.00 exceeds $500.00 threshold).
  - `approval_email_text`: `null` (no return instructions for denied claims).

---

### TC-04: Date Window Policy Denial (Expired Return Window)
- **Endpoint**: `POST /refunds` followed by `GET /refunds/{refund_id}`
- **Goal**: Confirm that return requests filed beyond the policy window (`ORD-1004` purchased in August, > 30 days ago) are denied.
- **Input (`POST /refunds`)**:
  ```json
  {
    "order_id": "ORD-1004",
    "customer_request_text": "The keyboard spacebar stopped working properly. I would like a refund."
  }
  ```
- **Step 1 Expected Output**: `201 Created`
- **Step 2 (`GET /refunds/{refund_id}`) Expected Output**: `200 OK`
  - `status`: `"completed"`
  - `decision`: `"deny"`
  - `reasoning`: Identifies failed rule `"refund_window_days"`.

---

### TC-05: Carrier Logistics Verification via Autonomous Tool Calling
- **Endpoint**: `POST /refunds` followed by `GET /refunds/{refund_id}`
- **Goal**: Verify autonomous multi-turn tool calling where the Policy Checker invokes `query_carrier_tracking` for order `ORD-1005` (`in_transit`) to inspect FedEx tracking `TRK-1005`.
- **Input (`POST /refunds`)**:
  ```json
  {
    "order_id": "ORD-1005",
    "customer_request_text": "My standing desk converter was supposed to arrive last week but the package is still delayed and missing."
  }
  ```
- **Step 1 Expected Output**: `201 Created`
- **Step 2 (`GET /refunds/{refund_id}`) Expected Output**: `200 OK`
  - `status`: `"completed"`
  - `decision`: `"auto_approve"`
  - `tool_calls`: Contains an entry with:
    - `tool_name`: `"query_carrier_tracking"`
    - `tool_input`: `{"tracking_number": "TRK-1005"}`
    - `tool_output`: Contains carrier transit status and verified delay evidence.
  - `reasoning`: References carrier tracking findings confirming package delay beyond expected SLA.

---

### TC-06: Dual External Verification (FedEx Tracking & Stripe Charge)
- **Endpoint**: `POST /refunds` followed by `GET /refunds/{refund_id}`
- **Goal**: High-value claims (`ORD-1010`, $450.00 Camera) require autonomous multi-turn inspection of both carrier delivery proof (`query_carrier_tracking`) and payment dispute status (`query_payment_transaction`).
- **Input (`POST /refunds`)**:
  ```json
  {
    "order_id": "ORD-1010",
    "customer_request_text": "I ordered this mirrorless camera but received the wrong lens bundle. I would like to return it for a refund."
  }
  ```
- **Step 1 Expected Output**: `201 Created`
- **Step 2 (`GET /refunds/{refund_id}`) Expected Output**: `200 OK`
  - `status`: `"completed"`
  - `decision`: `"auto_approve"`
  - `tool_calls`: List with **2 distinct tool invocations**:
    1. `tool_name`: `"query_carrier_tracking"` (`TRK-1010`, verifies delivery photo proof).
    2. `tool_name`: `"query_payment_transaction"` (`ORD-1010`, verifies charge status $450.00 and `dispute_status: "none"`).
  - `approval_email_text`: Populated with RMA code and high-value packaging instructions.

---

### TC-07: Low-Confidence Pause & Customer Clarification Lifecycle
- **Endpoint**: `POST /refunds` $\rightarrow$ `GET /refunds/{id}` $\rightarrow$ `POST /refunds/{id}/clarify` $\rightarrow$ `GET /refunds/{id}`
- **Goal**: Verify that ambiguous mixed-intent customer requests trigger low classifier confidence (< 0.70), pause the workflow with `awaiting_clarification`, generate a polite clarification inquiry email, and resume to completion once answered.
- **Step 1 (`POST /refunds`) Input**:
  ```json
  {
    "order_id": "ORD-1008",
    "customer_request_text": "I got something in the mail. It is ok I guess but not sure about it or maybe something else."
  }
  ```
- **Step 2 (`GET /refunds/{refund_id}`) Expected Output**:
  - `status`: `"awaiting_clarification"`
  - `clarification_count`: `1`
  - `clarification_prompt`: Formatted customer inquiry email asking for specific reasons and details.
- **Step 3 (`POST /refunds/{refund_id}/clarify`) Input**:
  - `refund_id`: `<copied_refund_id>`
  - Request Body:
    ```json
    {
      "response_text": "The watch is in perfect unopened condition, but I decided I prefer an analog watch instead. I want to return it."
    }
    ```
- **Step 3 Expected Output**: `200 OK`
  - `status`: `"pending"` (Workflow resumed).
- **Step 4 (`GET /refunds/{refund_id}`) Expected Output** (after 2–3s):
  - `status`: `"completed"`
  - `decision`: `"auto_approve"`
  - `confidence_score`: `>= 0.85`
  - `approval_email_text`: Populated with return instructions and RMA.

---

### TC-08: Clarification Exhaustion to Human Escalation
- **Endpoint**: `POST /refunds` $\rightarrow$ `POST /refunds/{id}/clarify` (Cycle 1) $\rightarrow$ `POST /refunds/{id}/clarify` (Cycle 2) $\rightarrow$ `GET /refunds/{id}`
- **Goal**: Validate that repeated unhelpful or vague clarification answers increment `clarification_count` across a complete two-stage clarification cycle and escalate to manual supervisor review once the maximum attempts threshold (`>= 2`) is exhausted.
- **Step 1 (`POST /refunds`) - Initial Ambiguous Intake**:
  - Request Body:
    ```json
    {
      "order_id": "ORD-1009",
      "customer_request_text": "I am unsure what happened, low confidence description of wireless earbuds for order ORD-1009."
    }
    ```
  - **Expected Status**: `202 Accepted`
  - *(Copy the returned `refund_id` for subsequent steps)*.
  - **Verification (`GET /refunds/{refund_id}`)**:
    - `status`: `"awaiting_clarification"`
    - `clarification_count`: `1`
    - `clarification_prompt`: Formatted customer inquiry email asking for specific reasons and details.
- **Step 2 (`POST /refunds/{refund_id}/clarify`) - Clarification Cycle 1 (First Vague Response)**:
  - Submit the first ambiguous clarification response:
    ```json
    {
      "response_text": "Still unsure about what happened, low confidence details."
    }
    ```
  - **Expected Status**: `200 OK` (`status: "pending"`).
  - **Verification (`GET /refunds/{refund_id}`)**:
    - `status`: `"awaiting_clarification"`
    - `clarification_count`: `2`
    - `clarification_prompt`: Formatted customer inquiry email prompting for clarification again.
- **Step 3 (`POST /refunds/{refund_id}/clarify`) - Clarification Cycle 2 (Second Vague Response - Exhaustion)**:
  - Submit the second ambiguous clarification response (exhausting maximum clarification attempts):
    ```json
    {
      "response_text": "Still unsure and low confidence description."
    }
    ```
  - **Expected Status**: `200 OK` (`status: "pending"`).
- **Step 4 (`GET /refunds/{refund_id}`) - Escalation Verification**:
  - Wait 2–3 seconds and execute `GET /refunds/{refund_id}`.
  - **Expected Status**: `200 OK`
  - **Expected Output**:
    ```json
    {
      "refund_id": "ref_...",
      "order_id": "ORD-1009",
      "customer_request_text": "I am unsure what happened, low confidence description of wireless earbuds for order ORD-1009.\n[Clarification]: Still unsure about what happened, low confidence details.\n[Clarification]: Still unsure and low confidence description.",
      "status": "escalated",
      "decision": "escalate",
      "clarification_count": 2,
      "clarification_response": "Still unsure and low confidence description.",
      "reasoning": "Confidence score 0.52 below threshold (0.70) after reaching maximum clarification cycles (2). Escalating to human review queue.",
      "approval_email_text": null,
      "denial_email_text": null,
      "created_at": "...",
      "updated_at": "..."
    }
    ```
  - *(Save this escalated `refund_id` for use in TC-09)*.

---

### TC-09: Supervisor Manual Decision Override
- **Endpoint**: `POST /refunds/{refund_id}/override`
- **Goal**: Confirm a human operator / supervisor can inspect an escalated refund (using the escalated `refund_id` resulting from TC-08) and issue a binding override decision (`approve` or `deny`), updating workflow status to `completed` and generating the appropriate customer notification email.
- **Pre-condition**:
  - Verify that the refund request with `refund_id` from TC-08 (`<escalated_refund_id_from_TC-08>`) is in `status: "escalated"` via `GET /refunds/{refund_id}` prior to issuing the override.
- **Option A: Approval Override (`override_decision: "approve"`)**:
  - **Input (`POST /refunds/{refund_id}/override`)**:
    - `refund_id`: `<escalated_refund_id_from_TC-08>`
    - Request Body:
      ```json
      {
        "override_decision": "approve",
        "reason": "Customer is a verified loyalty club member; courtesy approval granted."
      }
      ```
  - **Expected Status**: `200 OK`
  - **Expected Response Body**:
    ```json
    {
      "refund_id": "<escalated_refund_id_from_TC-08>",
      "order_id": "ORD-1009",
      "status": "completed",
      "decision": "approve",
      "override_decision": "approve",
      "override_reason": "Customer is a verified loyalty club member; courtesy approval granted.",
      "overridden_at": "2026-09-25T...",
      "approval_email_text": "Dear Customer,\n\nWe have approved your refund request for order ORD-1009.\nReturn Merchandise Authorization (RMA): RMA-1009-...\nPlease return your item within 14 days using the provided return label.\n\nThank you,\nCustomer Support Team",
      "denial_email_text": null,
      "created_at": "...",
      "updated_at": "..."
    }
    ```
- **Option B: Denial Override (`override_decision: "deny"`)**:
  - **Input (`POST /refunds/{refund_id}/override`)**:
    - `refund_id`: `<escalated_refund_id_from_TC-08>`
    - Request Body:
      ```json
      {
        "override_decision": "deny",
        "reason": "Customer repeatedly failed to provide valid damage verification details upon clarification."
      }
      ```
  - **Expected Status**: `200 OK`
  - **Expected Response Body**:
    ```json
    {
      "refund_id": "<escalated_refund_id_from_TC-08>",
      "order_id": "ORD-1009",
      "status": "completed",
      "decision": "deny",
      "override_decision": "deny",
      "override_reason": "Customer repeatedly failed to provide valid damage verification details upon clarification.",
      "overridden_at": "2026-09-25T...",
      "approval_email_text": null,
      "denial_email_text": "Dear Customer,\n\nWe are writing to inform you that your refund request for order ORD-1009 has been denied.\nReason: Customer repeatedly failed to provide valid damage verification details upon clarification.\n\nThank you,\nCustomer Support Team",
      "created_at": "...",
      "updated_at": "..."
    }
    ```
- **Post-Override Verification**:
  - Execute `GET /refunds/{refund_id}` using the overridden `refund_id` to confirm persistent storage reflects `status: "completed"`, `decision` matches the supervisor override, and the corresponding email text is populated.

---

### TC-10: Customer Damage Evidence Upload (Multipart)
- **Endpoint**: `POST /refunds/{refund_id}/evidence`
- **Goal**: Verify multipart file upload handling for customer proof photos and videos.
- **Input**:
  - `refund_id`: Any existing refund ID.
  - `file`: Attach any small image file (`sample_damage.jpg` or `sample_damage.png`).
- **Expected Output**: `201 Created`
  ```json
  {
    "refund_id": "ref_...",
    "order_id": "...",
    "evidence": [
      {
        "evidence_id": "evi_...",
        "storage_key": "evidence/.../sample_damage.jpg",
        "filename": "sample_damage.jpg",
        "content_type": "image/jpeg",
        "size_bytes": 12345,
        "url": "/static/uploads/evidence/.../sample_damage.jpg",
        "created_at": "..."
      }
    ]
  }
  ```

---

### TC-11: Multimodal Vision Inspection of Customer Damage Photo
- **Endpoint**: `POST /refunds` (or attach evidence via `POST /refunds/{id}/evidence`)
- **Goal**: When a claim is `damaged` and an image is attached, verify that deterministic pass is bypassed and the multimodal Bedrock agent inspects image bytes for visible damage.
- **Input Step 1 (`POST /refunds`)**:
  ```json
  {
    "order_id": "ORD-1001",
    "customer_request_text": "The chair arrived broken with cracked plastic framing."
  }
  ```
- **Input Step 2 (`POST /refunds/{refund_id}/evidence`)**:
  - Attach an image demonstrating item damage.
- **Expected Verification**:
  - `GET /refunds/{refund_id}` reflects `evidence` array populated.
  - Multimodal agent inspects image content blocks.
  - If damage is verified: `decision: "auto_approve"`, `reasoning` explicitly confirms physical damage observed in proof photo.
  - If non-image (video) only: routes to `ambiguous` with `reasoning="Video evidence requires manual reviewer inspection."`.

---

### TC-12: Refund Queue Listing & Status Filtering
- **Endpoint**: `GET /refunds`
- **Goal**: Verify back-office query capabilities across refund statuses.
- **Test Variations**:
  1. `GET /refunds` (no parameters) $\rightarrow$ Returns list of all refund records.
  2. `GET /refunds?status=completed` $\rightarrow$ Returns only approved or denied completed claims.
  3. `GET /refunds?status=escalated` $\rightarrow$ Returns only claims waiting in the manual review queue.
  4. `GET /refunds?status=awaiting_clarification` $\rightarrow$ Returns claims waiting for customer responses.
- **Expected Status**: `200 OK`
- **Expected Output**: Array of `RefundRecord` items matching the filter.

---

### TC-13: Validation Boundaries & Error Handling
- **Goal**: Verify robust HTTP error status codes on invalid inputs.

| Test Case | Method & Endpoint | Payload / Condition | Expected Status Code | Expected Behavior |
| :--- | :--- | :--- | :---: | :--- |
| **Blank Order ID** | `POST /refunds` | `{"order_id": "", "customer_request_text": "Help"}` | `422 Unprocessable Entity` | Pydantic validation error |
| **Blank Request Text** | `POST /refunds` | `{"order_id": "ORD-1001", "customer_request_text": "   "}` | `422 Unprocessable Entity` | Pydantic validation error |
| **Nonexistent Refund** | `GET /refunds/ref_nonexistent` | Random invalid refund ID | `404 Not Found` | Detail: `"Refund request '...' not found."` |
| **Disallowed File Upload** | `POST /refunds/{id}/evidence` | Upload `.exe` or `.txt` file | `400 Bad Request` | Detail: `"Disallowed file extension/MIME type"` |
| **Oversized Upload** | `POST /refunds/{id}/evidence` | Upload image > 10MB or video > 50MB | `413 Payload Too Large` | Rejection of oversized file |
