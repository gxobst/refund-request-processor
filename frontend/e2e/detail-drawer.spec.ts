import { test, expect } from '@playwright/test'
import { setupMockApi } from './support/mockApi'

test.describe('Refund Detail Drawer and Manual Override', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockApi(page)
  })

  test('opens detail drawer, inspects AI analysis sections, executes supervisor override, and closes drawer', async ({
    page,
  }) => {
    await page.goto('/')

    // 1. Click Review / Inspect button on ORD-1002 row
    const inspectButton = page.getByRole('button', { name: /Review order ORD-1002/i })
    await inspectButton.click()

    // 2. Verify drawer sections are rendered
    const customerIntakeSection = page.getByTestId('section-customer-intake')
    await expect(customerIntakeSection).toBeVisible()

    const classificationSection = page.getByTestId('section-classification')
    await expect(classificationSection).toBeVisible()

    const reasoningSection = page.getByTestId('section-decision-reasoning')
    await expect(reasoningSection).toBeVisible()

    // 3. Click "Manual Override" button to open ManualOverrideModal
    const manualOverrideBtn = page.getByRole('button', { name: /Manual Override/i })
    await expect(manualOverrideBtn).toBeVisible()
    await manualOverrideBtn.click()

    const overrideModalTitle = page.getByRole('heading', { name: 'Manual Decision Override' })
    await expect(overrideModalTitle).toBeVisible()

    // 4. Select override decision, enter justification, check confirmation guard
    const approveChoice = page.getByTestId('decision-choice-approve')
    await approveChoice.click()

    const justificationTextarea = page.getByTestId('override-justification-textarea')
    await justificationTextarea.fill('Customer contacted VIP support line; verified exchange authorization.')

    const confirmCheckbox = page.getByTestId('confirm-override-checkbox')
    await confirmCheckbox.check()

    // 5. Submit override
    const submitOverrideBtn = page.getByTestId('override-submit-button')
    await submitOverrideBtn.click()

    // Override modal closes
    await expect(overrideModalTitle).not.toBeVisible()

    // 6. Verify supervisor override banner is displayed inside the drawer
    const overrideBanner = page.getByTestId('supervisor-override-banner')
    await expect(overrideBanner).toBeVisible()
    await expect(overrideBanner).toContainText('Supervisor Decision Override')
    await expect(overrideBanner).toContainText('Customer contacted VIP support line')

    // 7. Click drawer close button and verify drawer is closed
    const drawerCloseButton = page.getByTestId('drawer-close-button')
    await drawerCloseButton.click()

    await expect(customerIntakeSection).not.toBeVisible()
  })
})
