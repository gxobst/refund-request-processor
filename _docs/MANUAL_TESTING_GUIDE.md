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

> [!TIP]
> **Swagger UI Media Type Toggling & Reset**:
> For endpoints offering dual media types (e.g. `POST /refunds` and `POST /refunds/{refund_id}/clarify` supporting both `application/json` and `multipart/form-data`), Swagger UI retains entered field values across format selections in browser state. If you switch between `multipart/form-data` and `application/json`, click the Swagger **Reset** button or reload the page to clear the previous form parameters.

---

## Summary Matrix of Test Scenarios

| Scenario # | Test Name | Key Mechanism Verified | Target Order | Expected Decision / Status |
| :---: | :--- | :--- | :--- | :---: |
| **TC-01** | System Health Check | DynamoDB & API connectivity | N/A | `status: "healthy"` (HTTP 200) |
| **TC-02** | Clear-Cut Approval & Return Email | Fast deterministic bypass + approval email with RMA | `ORD-1007` | `auto_approve` / `completed` |
| **TC-03** | Max Order Amount Escalation & Damage Proof Collection | Two-stage evaluation: unproven damage pauses in `awaiting_clarification` to collect photos, then escalates with proof ($750 > $500) | `ORD-1003` | `awaiting_clarification` -> `escalate` / `escalated` |
| **TC-04** | Expired Return Window Denial & Denial Email | Date window violation (> 30 days) triggers denial + automated denial email | `ORD-1004` | `deny` / `completed` |
| **TC-05** | Single Tool Carrier Verification | Autonomous `query_carrier_tracking` tool call for delayed delivery | `ORD-1005` | `auto_approve` / `completed` |
| **TC-06** | Mandatory Dual Tool Verification (FedEx & Stripe) | High-value order (≥ $400) mandates both carrier & payment tool audit records | `ORD-1010` | `auto_approve` / `completed` |
| **TC-07** | Clarification Loop Lifecycle | Low confidence (< 0.70) pause (persists `category` & diagnostics) -> customer response -> resolution | `ORD-1008` | `awaiting_clarification` -> `auto_approve` |
| **TC-08** | Clarification Exhaustion to Escalation | 2-cycle clarification exhaustion (low confidence < 0.70) -> human escalation; tracks `clarification_history` | `ORD-1009` | `awaiting_clarification` (cycles 1 & 2) -> `escalate` / `escalated` |
| **TC-09** | Supervisor Manual Override | Supervisor manual override on escalated TC-08 refund (`approve` or `deny`) | `ORD-1009` | `approve` or `deny` / `completed` |
| **TC-10** | Multipart Damage Evidence Upload & Workflow Resumption | Interactive file picker upload (JPEG/PNG/WebP ≤ 5MB); automatically triggers workflow resumption for paused refunds | Any active refund | HTTP 201 (`resume_refund_workflow` triggered) |
| **TC-11** | Multimodal Image Inspection | Mandatory proof check: missing photos pause with `awaiting_clarification`; direct `/evidence` upload resumes Bedrock vision | `ORD-1001` | `awaiting_clarification` -> `auto_approve` |
| **TC-12** | Initial Refund Creation with Attached Image | Multipart `POST /refunds` with upfront image proof (case-sensitive boundary support) | `ORD-1001` | HTTP 202 (`evidence` populated on intake) |
| **TC-13** | Queue Listing and Filtering | DynamoDB querying with status filter (`completed`, `escalated`, etc.) | N/A | HTTP 200 (filtered list) |
| **TC-14** | Input Validation & Error Boundaries | Order ID regex (`^ORD-\d{4}$`), blank fields, 404s, video rejection, 5MB limit, request-proof validation | N/A | HTTP 400, 404, 413, 422 |
| **TC-15** | Supervisor Proof Request from Escalation Queue | Human supervisor requests targeted photo proof via `POST /refunds/{id}/request-proof`; tracks `clarification_history` | `ORD-1009` | `escalated` -> `awaiting_clarification` (HTTP 200) |
| **TC-16** | Product Mismatch Customer Clarification | Item mismatch routes to customer inquiry email; resolves upon confirmation or escalates if 2 cycles exhausted | `ORD-1008` | `awaiting_clarification` -> `completed` (or `escalate`) |
| **TC-17** | Wrong Item Photo Evidence Verification & Multimodal Inspection | Mandatory photo proof for `wrong_item`: pauses without photos, upload resumes vision inspection (auto-approve / deny / escalate) | `ORD-1002` | `awaiting_clarification` -> `auto_approve` / `deny` / `escalate` |

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
    "timestamp": "2026-09-25T...",
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
- **Step 1 Expected Output (`POST /refunds`)**: `202 Accepted`
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
  - `denial_email_text`: `null`
  - `approval_email_text`: Non-null string containing:
    - Formal customer greeting
    - Confirmation that refund for `ORD-1007` is approved
    - Unique RMA number (e.g. `RMA-1007-...`)
    - Explicit 14-day return window deadline
    - Clear packaging and mailing return instructions

---

### TC-03: Max Order Amount Threshold Escalation & Mandatory Photo Collection
- **Endpoint**: `POST /refunds` (Intake) $\rightarrow$ `GET /refunds/{refund_id}` (Pause) $\rightarrow$ `POST /refunds/{refund_id}/evidence` (Proof Upload) $\rightarrow$ `GET /refunds/{refund_id}` (Escalation)
- **Goal**: Validate the two-stage evaluation sequence for high-value damage claims (`ORD-1003`, $750.00 OLED Gaming Monitor, exceeding the $500.00 damaged limit). Unproven damage claims must NOT escalate immediately to a supervisor with missing evidence; instead, the system pauses at `status: "awaiting_clarification"` to collect photo proof of the damage. Once the customer attaches photo evidence via `POST /refunds/{refund_id}/evidence`, workflow execution automatically resumes in the background and escalates to `status: "escalated"` with `failed_rules: ["max_order_amount"]` and the customer's photo proof attached for human supervisor review.

> [!IMPORTANT]
> **Two-Stage Evaluation Sequence for High-Value Damage Claims**:
> - **Stage 1 (Proof Collection Pause)**: When a damage claim is filed without photos, the Policy Checker identifies the `damaged` category and pauses at `status: "awaiting_clarification"` with `failed_rules: ["physical_damage_verification"]`. This guarantees human supervisors do not receive escalated tickets that lack essential damage photographs.
> - **Stage 2 (Supervisor Escalation with Evidence)**: Uploading photo evidence via `POST /refunds/{refund_id}/evidence` automatically resumes workflow execution in the background. With evidence now attached, policy evaluation verifies the photo and evaluates the order amount ($750.00 > $500.00 limit), routing to `status: "escalated"` and `decision: "escalate"` with `failed_rules: ["max_order_amount"]` and full evidence attached.

#### Step 1: Initial Submission Without Photo Proof
- **Action**: In Swagger UI, expand `POST /refunds` and submit:
  ```json
  {
    "order_id": "ORD-1003",
    "customer_request_text": "The gaming monitor arrived with a completely shattered OLED panel and cracked stand."
  }
  ```
- **Expected Status**: `202 Accepted`
  ```json
  {
    "refund_id": "ref_...",
    "order_id": "ORD-1003",
    "status": "pending",
    "created_at": "..."
  }
  ```
  *(Copy the returned `refund_id` for subsequent steps)*.

#### Step 2: Verification of Stage 1 Photo Proof Pause
- **Action**: Wait 2–3 seconds and execute `GET /refunds/{refund_id}`.
- **Expected Status**: `200 OK`
- **Expected Output**:
  - `status`: `"awaiting_clarification"` *(Note: Auto-escalation is paused to collect photo proof)*
  - `decision`: `null`
  - `category`: `"damaged"`
  - `policy_status`: `"ambiguous"`
  - `failed_rules`: `["physical_damage_verification"]`
  - `clarification_count`: `1`
  - `clarification_prompt`: Formatted customer inquiry email requesting clear photographs of the damaged OLED monitor and shipping packaging.
  - `clarification_history`:
    ```json
    [
      {
        "cycle": 1,
        "prompt": "Dear Customer,\n\nThank you for reaching out regarding order ORD-1003. To evaluate your damaged item claim, please provide photos of the damaged merchandise and packaging...",
        "response": null,
        "timestamp": "2026-09-26T...",
        "evidence_ids": []
      }
    ]
    ```

#### Step 3: Customer Uploads Damage Photo Proof
- **Action**: In Swagger UI, expand `POST /refunds/{refund_id}/evidence`.
  1. Input `refund_id`: `<refund_id_from_step_1>`.
  2. Under `file`, choose a valid image depicting the cracked monitor (`damaged_monitor.png`, JPEG/PNG/WebP ≤ 5MB).
  3. Click **Execute**.
- **Expected Status**: `201 Created`
- **Expected Output**:
  ```json
  {
    "refund_id": "ref_...",
    "order_id": "ORD-1003",
    "evidence": [
      {
        "evidence_id": "evi_...",
        "storage_key": "evidence/ref_.../damaged_monitor.png",
        "filename": "damaged_monitor.png",
        "content_type": "image/png",
        "size_bytes": 45120,
        "url": "/static/uploads/evidence/ref_.../damaged_monitor.png",
        "created_at": "2026-09-26T..."
      }
    ]
  }
  ```

> [!NOTE]
> **Automatic Workflow Resumption**: Calling `POST /refunds/{refund_id}/evidence` on a refund in `status: "awaiting_clarification"` automatically schedules background workflow resumption (`resume_refund_workflow`). No secondary call to `POST /refunds/{refund_id}/clarify` is needed.

#### Step 4: Verification of Stage 2 Supervisor Escalation
- **Action**: Wait 2–3 seconds for background workflow resumption to complete, then execute `GET /refunds/{refund_id}`.
- **Expected Status**: `200 OK`
- **Expected Output**:
  - `status`: `"escalated"`
  - `decision`: `"escalate"`
  - `policy_status`: `"ambiguous"`
  - `failed_rules`: `["max_order_amount"]`
  - `reasoning`: `"Order amount ($750.0) exceeds maximum threshold ($500.0); requires supervisor escalation."`
  - `approval_email_text`: `null`
  - `denial_email_text`: `null`
  - `evidence`: Array contains the uploaded `damaged_monitor.png` metadata.
  - `clarification_history`:
    ```json
    [
      {
        "cycle": 1,
        "prompt": "Dear Customer,\n\nThank you for reaching out regarding order ORD-1003...",
        "response": null,
        "timestamp": "2026-09-26T...",
        "evidence_ids": [
          "evi_..."
        ]
      }
    ]
    ```

---

### TC-04: Expired Return Window Denial & Customer Denial Email
- **Endpoint**: `POST /refunds` followed by `GET /refunds/{refund_id}`
- **Goal**: Confirm that return requests filed beyond the policy window (`ORD-1004` purchased in August, > 30 days ago) are denied (`decision: "deny"`, `status: "completed"`) and automatically generate an empathetic customer denial email explaining the policy violation without an RMA number.
- **Input (`POST /refunds`)**:
  ```json
  {
    "order_id": "ORD-1004",
    "customer_request_text": "The keyboard spacebar stopped working properly. I would like a refund."
  }
  ```
- **Step 1 Expected Output**: `202 Accepted`
- **Step 2 (`GET /refunds/{refund_id}`) Expected Output**: `200 OK`
  - `status`: `"completed"`
  - `decision`: `"deny"`
  - `failed_rules`: `["refund_window_days"]`
  - `reasoning`: Identifies failed rule `"refund_window_days"`.
  - `approval_email_text`: `null`
  - `denial_email_text`: Non-null string containing:
    - Customer greeting and order ID `ORD-1004`
    - Polite explanation that the request falls outside the 30-day return policy window
    - Customer support contact information
    - Strictly **NO RMA number** or return shipping instructions

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
- **Step 1 Expected Output**: `202 Accepted`
- **Step 2 (`GET /refunds/{refund_id}`) Expected Output**: `200 OK`
  - `status`: `"completed"`
  - `decision`: `"auto_approve"`
  - `tool_calls`: Contains an entry with:
    - `tool_name`: `"query_carrier_tracking"`
    - `tool_input`: `{"tracking_number": "TRK-1005"}`
    - `tool_output`: Contains carrier transit status and verified delay evidence.
  - `reasoning`: References carrier tracking findings confirming package delay beyond expected SLA.

---

### TC-06: Mandatory Dual Tool Verification for High-Value Orders
- **Endpoint**: `POST /refunds` followed by `GET /refunds/{refund_id}`
- **Goal**: High-value claims (`ORD-1010`, $450.00 Camera, order amount ≥ $400.00) strictly mandate autonomous execution of BOTH external verification tools (`query_carrier_tracking` and `query_payment_transaction`) before any approval can be granted.
- **Input (`POST /refunds`)**:
  ```json
  {
    "order_id": "ORD-1010",
    "customer_request_text": "I ordered this mirrorless camera but received the wrong lens bundle. I would like to return it for a refund."
  }
  ```
- **Step 1 Expected Output**: `202 Accepted`
- **Step 2 (`GET /refunds/{refund_id}`) Expected Output**: `200 OK`
  - `status`: `"completed"`
  - `decision`: `"auto_approve"`
  - `tool_calls`: List with **both required tool audit executions**:
    1. `tool_name`: `"query_carrier_tracking"` (`TRK-1010`, verifies delivery photo proof).
    2. `tool_name`: `"query_payment_transaction"` (`ORD-1010`, verifies charge amount $450.00 and `dispute_status: "none"`).
  - `approval_email_text`: Populated with RMA code `RMA-1010-...` and return instructions.

---

### TC-07: Low-Confidence Pause & Customer Clarification Lifecycle
- **Endpoint**: `POST /refunds` $\rightarrow$ `GET /refunds/{id}` $\rightarrow$ `POST /refunds/{id}/clarify` $\rightarrow$ `GET /refunds/{id}`
- **Goal**: Verify that ambiguous mixed-intent customer requests trigger low classifier confidence (< 0.70), pause the workflow with `awaiting_clarification`, generate a polite clarification inquiry email requesting specific refund reasons and damage photo proof, and resume once answered.
- **Step 1 (`POST /refunds`) Input**:
  ```json
  {
    "order_id": "ORD-1008",
    "customer_request_text": "I got something in the mail. It is ok I guess but not sure about it or maybe something else."
  }
  ```
- **Step 2 (`GET /refunds/{refund_id}`) Expected Output**:
  - `status`: `"awaiting_clarification"`
  - `decision`: `null` *(expected: policy evaluation is paused until clarification is submitted)*
  - `category`: `"changed_mind"` (or `"ambiguous"`) *(persisted from classifier agent)*
  - `confidence_score`: `< 0.70` (e.g. `0.52`) *(persisted diagnostic score)*
  - `reasoning`: Non-null classification diagnosis explaining ambiguity or low confidence.
  - `clarification_count`: `1`
  - `clarification_prompt`: Formatted customer inquiry email asking for specific reasons and photo proof.
- **Step 3 (`POST /refunds/{refund_id}/clarify`) Input (Swagger Form / JSON)**:
  - In Swagger UI, expand `POST /refunds/{refund_id}/clarify`.
  - Enter `refund_id`.
  - In the request body, provide:
    ```json
    {
      "response_text": "The watch is in perfect unopened condition, but I decided I prefer an analog watch instead. I want to return it."
    }
    ```
- **Step 3 Expected Output**: `200 OK` (`status: "pending"`).
- **Step 4 (`GET /refunds/{refund_id}`) Expected Output** (after 2–3s):
  - `status`: `"completed"`
  - `decision`: `"auto_approve"`
  - `confidence_score`: `>= 0.85`
  - `approval_email_text`: Populated with return instructions and RMA.

---

### TC-08: Clarification Exhaustion to Human Escalation
- **Endpoint**: `POST /refunds` (Intake) $\rightarrow$ `POST /refunds/{id}/clarify` (Answer 1) $\rightarrow$ `POST /refunds/{id}/clarify` (Answer 2) $\rightarrow$ `GET /refunds/{id}`
- **Goal**: Validate that repeated unhelpful or vague clarification answers increment `clarification_count` across the full two-cycle clarification allowance, and escalate to manual supervisor review once the maximum attempts threshold (`clarification_count >= 2`) is exhausted.

> [!IMPORTANT]
> **Understanding the 3-Turn / 2-Cycle Clarification Sequence**:
> - **Turn 1 (Intake)**: Initial vague refund request pauses at `awaiting_clarification` (`clarification_count: 1`). The system sends Question #1 to the customer.
> - **Turn 2 (Customer Answer #1)**: Submitting the 1st vague `/clarify` response opens Cycle 2. The system sends Question #2, remaining in **`status: "awaiting_clarification"`** with **`clarification_count: 2`**. *(It does NOT escalate yet because the customer is given a second chance to answer).*
> - **Turn 3 (Customer Answer #2 - Exhaustion)**: Submitting the 2nd vague `/clarify` response exhausts all allowed clarification attempts (`clarification_count >= 2`). The system routes to **`status: "escalated"`** and **`decision: "escalate"`** for supervisor review.

#### Step 1: Initial Ambiguous Intake (Turn 1)
- **Action**: In Swagger UI, expand `POST /refunds`.
- **Request Body**:
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
  - `decision`: `null`
  - `clarification_count`: `1`
  - `clarification_prompt`: Formatted customer inquiry email prompting for clarification (Question #1).
  - `clarification_history`:
    ```json
    [
      {
        "cycle": 1,
        "prompt": "Dear Customer,\n\nThank you for contacting us regarding order ORD-1009. Could you please provide more details regarding your request?",
        "response": null,
        "timestamp": "2026-09-26T10:00:00Z",
        "evidence_ids": []
      }
    ]
    ```

#### Step 2: First Clarification Response - Enters Cycle 2 (Turn 2)
- **Action**: In Swagger UI, expand `POST /refunds/{refund_id}/clarify`.
- **Input**:
  - `refund_id`: `<refund_id>`
  - Request Body:
    ```json
    {
      "response_text": "Still unsure about what happened, low confidence details."
    }
    ```
- **Expected Status**: `200 OK` (returns record with `status: "pending"`).
- **Verification (`GET /refunds/{refund_id}`)** *(wait 2-3 seconds for background worker)*:
  - `status`: `"awaiting_clarification"` *(Note: Still awaiting clarification because the customer is granted attempt #2)*
  - `decision`: `null`
  - `clarification_count`: `2`
  - `clarification_prompt`: Formatted customer inquiry email prompting for clarification again (Question #2).
  - `clarification_history`:
    ```json
    [
      {
        "cycle": 1,
        "prompt": "Dear Customer,\n\nThank you for contacting us regarding order ORD-1009. Could you please provide more details regarding your request?",
        "response": "Still unsure about what happened, low confidence details.",
        "timestamp": "2026-09-26T10:00:00Z",
        "evidence_ids": []
      },
      {
        "cycle": 2,
        "prompt": "Dear Customer,\n\nWe received your note but still need further specific details regarding order ORD-1009...",
        "response": null,
        "timestamp": "2026-09-26T10:02:00Z",
        "evidence_ids": []
      }
    ]
    ```

#### Step 3: Second Clarification Response - Exhausts Attempts (Turn 3)
- **Action**: In Swagger UI, submit a second vague answer to `POST /refunds/{refund_id}/clarify`.
- **Input**:
  - `refund_id`: `<refund_id>`
  - Request Body:
    ```json
    {
      "response_text": "Still unsure and low confidence description."
    }
    ```
- **Expected Status**: `200 OK` (returns record with `status: "pending"`).

#### Step 4: Verify Final Escalation
- **Action**: Wait 2–3 seconds and execute `GET /refunds/{refund_id}`.
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
    "clarification_history": [
      {
        "cycle": 1,
        "prompt": "Dear Customer,\n\nThank you for contacting us regarding order ORD-1009. Could you please provide more details regarding your request?",
        "response": "Still unsure about what happened, low confidence details.",
        "timestamp": "2026-09-26T10:00:00Z",
        "evidence_ids": []
      },
      {
        "cycle": 2,
        "prompt": "Dear Customer,\n\nWe received your note but still need further specific details regarding order ORD-1009...",
        "response": "Still unsure and low confidence description.",
        "timestamp": "2026-09-26T10:02:00Z",
        "evidence_ids": []
      }
    ],
    "reasoning": "Confidence score 0.30 below threshold (0.70) after reaching maximum clarification cycles (2). Escalating to human review queue.",
    "approval_email_text": null,
    "denial_email_text": null,
    "created_at": "...",
    "updated_at": "..."
  }
  ```
- *(Save this escalated `refund_id` for use in TC-09 and TC-15)*.

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

### TC-10: Customer Damage Evidence Upload (Interactive Swagger UI File Picker)
- **Endpoint**: `POST /refunds/{refund_id}/evidence`
- **Goal**: Verify multipart image file upload using Swagger UI's interactive file selector (`<input type="file">`). Only images (JPEG, PNG, WebP ≤ 5MB) are supported; videos are rejected. Furthermore, verify that uploading evidence to a claim in `status: "awaiting_clarification"` automatically triggers background workflow resumption (`resume_refund_workflow`) without requiring a separate `/clarify` invocation.
- **Instructions in Swagger UI**:
  1. Navigate to `POST /refunds/{refund_id}/evidence` and click **Try it out**.
  2. Input an active `refund_id` (e.g. from TC-03, TC-11, or TC-17 in `awaiting_clarification`).
  3. Click **Choose File** / **Browse** and select a valid JPEG, PNG, or WebP photo (`sample_crack.png`, ≤ 5MB).
  4. Click **Execute**.
- **Expected Status**: `201 Created`
- **Expected Output**:
  ```json
  {
    "refund_id": "ref_...",
    "order_id": "ORD-...",
    "evidence": [
      {
        "evidence_id": "evi_...",
        "storage_key": "evidence/ref_.../sample_crack.png",
        "filename": "sample_crack.png",
        "content_type": "image/png",
        "size_bytes": 12345,
        "url": "/static/uploads/evidence/ref_.../sample_crack.png",
        "created_at": "2026-09-25T..."
      }
    ]
  }
  ```

> [!IMPORTANT]
> **Automatic Background Workflow Resumption on Evidence Upload**:
> When a refund is in `status: "awaiting_clarification"`, submitting `POST /refunds/{refund_id}/evidence` automatically:
> 1. Stores the uploaded file in S3/static storage and records the evidence metadata in DynamoDB.
> 2. Links the newly generated `evidence_id` to `evidence_ids` in the active turn of `clarification_history`.
> 3. Triggers `resume_refund_workflow` as a background task, transitioning status to `pending` and resuming policy evaluation.
>
> A manual follow-up call to `POST /refunds/{refund_id}/clarify` is **not required** when evidence is uploaded via this endpoint.
> *(Note: For claims in `completed` or `escalated` status, evidence is attached to the record for audit/supervisor review without re-triggering automated policy evaluation).*

> [!NOTE]
> **Swagger UI & Browser Boundary Support**: The server preserves case sensitivity in request headers. Browser-generated WebKit boundary tokens (e.g. `boundary=----WebKitFormBoundary...`) are parsed accurately without returning false `No file uploaded in multipart request` errors.

---

### TC-11: Multimodal Vision Inspection of Customer Damage Photo
- **Endpoint**: `POST /refunds` $\rightarrow$ `GET /refunds/{refund_id}` $\rightarrow$ `POST /refunds/{refund_id}/evidence` (or `POST /refunds/{refund_id}/clarify`) $\rightarrow$ `GET /refunds/{refund_id}`
- **Goal**: When a claim is categorized as `damaged`, verify that automated approval without evidence is strictly blocked. The system pauses at `status: "awaiting_clarification"` to demand photo proof. Once the customer attaches a valid image (either directly via `POST /refunds/{refund_id}/evidence` or via `POST /refunds/{refund_id}/clarify`), the multimodal Bedrock agent inspects the photo bytes to verify visible damage before approving.
- **Multimodal Evaluation Behavior**:
  - **No Evidence Attached**: Policy evaluation returns `policy_status: "ambiguous"` with `failed_rules: ["physical_damage_verification"]`. The workflow pauses in `awaiting_clarification` and sends a clarification email requesting photos of the damaged merchandise and packaging.
  - **Damage Verified in Image**: The multimodal vision agent inspects the uploaded image bytes. If physical damage matching the claim is identified on the product, it auto-approves (`decision: "auto_approve"`, `status: "completed"`).
  - **Intact Product / No Damage**: If the photo clearly shows an intact, undamaged product, the request is denied (`decision: "deny"`).
  - **Inconclusive / Corrupted**: If the image is blurry, corrupted, or inconclusive, the claim is escalated (`status: "escalated"`).

#### Step 1: Initial Submission Without Photo Proof
- **Action**: Submit a damaged claim without attaching an evidence file via `POST /refunds`:
  ```json
  {
    "order_id": "ORD-1001",
    "customer_request_text": "The chair arrived broken with cracked plastic framing."
  }
  ```
- **Expected Status**: `202 Accepted` *(copy returned `refund_id`)*.

#### Step 2: Verification of Mandatory Proof Clarification Pause
- **Action**: Wait 2–3 seconds and execute `GET /refunds/{refund_id}`.
- **Expected Status**: `200 OK`
- **Expected Output**:
  - `status`: `"awaiting_clarification"` *(Note: Auto-approval is blocked; photo evidence is required)*
  - `decision`: `null`
  - `clarification_count`: `1`
  - `failed_rules`: `["physical_damage_verification"]`
  - `clarification_prompt`: Non-null customer inquiry email stating:
    - Informs customer that claims for damaged items require photo evidence of both the damaged merchandise and exterior shipping packaging.
    - Specifies supported file formats (JPEG, PNG, WebP ≤ 5MB).
  - `clarification_history`:
    ```json
    [
      {
        "cycle": 1,
        "prompt": "Dear Customer,\n\nThank you for reaching out regarding order ORD-1001. Please provide clear photo evidence of the damaged merchandise and outer packaging...",
        "response": null,
        "timestamp": "2026-09-26T12:00:00Z",
        "evidence_ids": []
      }
    ]
    ```

#### Step 3: Customer Uploads Damage Photo Proof
- **Option A (Interactive Clarification with File in Swagger UI)**:
  1. Expand `POST /refunds/{refund_id}/clarify`.
  2. Select `multipart/form-data` from the Request body media type dropdown.
  3. Enter `refund_id`.
  4. Under `response_text`, enter: `"Attached photo showing the cracked chair armrest and frame."`.
  5. Under `evidence_file`, select a valid image depicting damage (`damaged_chair.png`, ≤ 5MB).
  6. Click **Execute**.
- **Option B (Direct Upload via `/evidence` with Automatic Workflow Resumption)**:
  1. Expand `POST /refunds/{refund_id}/evidence`.
  2. Enter `refund_id` and select the damage photo (`damaged_chair.png`, ≤ 5MB).
  3. Click **Execute**.
  4. Expected status is `201 Created`. Workflow evaluation automatically resumes in the background (`resume_refund_workflow`) without requiring a separate `POST /refunds/{refund_id}/clarify` follow-up invocation.

#### Step 4: Final Multimodal Inspection & Verification
- **Action**: Wait 3–4 seconds for Bedrock vision agent processing, then execute `GET /refunds/{refund_id}`.
- **Expected Status**: `200 OK`
- **Expected Output**:
  - `status`: `"completed"`
  - `decision`: `"auto_approve"`
  - `reasoning`: Explicitly confirms physical damage verified from customer photo proof (e.g. `"Physical damage observed in uploaded evidence matching customer claim; policy rules satisfied."`).
  - `approval_email_text`: Populated with RMA number (`RMA-1001-...`) and return instructions.
  - `evidence`: Array contains the uploaded damage photo metadata.
  - `clarification_history`:
    ```json
    [
      {
        "cycle": 1,
        "prompt": "Dear Customer,\n\nThank you for reaching out regarding order ORD-1001. Please provide clear photo evidence of the damaged merchandise and outer packaging...",
        "response": "Attached photo showing the cracked chair armrest and frame.",
        "timestamp": "2026-09-26T12:00:00Z",
        "evidence_ids": [
          "evi_..."
        ]
      }
    ]
    ```

---

### TC-12: Initial Refund Request with Upfront Image Evidence Attachment
- **Endpoint**: `POST /refunds` (via `multipart/form-data`)
- **Goal**: Verify that customers can attach an image proof directly upon initial refund creation in `POST /refunds`, storing the image and immediately evaluating it on the first workflow run without requiring a secondary evidence upload call.
- **Instructions in Swagger UI**:
  1. In Swagger UI, expand `POST /refunds`.
  2. Select `multipart/form-data` from the Request body dropdown.
  3. Enter `order_id`: `"ORD-1001"`.
  4. Enter `customer_request_text`: `"Chair armrest arrived snapped in half during transit."`.
  5. Under `file`, select a valid image file (`damage_proof.jpg`).
  6. Click **Execute**.
- **Step 1 Expected Output**: `202 Accepted`
  ```json
  {
    "refund_id": "ref_...",
    "order_id": "ORD-1001",
    "status": "pending",
    "created_at": "..."
  }
  ```

> [!NOTE]
> **Swagger UI Field Parsing**: Case-preserved multipart parsing ensures text fields (`order_id`, `customer_request_text`) and binary image files are parsed simultaneously without triggering `Field 'order_id' cannot be blank or empty` or `No file uploaded` validation errors.

- **Step 2 Verification (`GET /refunds/{refund_id}`)**:
  - `evidence`: Array is populated immediately on intake with the uploaded file metadata.
  - `status`: `"completed"`
  - `decision`: `"auto_approve"`
  - `reasoning`: Confirms physical damage verified from initial attached photo.

---

### TC-13: Refund Queue Listing & Status Filtering
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

### TC-14: Validation Boundaries & Error Handling

Verify robust HTTP error responses across inputs, formats, and file restrictions:

| Test Case | Method & Endpoint | Payload / Condition | Expected Status Code | Expected Behavior |
| :--- | :--- | :--- | :---: | :--- |
| **Malformed Order ID (lowercase)** | `POST /refunds` | `{"order_id": "ord-1001", "customer_request_text": "Defective"}` | `422 Unprocessable Entity` | Regex mismatch against `^ORD-\d{4}$` |
| **Malformed Order ID (wrong prefix)** | `POST /refunds` | `{"order_id": "INV-1001", "customer_request_text": "Defective"}` | `422 Unprocessable Entity` | Regex mismatch against `^ORD-\d{4}$` |
| **Malformed Order ID (wrong digits)** | `POST /refunds` | `{"order_id": "ORD-100", "customer_request_text": "Defective"}` | `422 Unprocessable Entity` | Regex mismatch (must have 4 digits) |
| **Blank Order ID** | `POST /refunds` | `{"order_id": "", "customer_request_text": "Help"}` | `422 Unprocessable Entity` | Pydantic validation error |
| **Blank Request Text** | `POST /refunds` | `{"order_id": "ORD-1001", "customer_request_text": "   "}` | `422 Unprocessable Entity` | Blank text rejected |
| **Nonexistent Refund** | `GET /refunds/ref_nonexistent` | Unknown refund ID | `404 Not Found` | Detail: `"Refund request '...' not found"` |
| **Video File Rejection** | `POST /refunds/{id}/evidence` | Upload `.mp4` or `.mov` video file | `400 Bad Request` | Video formats disallowed; strictly images only |
| **Oversized Image File** | `POST /refunds/{id}/evidence` | Upload image > 5MB | `413 Payload Too Large` | Rejection of file exceeding 5MB ceiling |
| **Disallowed Extension** | `POST /refunds/{id}/evidence` | Upload `.exe`, `.pdf`, or `.txt` file | `400 Bad Request` | Disallowed file extension |
| **Proof Request on Non-Escalated Refund** | `POST /refunds/{id}/request-proof` | Target refund in `completed` or `pending` status | `400 Bad Request` | Detail: `"Refund request '...' is not escalated"` |
| **Blank Proof Prompt** | `POST /refunds/{id}/request-proof` | `{"proof_prompt": "   "}` | `422 Unprocessable Entity` | Blank proof prompt rejected |
| **Proof Request Unknown ID** | `POST /refunds/ref_missing/request-proof` | Unknown refund ID | `404 Not Found` | Detail: `"Refund request '...' not found"` |

---

### TC-15: Supervisor Proof Request from Escalation Queue
- **Endpoint**: `POST /refunds/{refund_id}/request-proof` $\rightarrow$ `GET /refunds/{refund_id}` $\rightarrow$ `POST /refunds/{refund_id}/evidence` (or `POST /refunds/{refund_id}/clarify`)
- **Goal**: Confirm that a human supervisor reviewing an escalated refund (e.g. resulting from TC-03 or TC-08) can request targeted customer proof (e.g., photo evidence of serial number or package labels). The system transitions the refund from `status: "escalated"` to `status: "awaiting_clarification"`, resets `decision: null`, generates a polite customer notification email with evidence upload instructions (JPEG, PNG, WebP ≤ 5MB), and enables customer evidence submission.
- **Pre-condition**:
  - Target refund must be in `status: "escalated"` (use `<escalated_refund_id>` from TC-03 or TC-08).
- **Step 1 (`POST /refunds/{refund_id}/request-proof`) Input**:
  - In Swagger UI, expand `POST /refunds/{refund_id}/request-proof`.
  - Enter `refund_id`: `<escalated_refund_id>`.
  - Request Body:
    ```json
    {
      "proof_prompt": "Please upload a clear close-up photograph of the manufacturer serial number sticker on the back of the device, as well as the outer shipping box condition.",
      "customer_name": "Jane Doe"
    }
    ```
- **Step 1 Expected Output**: `200 OK`
  ```json
  {
    "refund_id": "<escalated_refund_id>",
    "order_id": "ORD-...",
    "status": "awaiting_clarification",
    "decision": null,
    "clarification_prompt": "Please upload a clear close-up photograph of the manufacturer serial number sticker on the back of the device, as well as the outer shipping box condition.",
    "clarification_email_text": "Dear Jane Doe,\n\nWe are currently reviewing your refund request for order ORD-... regarding your recent purchase.\n\nTo help us complete our review, our support team has requested additional proof:\n\"Please upload a clear close-up photograph of the manufacturer serial number sticker on the back of the device, as well as the outer shipping box condition.\"\n\nHow to submit your proof:\n- Upload clear photos directly via our customer portal or reply to this request.\n- Supported formats: JPEG, PNG, WebP (up to 5MB per file).\n- Please ensure all markings and serial labels are fully legible.\n\nOnce we receive your additional information, our team will proceed with your claim.\n\nSincerely,\nCustomer Support Team",
    "clarification_count": 3,
    "clarification_history": [
      {
        "cycle": 1,
        "prompt": "Dear Customer,\n\nThank you for contacting us regarding order ORD-1009. Could you please provide more details regarding your request?",
        "response": "Still unsure about what happened, low confidence details.",
        "timestamp": "2026-09-26T10:00:00Z",
        "evidence_ids": []
      },
      {
        "cycle": 2,
        "prompt": "Dear Customer,\n\nWe received your note but still need further specific details regarding order ORD-1009...",
        "response": "Still unsure and low confidence description.",
        "timestamp": "2026-09-26T10:02:00Z",
        "evidence_ids": []
      },
      {
        "cycle": 3,
        "prompt": "Please upload a clear close-up photograph of the manufacturer serial number sticker on the back of the device, as well as the outer shipping box condition.",
        "response": null,
        "timestamp": "2026-09-26T10:15:00Z",
        "evidence_ids": []
      }
    ]
  }
  ```
- **Step 2 Customer Evidence Submission**:
  - Customer can now upload the requested photo using `POST /refunds/{refund_id}/evidence` (via the Swagger file selector).
  - Or respond with text details using `POST /refunds/{refund_id}/clarify`.
  - The workflow resumes processing upon submission.

---

### TC-16: Product Mismatch Detection & Customer Clarification
- **Endpoint**: `POST /refunds` $\rightarrow$ `GET /refunds/{refund_id}` $\rightarrow$ `POST /refunds/{refund_id}/clarify` $\rightarrow$ `GET /refunds/{refund_id}`
- **Goal**: Verify that when a customer refund request explicitly describes a product conflicting with the item recorded in the order database (e.g., claiming a refund for a "mirrorless camera" when order `ORD-1008` is actually for a "Smart Fitness Watch"), the system detects the discrepancy. Rather than escalating immediately to a human supervisor, the system routes to `status: "awaiting_clarification"` (`clarification_count < 2`) and automatically generates a polite customer inquiry email asking the customer to clarify whether they are claiming for the item on their order or entered an incorrect order number.
- **Workflow Routing Behavior**:
  - **First Pass (Mismatch Detected, `clarification_count < 2`)**: Policy Checker flags `failed_rules: ["product_mismatch"]` and sets `policy_status: "ambiguous"`. Graph routes to `clarification_node`, which crafts an inquiry email pointing out the discrepancy and asking for clarification. Status pauses at `awaiting_clarification`.
  - **Customer Resolves Item**: Customer replies via `POST /refunds/{refund_id}/clarify` confirming the ordered item. Workflow resumes, policy evaluates without mismatch, and request proceeds to approval (`completed`).
  - **Persistent Mismatch (Exhaustion)**: If the customer repeats the conflicting product description across 2 clarification cycles (`clarification_count >= 2`), the workflow escalates to `status: "escalated"` (`decision: "escalate"`) for human supervisor review.

#### Step 1: Initial Submission with Item Discrepancy
- **Action**: Submit a refund request with a mismatched product via `POST /refunds`:
  ```json
  {
    "order_id": "ORD-1008",
    "customer_request_text": "I ordered this mirrorless camera but received the wrong lens bundle. I would like to return it for a refund."
  }
  ```
- **Expected Status**: `202 Accepted` *(copy returned `refund_id`)*.

#### Step 2: Verification of Customer Clarification Pause
- **Action**: Wait 2–3 seconds and execute `GET /refunds/{refund_id}`.
- **Expected Status**: `200 OK`
- **Expected Output**:
  - `status`: `"awaiting_clarification"` *(Note: Does NOT escalate immediately; asks customer to clear it up)*
  - `decision`: `null`
  - `policy_status`: `"ambiguous"`
  - `failed_rules`: `["product_mismatch"]`
  - `clarification_count`: `1`
  - `reasoning`: Explicitly identifies the product conflict (e.g. `"Customer request describes 'camera' which does not match ordered item 'Smart Fitness Watch'"`).
  - `clarification_prompt`: Formatted customer inquiry email:
    - References order `ORD-1008` and the ordered item (*Smart Fitness Watch*).
    - Asks whether the refund is intended for the Smart Fitness Watch or if an incorrect order number was entered.
  - `clarification_history`:
    ```json
    [
      {
        "cycle": 1,
        "prompt": "Dear Customer,\n\nThank you for reaching out regarding order ORD-1008. We noticed your request mentions a camera, whereas order ORD-1008 is for a Smart Fitness Watch. Could you please confirm if this request is for the Smart Fitness Watch or an alternate order?",
        "response": null,
        "timestamp": "2026-09-26T13:00:00Z",
        "evidence_ids": []
      }
    ]
    ```

#### Step 3: Customer Clarifies and Resolves Mismatch
- **Action**: In Swagger UI, expand `POST /refunds/{refund_id}/clarify` and submit:
  ```json
  {
    "response_text": "Apologies for the mix-up! I was referencing order ORD-1008 for my Smart Fitness Watch, which stopped charging."
  }
  ```
- **Expected Status**: `200 OK` (`status: "pending"`).

#### Step 4: Final Evaluation Verification
- **Action**: Wait 2–3 seconds and execute `GET /refunds/{refund_id}`.
- **Expected Status**: `200 OK`
- **Expected Output**:
  - `status`: `"completed"`
  - `decision`: `"auto_approve"`
  - `approval_email_text`: Populated with RMA number and return instructions for `ORD-1008`.
  - `clarification_history`:
    ```json
    [
      {
        "cycle": 1,
        "prompt": "Dear Customer,\n\nThank you for reaching out regarding order ORD-1008. We noticed your request mentions a camera, whereas order ORD-1008 is for a Smart Fitness Watch. Could you please confirm if this request is for the Smart Fitness Watch or an alternate order?",
        "response": "Apologies for the mix-up! I was referencing order ORD-1008 for my Smart Fitness Watch, which stopped charging.",
        "timestamp": "2026-09-26T13:00:00Z",
        "evidence_ids": []
      }
    ]
    ```

#### Expected Edge-Case Behaviors
- **Generic Phrasing Passes**: Generic phrasing (e.g. *"The item arrived defective"*, *"Package was damaged in transit"*, *"I would like to return my order"*) does NOT trigger a mismatch.
- **Partial/Colloquial Names Pass**: Partial titles (e.g. *"the fitness watch strap broke"*, *"chair armrest snapped"*) correctly match the catalog and proceed with standard policy evaluation without clarification pause.
- **Clarification Exhaustion**: Submitting two consecutive responses that both maintain the product mismatch exhausts the 2-cycle threshold, routing to `decision: "escalate"`, `status: "escalated"`.

---

### TC-17: Wrong Item Photo Evidence Verification & Multimodal Inspection
- **Endpoint**: `POST /refunds` (Intake) $\rightarrow$ `GET /refunds/{refund_id}` (Pause) $\rightarrow$ `POST /refunds/{refund_id}/evidence` (Upload) $\rightarrow$ `GET /refunds/{refund_id}` (Inspection)
- **Goal**: Validate end-to-end processing of `wrong_item` claims using Swagger UI. Automated approval without photographic evidence is strictly prohibited; the request must pause in `status: "awaiting_clarification"` with `failed_rules: ["wrong_item_verification"]` and request clear photos of the incorrect item and packing slip or shipping label. Uploading photographic evidence via `POST /refunds/{refund_id}/evidence` automatically resumes workflow execution in the background, invoking Bedrock multimodal vision inspection to evaluate the item against order records (`ORD-1002`, *Noise-Cancelling Headphones*, $500.00).

> [!IMPORTANT]
> **Multimodal Vision Verification Rules for Wrong Item Claims**:
> - **Mandatory Upfront Proof**: Claims classified under `wrong_item` require photo proof before policy evaluation can pass. If submitted without an image, policy evaluation pauses at `awaiting_clarification`.
> - **Verified Discrepancy (Auto-Approve)**: If multimodal inspection confirms the customer received a distinct, incorrect product or variant (e.g., received a keyboard, desk fan, or different model) or the packing slip shows an incorrect SKU, policy passes (`policy_status: "pass"`) routing to `decision: "auto_approve"`, `status: "completed"`.
> - **Refuted Claim / Correct Item Depicted (Auto-Deny)**: If multimodal inspection determines the photo shows the correct ordered product matching catalog specifications, policy fails (`policy_status: "fail"`, `failed_rules: ["wrong_item_verification"]`) routing to `decision: "deny"`, `status: "completed"`.
> - **Inconclusive / Blurry Photo (Supervisor Escalation)**: If the photo is blurry, corrupted, unrecognizable, or does not clearly show the item or shipping labels, policy concludes `policy_status: "ambiguous"` routing to `decision: "escalate"`, `status: "escalated"` for supervisor review.

#### Step 1: Initial Submission Without Photo Proof
- **Action in Swagger UI**:
  1. Expand `POST /refunds`.
  2. In the request body, submit a `wrong_item` refund claim for order `ORD-1002` without attaching any files:
     ```json
     {
       "order_id": "ORD-1002",
       "customer_request_text": "I received the wrong item in my package. Instead of the Noise-Cancelling Headphones I ordered, the delivery box contained a computer keyboard."
     }
     ```
  3. Click **Execute**.
- **CLI Alternative (`curl`)**:
  ```bash
  curl -X POST "http://127.0.0.1:8000/refunds" \
    -H "Content-Type: application/json" \
    -d '{
      "order_id": "ORD-1002",
      "customer_request_text": "I received the wrong item in my package. Instead of the Noise-Cancelling Headphones I ordered, the delivery box contained a computer keyboard."
    }'
  ```
- **Expected Status**: `202 Accepted`
- **Step 1 Expected Output**:
  ```json
  {
    "refund_id": "ref_...",
    "order_id": "ORD-1002",
    "status": "pending",
    "created_at": "2026-09-26T..."
  }
  ```
  *(Copy the returned `refund_id` for subsequent verification steps)*.

#### Step 2: Verification of Mandatory Wrong Item Proof Pause
- **Action**: Wait 2–3 seconds for initial intake and classifier execution, then execute `GET /refunds/{refund_id}`.
- **Expected Status**: `200 OK`
- **Expected Output**:
  - `status`: `"awaiting_clarification"` *(Note: Auto-approval is blocked; photo evidence is required)*
  - `decision`: `null`
  - `category`: `"wrong_item"`
  - `policy_status`: `"ambiguous"`
  - `failed_rules`: `["wrong_item_verification"]`
  - `clarification_count`: `1`
  - `clarification_prompt`: Formatted customer inquiry email:
    - Explicitly requests clear photos of the incorrect item received.
    - Requests clear photos of the exterior shipping label and packing slip on the package.
    - Specifies supported image formats (JPEG, PNG, WebP ≤ 5MB).
  - `clarification_history`:
    ```json
    [
      {
        "cycle": 1,
        "prompt": "Dear Customer,\n\nThank you for reaching out regarding order ORD-1002. You indicated that you received an incorrect item instead of your Noise-Cancelling Headphones.\n\nTo help us verify and resolve this issue, please provide:\n1. A clear photograph of the incorrect item received, including any visible brand/model labels.\n2. A clear photograph of the shipping label and packing slip on or inside the package.\n\nSupported formats: JPEG, PNG, WebP (up to 5MB).\n\nSincerely,\nCustomer Support Team",
        "response": null,
        "timestamp": "2026-09-26T14:00:00Z",
        "evidence_ids": []
      }
    ]
    ```

#### Step 3: Customer Uploads Wrong Item Photo Proof
- **Action in Swagger UI**:
  1. Expand `POST /refunds/{refund_id}/evidence`.
  2. Input `refund_id`: `<refund_id_from_step_1>`.
  3. Under `file`, select a valid image file depicting the received item (`received_wrong_keyboard.jpg`, JPEG/PNG/WebP ≤ 5MB).
  4. Click **Execute**.
- **CLI Alternative (`curl`)**:
  ```bash
  curl -X POST "http://127.0.0.1:8000/refunds/<refund_id>/evidence" \
    -F "file=@received_wrong_keyboard.jpg;type=image/jpeg"
  ```
- **Expected Status**: `201 Created`
- **Expected Output**:
  ```json
  {
    "refund_id": "ref_...",
    "order_id": "ORD-1002",
    "evidence": [
      {
        "evidence_id": "evi_...",
        "storage_key": "evidence/ref_.../received_wrong_keyboard.jpg",
        "filename": "received_wrong_keyboard.jpg",
        "content_type": "image/jpeg",
        "size_bytes": 65432,
        "url": "/static/uploads/evidence/ref_.../received_wrong_keyboard.jpg",
        "created_at": "2026-09-26T..."
      }
    ]
  }
  ```

> [!NOTE]
> **Automatic Workflow Resumption**: Calling `POST /refunds/{refund_id}/evidence` on an `awaiting_clarification` claim automatically triggers `resume_refund_workflow` in the background. The server associates `evi_...` with `clarification_history[0].evidence_ids` and resumes graph execution directly to `policy_checker` with the photo bytes attached. No separate call to `/clarify` is needed.

#### Step 4: Verification of Multimodal Vision Inspection Outcomes
Wait 3–4 seconds for Bedrock vision agent processing, then execute `GET /refunds/{refund_id}`.

Depending on the image submitted, verify the corresponding evaluation outcome:

##### Outcome 1: Discrepancy Verified — Distinct Item Received (Auto-Approval)
- **Image Scenario**: Uploaded photo depicts an item distinct from Noise-Cancelling Headphones (e.g. computer keyboard, speaker, or different model).
- **Expected Status**: `200 OK`
- **Expected Output**:
  - `status`: `"completed"`
  - `decision`: `"auto_approve"`
  - `failed_rules`: `[]`
  - `reasoning`: Confirms physical inspection verified the discrepancy: `"Multimodal vision inspection confirmed received item does not match ordered Noise-Cancelling Headphones; wrong item verification passed."`
  - `approval_email_text`: Populated with RMA number (`RMA-1002-...`) and clear return instructions.
  - `denial_email_text`: `null`
  - `clarification_history`:
    ```json
    [
      {
        "cycle": 1,
        "prompt": "Dear Customer,\n\nThank you for reaching out regarding order ORD-1002...",
        "response": null,
        "timestamp": "2026-09-26T14:00:00Z",
        "evidence_ids": [
          "evi_..."
        ]
      }
    ]
    ```

##### Outcome 2: Claim Refuted — Correct Item Depicted (Auto-Denial)
- **Image Scenario**: Uploaded photo depicts the correct ordered item (Noise-Cancelling Headphones) in original condition.
- **Expected Status**: `200 OK`
- **Expected Output**:
  - `status`: `"completed"`
  - `decision`: `"deny"`
  - `failed_rules`: `["wrong_item_verification"]`
  - `reasoning`: Explicitly refutes claim: `"Evidence refutes claim; uploaded photo depicts the correct ordered Noise-Cancelling Headphones matching order specifications."`
  - `approval_email_text`: `null`
  - `denial_email_text`: Polite explanation detailing that the uploaded photo depicts the correct ordered product, with support contact details and **NO RMA number**.

##### Outcome 3: Inconclusive / Blurry Photo (Supervisor Escalation)
- **Image Scenario**: Uploaded photo is blurry, corrupted, unrecognizable, or poorly lit such that the product brand and packing slip cannot be identified.
- **Expected Status**: `200 OK`
- **Expected Output**:
  - `status`: `"escalated"`
  - `decision`: `"escalate"`
  - `policy_status`: `"ambiguous"`
  - `failed_rules`: `["wrong_item_verification"]`
  - `reasoning`: Indicates inconclusive photo evidence: `"Uploaded photo evidence is inconclusive and cannot confirm product identity; routing to supervisor escalation."`
  - `approval_email_text`: `null`
  - `denial_email_text`: `null`

#### Expected Edge-Case Behaviors
- **Clarification Exhaustion After 2 Unsuccessful Cycles**: If a customer responds twice via `POST /refunds/{refund_id}/clarify` without attaching valid photos or resolving the question, the system increments `clarification_count` to 2 and escalates to human review (`decision: "escalate"`, `status: "escalated"`).
- **Hard Constraints Take Immediate Precedence**: If an order has an expired return window (`> 30 days`) or was never marked as delivered, the policy checker fails deterministically upfront without pausing for wrong-item photos or invoking multimodal vision models.
- **Supervisor Proof Request (Integration with TC-15)**: If escalated due to inconclusive evidence, a supervisor can call `POST /refunds/{refund_id}/request-proof` to prompt the customer for clearer photos or a direct image of the packing slip.


