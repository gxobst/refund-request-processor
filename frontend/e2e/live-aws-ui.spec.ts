import { test, expect } from '@playwright/test'

/**
 * End-to-End browser UI clickthrough test suite running against the LIVE backend
 * connected to live AWS services (Amazon Bedrock us.amazon.nova-2-lite-v1:0,
 * live DynamoDB tables, and local Vite frontend).
 *
 * Covers scenarios defined in _docs/MANUAL_TESTING_GUIDE.md:
 * - TC-01: System Health, Polling & Header Live State
 * - TC-14: Input Validation & Error Boundaries
 * - TC-20: Client-Side Image Dimension Pre-Validation
 * - TC-26: Dynamic Policy Rules Inspection Modal
 * - TC-13 & TC-23: Status Tab Filtering & CSV Export Download
 * - TC-02: Clear-Cut Auto-Approval & RMA Email Generation (ORD-1007)
 * - TC-04: Expired Return Window Denial (ORD-1004)
 * - TC-07 & TC-16: Clarification Loop Lifecycle & Resolution (ORD-1008)
 * - TC-03 & TC-19: Tiered RBAC Approval Limits & Senior Manager Override (ORD-1003)
 */

test.describe('Live AWS UI Clickthrough - Manual Testing Guide Verification', () => {
  test.beforeEach(async ({ page }) => {
    // Reset local state to ensure clean role and credentials on initial load
    await page.addInitScript(() => {
      window.localStorage.clear()
    })
    await page.goto('/')
    await expect(page.getByTestId('system-health-badge')).toBeVisible({ timeout: 15000 })
  })

  test('TC-01: System Health, Live Header Status & Role Indicators', async ({ page }) => {
    test.setTimeout(45000)

    // 1. Verify System Operational Health Badge
    const healthBadge = page.getByTestId('system-health-badge')
    await expect(healthBadge).toBeVisible()
    await expect(healthBadge).toContainText('System Operational')

    // 2. Verify Auth Status Badge
    const authBadge = page.getByTestId('auth-status-badge')
    await expect(authBadge).toBeVisible()

    // 3. Verify Role Switcher initializes and can be toggled
    const roleSwitcher = page.getByTestId('role-switcher')
    await expect(roleSwitcher).toBeVisible()
    await expect(roleSwitcher).toContainText(/Agent|Supervisor|Senior Manager/)

    // 4. Verify Policy Rules and Analytics action buttons in Header
    await expect(page.getByTestId('policy-rules-button')).toBeVisible()
    await expect(page.getByTestId('analytics-button')).toBeVisible()
  })

  test('TC-14: Intake Validation & RFC Error Boundaries', async ({ page }) => {
    test.setTimeout(45000)

    // Open Create Refund modal
    await page.getByTestId('new-refund-button').click()
    const modalTitle = page.getByRole('heading', { name: 'Submit Refund Request' })
    await expect(modalTitle).toBeVisible()

    // Submit empty form -> triggers field validation errors
    await page.getByTestId('create-refund-submit-button').click()

    const orderIdError = page.getByTestId('order-id-error')
    await expect(orderIdError).toBeVisible()
    await expect(orderIdError).toContainText('Order ID must follow the pattern ORD-####')

    const explanationError = page.getByTestId('explanation-error')
    await expect(explanationError).toBeVisible()
    await expect(explanationError).toContainText('Customer explanation is required')

    // Test malformed order ID
    await page.getByTestId('create-order-id-input').fill('INVALID-123')
    await page.getByTestId('customer-request-textarea').fill('Testing invalid input format.')
    await page.getByTestId('create-refund-submit-button').click()

    await expect(orderIdError).toBeVisible()
    await expect(orderIdError).toContainText('Order ID must follow the pattern ORD-####')

    // Cancel modal
    await page.getByTestId('create-refund-cancel-button').click()
    await expect(modalTitle).not.toBeVisible()
  })

  test('TC-20: Client-Side Image Dimension Pre-Validation (< 50x50 Rejection)', async ({ page }) => {
    test.setTimeout(45000)

    await page.getByTestId('new-refund-button').click()

    // Construct a sub-50px (1x1 pixel) PNG buffer
    const sub50pxPngBase64 =
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
    const imageBuffer = Buffer.from(sub50pxPngBase64, 'base64')

    // Set file input on hidden input element
    const fileInput = page.getByTestId('file-picker-input')
    await fileInput.setInputFiles({
      name: 'micro-thumbnail.png',
      mimeType: 'image/png',
      buffer: imageBuffer,
    })

    // Dimension error alert banner must appear immediately
    const dimensionError = page.getByTestId('evidence-dimension-error')
    await expect(dimensionError).toBeVisible({ timeout: 5000 })
    await expect(dimensionError).toContainText('below minimum required resolution of 50x50 pixels')

    // Dismiss modal
    await page.getByTestId('create-refund-cancel-button').click()
  })

  test('TC-26: Dynamic Policy Rules Inspection Modal', async ({ page }) => {
    test.setTimeout(45000)

    // Click Policy Rules in Header
    await page.getByTestId('policy-rules-button').click()

    // Expect modal with heading to appear
    const dialogTitle = page.getByRole('heading', { name: 'Refund Policy Configuration' })
    await expect(dialogTitle).toBeVisible()

    // Verify Active Policies tab is selected and displays categories from live backend
    await expect(page.getByTestId('tab-active-policies')).toBeVisible()
    await expect(page.getByTestId('category-badge-damaged')).toBeVisible()
    await expect(page.getByTestId('category-badge-wrong_item')).toBeVisible()
    await expect(page.getByTestId('category-badge-changed_mind')).toBeVisible()
    await expect(page.getByTestId('category-badge-late_delivery')).toBeVisible()

    // Close modal
    await page.keyboard.press('Escape')
    await expect(dialogTitle).not.toBeVisible()
  })

  test('TC-13 & TC-23: Status Tab Filtering & Custom CSV Export', async ({ page }) => {
    test.setTimeout(45000)

    // 1. Verify Status Tabs exist and can be clicked
    const tabs = ['all', 'pending', 'completed', 'escalated', 'awaiting_clarification']
    for (const tabId of tabs) {
      const tabButton = page.getByRole('tab', { name: new RegExp(tabId.replace(/_/g, ' '), 'i') })
      await expect(tabButton).toBeVisible()
    }

    // Switch to "Completed" tab
    await page.getByRole('tab', { name: /completed/i }).click()
    await page.waitForTimeout(500)

    // Switch back to "All" tab
    await page.getByRole('tab', { name: /^all$/i }).click()
    await page.waitForTimeout(500)

    // 2. Test CSV Export dropdown
    const exportDropdownButton = page.getByTestId('export-dropdown-button')
    if (await exportDropdownButton.isEnabled()) {
      await exportDropdownButton.click()
      const exportCsvButton = page.getByTestId('export-csv-button')
      await expect(exportCsvButton).toBeVisible()

      // Listen for download
      const downloadPromise = page.waitForEvent('download')
      await exportCsvButton.click()
      const download = await downloadPromise
      expect(download.suggestedFilename()).toMatch(/\.csv$/i)
    }
  })

  test('TC-02: Clear-Cut Auto-Approval & RMA Email Generation (Live AWS Bedrock & DynamoDB)', async ({
    page,
  }) => {
    test.setTimeout(90000)

    // 1. Open New Refund Modal
    await page.getByTestId('new-refund-button').click()

    // 2. Enter ORD-1007 (Designer Wool Sweater, delivered, $200.00, changed mind within 14 days)
    await page.getByTestId('create-order-id-input').fill('ORD-1007')
    await page
      .getByTestId('customer-request-textarea')
      .fill('The sweater is unworn with original tags attached in original packaging. I changed my mind.')

    // Submit refund request
    await page.getByTestId('create-refund-submit-button').click()

    // 3. Confirm modal closes
    await expect(page.getByRole('heading', { name: 'Submit Refund Request' })).not.toBeVisible({ timeout: 30000 })

    // 4. Poll queue table until the new refund appears and reaches "completed" status
    const refundRow = page.locator('tr[data-testid="refund-row"]', { hasText: 'ORD-1007' }).first()
    await expect(refundRow).toBeVisible({ timeout: 15000 })

    // Wait for the workflow to complete via live Bedrock / DynamoDB
    await expect
      .poll(
        async () => {
          const text = await refundRow.innerText()
          return text.toLowerCase()
        },
        {
          message: 'Waiting for live Bedrock workflow to complete ORD-1007 auto-approval',
          timeout: 60000,
          intervals: [2000, 3000, 4000],
        }
      )
      .toMatch(/(completed|auto_approve|approved)/i)

    // 5. Click "Review / Inspect" to open the detail drawer
    await refundRow.getByRole('button', { name: /review/i }).click()

    // Verify detail drawer opened with Order ORD-1007
    await expect(page.getByTestId('detail-refund-id')).toBeVisible()
    await expect(page.getByRole('heading', { name: /Order ORD-1007/i })).toBeVisible()

    // Check customer email draft container
    const emailDraft = page.getByTestId('email-draft-container')
    await expect(emailDraft).toBeVisible()
    await expect(emailDraft).toContainText(/RMA-1007|approved|refund/i)

    // Close drawer
    await page.getByTestId('drawer-close-button').click()
    await expect(page.getByTestId('detail-refund-id')).not.toBeVisible()
  })

  test('TC-04: Expired Return Window Denial & Denial Email (Live AWS Bedrock)', async ({ page }) => {
    test.setTimeout(90000)

    // 1. Submit refund for ORD-1004 (Keyboard delivered 2026-08-05 > 30 days return window)
    await page.getByTestId('new-refund-button').click()
    await page.getByTestId('create-order-id-input').fill('ORD-1004')
    await page
      .getByTestId('customer-request-textarea')
      .fill('The mechanical keyboard keys are sticking. Purchased over two months ago.')

    await page.getByTestId('create-refund-submit-button').click()
    await expect(page.getByRole('heading', { name: 'Submit Refund Request' })).not.toBeVisible({ timeout: 30000 })

    // 2. Wait for live Bedrock policy checker to detect window expiration and deny
    const refundRow = page.locator('tr[data-testid="refund-row"]', { hasText: 'ORD-1004' }).first()
    await expect(refundRow).toBeVisible({ timeout: 15000 })

    await expect
      .poll(
        async () => {
          const text = await refundRow.innerText()
          return text.toLowerCase()
        },
        {
          message: 'Waiting for live Bedrock policy checker to deny ORD-1004 due to expired return window',
          timeout: 60000,
          intervals: [2000, 3000, 4000],
        }
      )
      .toMatch(/(completed|deny|denied)/i)

    // 3. Inspect drawer for denial reason and denial email
    await refundRow.getByRole('button', { name: /review/i }).click()
    await expect(page.getByTestId('detail-refund-id')).toBeVisible()
    await expect(page.getByRole('heading', { name: /Order ORD-1004/i })).toBeVisible()

    // Switch to Denial Draft tab
    await page.getByRole('button', { name: 'Denial Draft' }).click()
    const emailDraft = page.getByTestId('email-draft-container')
    await expect(emailDraft).toBeVisible()
    await expect(emailDraft).toContainText(/window|policy|unable|regret|cannot|denied/i)

    await page.getByTestId('drawer-close-button').click()
  })

  test('TC-07 & TC-16: Customer Clarification Loop with Workflow Resumption (ORD-1008)', async ({
    page,
  }) => {
    test.setTimeout(180000)

    // 1. Submit refund with mismatch description: customer claims camera for ORD-1008 (Smart Fitness Watch)
    await page.getByTestId('new-refund-button').click()
    await page.getByTestId('create-order-id-input').fill('ORD-1008')
    await page
      .getByTestId('customer-request-textarea')
      .fill('I want to return the camera because it does not fit.')

    await page.getByTestId('create-refund-submit-button').click()
    await expect(page.getByRole('heading', { name: 'Submit Refund Request' })).not.toBeVisible({ timeout: 30000 })

    const refundRow = page.locator('tr[data-testid="refund-row"]', { hasText: 'ORD-1008' }).first()
    await expect(refundRow).toBeVisible({ timeout: 15000 })

    // 2. Wait for live Bedrock to detect product ambiguity and pause in awaiting_clarification
    await expect
      .poll(
        async () => {
          const text = await refundRow.innerText()
          return text.toLowerCase()
        },
        {
          message: 'Waiting for live Bedrock to pause ORD-1008 in awaiting_clarification',
          timeout: 60000,
          intervals: [2000, 3000, 4000],
        }
      )
      .toMatch(/(awaiting_clarification|clarification)/i)

    // 3. Open drawer and click Submit Clarification
    await refundRow.getByRole('button', { name: /review/i }).click()
    await expect(page.getByTestId('drawer-clarify-button')).toBeVisible()
    await page.getByTestId('drawer-clarify-button').click()

    // 4. In CustomerClarificationModal, provide clarifying response
    const clarifyModalHeading = page.getByRole('heading', { name: /Customer Clarification Portal/i })
    await expect(clarifyModalHeading).toBeVisible()

    await page
      .getByTestId('clarification-response-textarea')
      .fill('I made a mistake in my description. I am returning the Smart Fitness Watch, unopened in original packaging.')

    // Submit clarification
    await page.getByTestId('clarification-submit-button').click()

    // Clarification confirmation "Done" button appears
    const doneButton = page.getByTestId('clarification-done-button')
    await expect(doneButton).toBeVisible({ timeout: 15000 })
    await doneButton.click()

    // Close drawer
    await page.getByTestId('drawer-close-button').click()

    // 5. Verify the resumed workflow completes on live Bedrock
    await expect
      .poll(
        async () => {
          const text = await refundRow.innerText()
          return text.toLowerCase()
        },
        {
          message: 'Waiting for resumed workflow to complete on live Bedrock',
          timeout: 90000,
          intervals: [2000, 3000, 4000],
        }
      )
      .toMatch(/(completed|auto_approve|approved)/i)
  })

  test('TC-03 & TC-19: High-Value Escalation & Tiered Approval Limits Override (ORD-1003)', async ({
    page,
  }) => {
    test.setTimeout(120000)

    // 1. Submit refund for ORD-1003 (Gaming Monitor, $750.00 > $500 max limit)
    await page.getByTestId('new-refund-button').click()
    await page.getByTestId('create-order-id-input').fill('ORD-1003')
    await page
      .getByTestId('customer-request-textarea')
      .fill('The gaming monitor display panel arrived shattered.')

    await page.getByTestId('create-refund-submit-button').click()
    await expect(page.getByRole('heading', { name: 'Submit Refund Request' })).not.toBeVisible({ timeout: 30000 })

    const refundRow = page.locator('tr[data-testid="refund-row"]', { hasText: 'ORD-1003' }).first()
    await expect(refundRow).toBeVisible({ timeout: 15000 })

    // 2. Live Bedrock evaluates damage / $750 amount -> reaches awaiting_clarification or escalated
    await expect
      .poll(
        async () => {
          const text = await refundRow.innerText()
          return text.toLowerCase()
        },
        {
          message: 'Waiting for live Bedrock to evaluate high-value ORD-1003',
          timeout: 60000,
          intervals: [2000, 3000, 4000],
        }
      )
      .toMatch(/(escalated|awaiting[\s_]clarification|clarification|escalate)/i)

    // 3. Ensure role in Header is Agent ($100 limit) before opening drawer
    const roleSwitcher = page.getByTestId('role-switcher')
    let currentRoleText = await roleSwitcher.innerText()
    while (!currentRoleText.includes('Agent')) {
      await roleSwitcher.click()
      currentRoleText = await roleSwitcher.innerText()
    }

    // 4. Open drawer to verify Agent role restrictions
    await refundRow.getByRole('button', { name: /review/i }).click()
    await expect(page.getByTestId('detail-refund-id')).toBeVisible()

    // As Agent ($100 limit), Manual Override button is disabled
    const disabledOverrideBtn = page.getByTestId('override-button-disabled')
    await expect(disabledOverrideBtn).toBeVisible()

    // Close drawer before switching roles
    await page.getByTestId('drawer-close-button').click()
    await expect(page.getByTestId('detail-refund-id')).not.toBeVisible()

    // 5. Switch role in Header to Supervisor ($500 limit)
    await roleSwitcher.click()
    await expect(roleSwitcher).toContainText('Supervisor ($500)')

    // Reopen drawer
    await refundRow.getByRole('button', { name: /review/i }).click()
    const activeOverrideBtn = page.getByTestId('override-action-button')
    await expect(activeOverrideBtn).toBeVisible()
    await activeOverrideBtn.click()

    // 6. In ManualOverrideModal, $750 exceeds Supervisor $500 limit
    // Verify approval limit warning banner is shown and submit button is blocked for Approve
    const limitWarning = page.getByTestId('override-limit-warning')
    await expect(limitWarning).toBeVisible()
    await expect(limitWarning).toContainText('Approval Limit Exceeded')
    await expect(page.getByTestId('override-submit-button')).toBeDisabled()

    // Cancel modal and close drawer
    await page.getByTestId('override-cancel-button').click()
    await page.getByTestId('drawer-close-button').click()
    await expect(page.getByTestId('detail-refund-id')).not.toBeVisible()

    // 7. Switch role to Senior Manager ($2,500 limit)
    await roleSwitcher.click()
    await expect(roleSwitcher).toContainText('Senior Manager ($2,500)')

    // Reopen drawer and override modal
    await refundRow.getByRole('button', { name: /review/i }).click()
    await page.getByTestId('override-action-button').click()

    // Limit warning should NOT be shown for Senior Manager ($750 <= $2,500)
    await expect(page.getByTestId('override-limit-warning')).not.toBeVisible()

    // Select Approve Refund
    await page.getByTestId('decision-choice-approve').click()
    await page
      .getByTestId('override-justification-textarea')
      .fill('Authorized override by Senior Manager: verified high-value transit carrier damage.')
    await page.getByTestId('confirm-override-checkbox').check()

    // Submit Override
    await page.getByTestId('override-submit-button').click()

    // Modal closes and record updates
    await expect(page.getByRole('heading', { name: 'Manual Decision Override' })).not.toBeVisible()
    await expect(page.getByText('ORD-1003').first()).toBeVisible()

    // Close drawer
    await page.getByTestId('drawer-close-button').click()
  })
})
