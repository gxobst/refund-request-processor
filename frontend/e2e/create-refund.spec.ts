import { test, expect } from '@playwright/test'
import { setupMockApi } from './support/mockApi'

test.describe('Refund Creation Modal', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockApi(page)
  })

  test('validates required inputs and submits a new refund request successfully', async ({
    page,
  }) => {
    await page.goto('/')

    // 1. Click "New Refund" button to open modal
    const newRefundButton = page.getByTestId('new-refund-button')
    await newRefundButton.click()

    const modalTitle = page.getByRole('heading', { name: 'Submit Refund Request' })
    await expect(modalTitle).toBeVisible()

    // 2. Submitting empty form triggers required validation errors
    const submitButton = page.getByTestId('create-refund-submit-button')
    await submitButton.click()

    const orderIdError = page.getByTestId('order-id-error')
    await expect(orderIdError).toBeVisible()
    await expect(orderIdError).toContainText('Order ID must follow the pattern ORD-####')

    const explanationError = page.getByTestId('explanation-error')
    await expect(explanationError).toBeVisible()
    await expect(explanationError).toContainText('Customer explanation is required')

    // 3. Fill in Order ID and Customer Explanation
    const orderIdInput = page.getByTestId('create-order-id-input')
    await orderIdInput.fill('ORD-2025')

    const explanationInput = page.getByTestId('customer-request-textarea')
    await explanationInput.fill('The package arrived torn with contents missing from the parcel.')

    // Character counter updates
    const charCounter = page.getByTestId('character-counter')
    await expect(charCounter).toBeVisible()
    await expect(charCounter).not.toHaveText('0 characters')

    // Submit valid form
    await submitButton.click()

    // 4. Verify modal is dismissed and new refund is prepended to queue table
    await expect(modalTitle).not.toBeVisible()
    await expect(page.getByText('ORD-2025')).toBeVisible()
  })

  test('cancel button closes modal and resets form inputs', async ({ page }) => {
    await page.goto('/')

    await page.getByTestId('new-refund-button').click()
    const modalTitle = page.getByRole('heading', { name: 'Submit Refund Request' })
    await expect(modalTitle).toBeVisible()

    await page.getByTestId('create-order-id-input').fill('ORD-9999')
    await page.getByTestId('create-refund-cancel-button').click()

    await expect(modalTitle).not.toBeVisible()

    // Reopen modal and confirm input was reset
    await page.getByTestId('new-refund-button').click()
    await expect(page.getByTestId('create-order-id-input')).toHaveValue('')
  })
})
