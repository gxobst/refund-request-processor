import { test, expect } from '@playwright/test'
import { setupMockApi, DEFAULT_MOCK_REFUNDS } from './support/mockApi'

test.describe('Status Filter Tabs Switching', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockApi(page)
  })

  test('updates active tab visual state, aria-selected attribute, and filters queue records correctly', async ({
    page,
  }) => {
    await page.goto('/')

    // Initial state: "All" tab is selected with 5 records
    const allTab = page.getByRole('tab', { name: /^all/i })
    await expect(allTab).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByTestId('tab-count-all')).toHaveText('5')
    await expect(page.getByTestId('refund-row')).toHaveCount(5)

    // 1. Switch to "Pending" tab
    const pendingTab = page.getByRole('tab', { name: /^pending/i })
    await pendingTab.click()
    await expect(pendingTab).toHaveAttribute('aria-selected', 'true')
    await expect(allTab).toHaveAttribute('aria-selected', 'false')
    await expect(page.getByTestId('tab-count-pending')).toHaveText('1')
    await expect(page.getByTestId('refund-row')).toHaveCount(1)
    await expect(page.getByText('ORD-1004')).toBeVisible()

    // 2. Switch to "Completed" tab
    const completedTab = page.getByRole('tab', { name: /^completed/i })
    await completedTab.click()
    await expect(completedTab).toHaveAttribute('aria-selected', 'true')
    await expect(pendingTab).toHaveAttribute('aria-selected', 'false')
    await expect(page.getByTestId('tab-count-completed')).toHaveText('2')
    await expect(page.getByTestId('refund-row')).toHaveCount(2)
    await expect(page.getByText('ORD-1001')).toBeVisible()
    await expect(page.getByText('ORD-1005')).toBeVisible()

    // 3. Switch to "Escalated" tab
    const escalatedTab = page.getByRole('tab', { name: /^escalated/i })
    await escalatedTab.click()
    await expect(escalatedTab).toHaveAttribute('aria-selected', 'true')
    await expect(completedTab).toHaveAttribute('aria-selected', 'false')
    await expect(page.getByTestId('tab-count-escalated')).toHaveText('1')
    await expect(page.getByTestId('refund-row')).toHaveCount(1)
    await expect(page.getByText('ORD-1002')).toBeVisible()

    // 4. Switch to "Awaiting Clarification" tab
    const clarifyTab = page.getByRole('tab', { name: /^awaiting clarification/i })
    await clarifyTab.click()
    await expect(clarifyTab).toHaveAttribute('aria-selected', 'true')
    await expect(escalatedTab).toHaveAttribute('aria-selected', 'false')
    await expect(page.getByTestId('tab-count-awaiting_clarification')).toHaveText('1')
    await expect(page.getByTestId('refund-row')).toHaveCount(1)
    await expect(page.getByText('ORD-1003')).toBeVisible()

    // 5. Switch back to "All" tab
    await allTab.click()
    await expect(allTab).toHaveAttribute('aria-selected', 'true')
    await expect(clarifyTab).toHaveAttribute('aria-selected', 'false')
    await expect(page.getByTestId('refund-row')).toHaveCount(5)
  })

  test('displays empty state notice when active tab contains no matching records', async ({
    page,
  }) => {
    // Seed with no pending refunds
    const refundsWithoutPending = DEFAULT_MOCK_REFUNDS.filter((r) => r.status !== 'pending')
    await setupMockApi(page, refundsWithoutPending)

    await page.goto('/')

    const pendingTab = page.getByRole('tab', { name: /^pending/i })
    await pendingTab.click()

    await expect(pendingTab).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByTestId('empty-state')).toBeVisible()
    await expect(page.getByText('No refund requests found in this view')).toBeVisible()
    await expect(page.getByTestId('refund-row')).toHaveCount(0)
  })
})
