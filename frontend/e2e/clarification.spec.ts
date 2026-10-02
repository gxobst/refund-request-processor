import { test, expect } from '@playwright/test'
import { setupMockApi } from './support/mockApi'

test.describe('Customer Clarification Modal and Portal Routing', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockApi(page)
  })

  test('opens clarification modal via URL query param, displays inquiry prompt, validates input, updates counter, and cancels', async ({
    page,
  }) => {
    // 1. Open customer clarification portal via ?clarify=ref-103
    await page.goto('/?clarify=ref-103')

    const modalTitle = page.getByRole('heading', { name: 'Customer Clarification Portal' })
    await expect(modalTitle).toBeVisible()

    // 2. Verify Order ID and Inquiry Prompt display
    const orderIdElem = page.getByTestId('clarification-order-id')
    await expect(orderIdElem).toHaveText('ORD-1003')

    const inquiryPromptElem = page.getByTestId('clarification-inquiry-prompt')
    await expect(inquiryPromptElem).toBeVisible()
    await expect(inquiryPromptElem).toContainText('Please upload a photo of the exterior shipping box')

    // 3. Submitting empty or whitespace response shows validation error
    const submitButton = page.getByTestId('clarification-submit-button')
    await submitButton.click()

    const responseError = page.getByTestId('clarification-response-error')
    await expect(responseError).toBeVisible()
    await expect(responseError).toContainText('Clarification response is required')

    // 4. Entering response text updates character counter
    const textarea = page.getByTestId('clarification-response-textarea')
    await textarea.fill('Here are the details requested regarding the exterior shipping package.')

    const counter = page.getByTestId('clarification-character-counter')
    await expect(counter).toContainText('71 characters')
    await expect(responseError).not.toBeVisible()

    // 5. Dismiss/cancel modal via cancel button
    const cancelButton = page.getByTestId('clarification-cancel-button')
    await cancelButton.click()

    await expect(modalTitle).not.toBeVisible()
  })

  test('opens clarification modal from drawer "Submit Clarification" action button for awaiting_clarification refund', async ({
    page,
  }) => {
    await page.goto('/')

    // Review/inspect ORD-1003 which has status awaiting_clarification
    const inspectBtn = page.getByRole('button', { name: /Review order ORD-1003/i })
    await inspectBtn.click()

    const clarifyBtn = page.getByTestId('drawer-clarify-button')
    await expect(clarifyBtn).toBeVisible()
    await clarifyBtn.click()

    // Modal renders
    const modalTitle = page.getByRole('heading', { name: 'Customer Clarification Portal' })
    await expect(modalTitle).toBeVisible()
    await expect(page.getByTestId('clarification-order-id')).toHaveText('ORD-1003')
  })
})
