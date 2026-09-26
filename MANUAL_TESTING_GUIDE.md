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
| **TC-03** | Max Order Amount Escalation | Order amount exceeding threshold ($750 > $500) escalates to human review | `ORD-1003` | `escalate` / `escalated` |
| **TC-04** | Expired Return Window Denial & Denial Email | Date window violation (> 30 days) triggers denial + automated denial email | `ORD-1004` | `deny` / `completed` |
| **TC-05** | Single Tool Carrier Verification | Autonomous `query_carrier_tracking` tool call for delayed delivery | `ORD-1005` | `auto_approve` / `completed` |
| **TC-06** | Mandatory Dual Tool Verification (FedEx & Stripe) | High-value order (≥ $400) mandates both carrier & payment tool audit records | `ORD-1010` | `auto_approve` / `completed` |
| **TC-07** | Clarification Loop Lifecycle | Low confidence (< 0.70) pause (persists `category` & diagnostics) -> customer response -> resolution | `ORD-1008` | `awaiting_clarification` -> `auto_approve` |
| **TC-08** | Clarification Exhaustion to Escalation | 2-cycle clarification exhaustion (low confidence < 0.70) -> human escalation | `ORD-1009` | `awaiting_clarification` (cycles 1 & 2) -> `escalate` / `escalated` |
| **TC-09** | Supervisor Manual Override | Supervisor manual override on escalated TC-08 refund (`approve` or `deny`) | `ORD-1009` | `approve` or `deny` / `completed` |
| **TC-10** | Multipart Damage Evidence Upload | Interactive file picker upload (Swagger UI WebKit boundary support, JPEG/PNG/WebP ≤ 5MB; video rejected) | Any active refund | HTTP 201 (`evidence` array populated) |
| **TC-11** | Multimodal Image Inspection | Multimodal Bedrock vision agent verifies damage in attached photo | `ORD-1001` | `auto_approve` (damage verified) |
| **TC-12** | Initial Refund Creation with Attached Image | Multipart `POST /refunds` with upfront image proof (case-sensitive boundary support) | `ORD-1001` | HTTP 202 (`evidence` populated on intake) |
| **TC-13** | Queue Listing and Filtering | DynamoDB querying with status filter (`completed`, `escalated`, etc.) | N/A | HTTP 200 (filtered list) |
| **TC-14** | Input Validation & Error Boundaries | Order ID regex (`^ORD-\d{4}$`), blank fields, 404s, video rejection, 5MB limit, request-proof validation | N/A | HTTP 400, 404, 413, 422 |
| **TC-15** | Supervisor Proof Request from Escalation Queue | Human supervisor requests targeted photo proof via `POST /refunds/{id}/request-proof` | `ORD-1009` | `escalated` -> `awaiting_clarification` (HTTP 200) |
| **TC-16** | Product Mismatch Detection & Escalation | Customer request product conflicts with ordered item (e.g. camera for fitness watch) | `ORD-1008` | `escalate` / `escalated` (`policy_status: "ambiguous"`) |

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

### TC-03: Max Order Amount Threshold Escalation
- **Endpoint**: `POST /refunds` followed by `GET /refunds/{refund_id}`
- **Goal**: Confirm that orders exceeding the policy maximum order amount (`$750.00 > $500.00` limit for `damaged` in `ORD-1003`) are NOT auto-denied, but instead route to human supervisor escalation (`decision: "escalate"`, `status: "escalated"`, `policy_status: "ambiguous"`).
- **Input (`POST /refunds`)**:
  ```json
  {
    "order_id": "ORD-1003",
    "customer_request_text": "The gaming monitor arrived with a completely shattered OLED panel and cracked stand."
  }
  ```
- **Step 1 Expected Output**: `202 Accepted`
- **Step 2 (`GET /refunds/{refund_id}`) Expected Output**: `200 OK`
  - `status`: `"escalated"`
  - `decision`: `"escalate"`
  - `policy_status`: `"ambiguous"`
  - `failed_rules`: `["max_order_amount"]`
  - `reasoning`: Cites order amount threshold escalation (`"Order amount ($750.0) exceeds maximum threshold ($500.0); requires supervisor escalation."`).
  - `approval_email_text`: `null`
  - `denial_email_text`: `null`

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
    - `clarification_prompt`: Formatted customer inquiry email prompting for clarification.
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

### TC-10: Customer Damage Evidence Upload (Interactive Swagger UI File Picker)
- **Endpoint**: `POST /refunds/{refund_id}/evidence`
- **Goal**: Verify multipart image file upload using Swagger UI's interactive file selector (`<input type="file">`). Only images (JPEG, PNG, WebP ≤ 5MB) are supported; videos are rejected.
- **Instructions in Swagger UI**:
  1. Navigate to `POST /refunds/{refund_id}/evidence` and click **Try it out**.
  2. Input an active `refund_id`.
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

> [!NOTE]
> **Swagger UI & Browser Boundary Support**: The server preserves case sensitivity in request headers. Browser-generated WebKit boundary tokens (e.g. `boundary=----WebKitFormBoundary...`) are parsed accurately without returning false `No file uploaded in multipart request` errors.

---

### TC-11: Multimodal Vision Inspection of Customer Damage Photo
- **Endpoint**: `POST /refunds` followed by `POST /refunds/{refund_id}/evidence`
- **Goal**: When a claim is categorized as `damaged` and an image is attached, verify that deterministic pass is bypassed and the multimodal Bedrock agent inspects image bytes for visible damage.
- **Multimodal Evaluation Behavior**:
  - The multimodal vision agent reads the uploaded image content bytes directly and checks if the photo confirms the reported damage.
  - If damage is clearly identified and matches the claim, it proceeds directly to approval.
  - If the model is uncertain or the image does not show identifiable damage (low confidence), it routes the request to `status: "escalated"` for supervisor review.
- **Step 1 (`POST /refunds`)**:
  ```json
  {
    "order_id": "ORD-1001",
    "customer_request_text": "The chair arrived broken with cracked plastic framing."
  }
  ```
  *(Copy returned `refund_id`)*.
- **Step 2 (`POST /refunds/{refund_id}/evidence`)**:
  - Upload a photo depicting visible product damage.
- **Step 3 (`GET /refunds/{refund_id}`)**:
  - `status`: `"completed"`
  - `decision`: `"auto_approve"`
  - `reasoning`: Explicitly confirms physical damage observed in proof photo.
  - `approval_email_text`: RMA generated with return instructions.

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
    "clarification_count": 3
  }
  ```
- **Step 2 Customer Evidence Submission**:
  - Customer can now upload the requested photo using `POST /refunds/{refund_id}/evidence` (via the Swagger file selector).
  - Or respond with text details using `POST /refunds/{refund_id}/clarify`.
  - The workflow resumes processing upon submission.

---

### TC-16: Product Mismatch Detection & Escalation
- **Endpoint**: `POST /refunds` followed by polling `GET /refunds/{refund_id}`
- **Goal**: Verify that when a customer refund request explicitly describes a product conflicting with the item recorded in the order database (e.g., claiming a refund for an "OLED gaming monitor" or "mirrorless camera" when order `ORD-1008` is actually for a "Smart Fitness Watch"), the system detects the discrepancy. Automated approval is overridden, and the request is routed to `policy_status: "ambiguous"` and `status: "escalated"` (`decision: "escalate"`) for human supervisor review.
- **Step 1 (`POST /refunds`) Input**:
  ```json
  {
    "order_id": "ORD-1008",
    "customer_request_text": "I ordered this mirrorless camera but received the wrong lens bundle. I would like to return it for a refund."
  }
  ```
- **Step 1 Expected Output**: `202 Accepted`
  ```json
  {
    "refund_id": "ref_...",
    "order_id": "ORD-1008",
    "status": "pending",
    "created_at": "..."
  }
  ```
- **Step 2 Verification (`GET /refunds/{refund_id}`)**:
  - Wait 2–3 seconds for the agent evaluation.
  - **Expected Status**: `200 OK`
  - **Expected Fields**:
    - `status`: `"escalated"`
    - `decision`: `"escalate"`
    - `policy_status`: `"ambiguous"`
    - `reasoning`: Explicitly identifies the product conflict (e.g. `"Customer request describes 'camera' which does not match ordered item 'Smart Fitness Watch'"`).
    - `approval_email_text`: `null`
    - `denial_email_text`: `null`
- **Expected Edge-Case Behaviors**:
  - **Generic Phrasing Passes**: Generic phrasing (e.g. *"The item arrived damaged"*, *"My package was crushed"*, *"The product is defective"*) is treated neutrally and does NOT trigger a mismatch.
  - **Partial/Colloquial Names Pass**: Partial titles (e.g. *"the fitness watch strap broke"*, *"chair armrest snapped"*) correctly match and proceed with standard policy evaluation.

