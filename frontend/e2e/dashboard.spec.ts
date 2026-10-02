import { test, expect } from '@playwright/test'
import { setupMockApi } from './support/mockApi'

test.describe('Dashboard Load and Layout', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockApi(page)
  })

  test('verifies page title, Header brand, metrics / queue summary counts, queue table container with headers, and action buttons', async ({
    page,
  }) => {
    await page.goto('/')

    // 1. Verify page title and Header branding
    await expect(page).toHaveTitle('AI Refund Request Processor')
    const headerBrand = page.getByRole('heading', { name: 'AI Refund Request Processor' })
    await expect(headerBrand).toBeVisible()

    // 2. Verify queue summary counts / indicators
    // Active tab count badge displays total count of refunds (5 mock records)
    const allTabCount = page.getByTestId('tab-count-all')
    await expect(allTabCount).toBeVisible()
    await expect(allTabCount).toHaveText('5')

    // Polling indicator renders live state
    const pollingStatus = page.getByTestId('polling-status')
    await expect(pollingStatus).toBeVisible()

    // 3. Verify refund queue table container renders with standard table headers
    const tableContainer = page.getByTestId('refund-queue-table-container')
    await expect(tableContainer).toBeVisible()

    const expectedHeaders = [
      'Order ID',
      'Customer Request',
      'Category',
      'Amount',
      'Decision',
      'Status',
      'Timestamp',
      'Actions',
    ]
    for (const header of expectedHeaders) {
      await expect(tableContainer.getByRole('columnheader', { name: header })).toBeVisible()
    }

    // 4. Verify "New Refund" button and "Refresh" button are visible and enabled
    const newRefundButton = page.getByTestId('new-refund-button')
    await expect(newRefundButton).toBeVisible()
    await expect(newRefundButton).toBeEnabled()

    const refreshButton = page.getByRole('button', { name: /refresh/i }).first()
    await expect(refreshButton).toBeVisible()
    await expect(refreshButton).toBeEnabled()
  })
})
