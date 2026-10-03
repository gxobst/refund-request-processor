import * as React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CustomerClarificationModal } from '@/components/modals/CustomerClarificationModal'
import { CreateRefundModal } from '@/components/modals/CreateRefundModal'
import * as refundService from '@/services/refundService'
import type { RefundRecord, RefundCreateResponse } from '@/types/api'

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  })
}

function renderWithClient(ui: React.ReactElement, client = createTestQueryClient()) {
  return {
    ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>),
    client,
  }
}

describe('Client-side Image Compression and Dimension Pre-validation Integration Tests', () => {
  const originalCreateObjectURL = window.URL.createObjectURL
  const originalRevokeObjectURL = window.URL.revokeObjectURL
  const originalImage = window.Image
  const originalGetContext = HTMLCanvasElement.prototype.getContext
  const originalToBlob = HTMLCanvasElement.prototype.toBlob

  let mockWidth = 800
  let mockHeight = 600
  let mockShouldFail = false

  class MockImage {
    naturalWidth = 0
    naturalHeight = 0
    width = 0
    height = 0
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    private _src = ''

    set src(value: string) {
      this._src = value
      queueMicrotask(() => {
        if (mockShouldFail) {
          this.onerror?.()
        } else {
          this.naturalWidth = mockWidth
          this.naturalHeight = mockHeight
          this.width = mockWidth
          this.height = mockHeight
          this.onload?.()
        }
      })
    }

    get src() {
      return this._src
    }
  }

  beforeEach(() => {
    mockWidth = 800
    mockHeight = 600
    mockShouldFail = false

    window.URL.createObjectURL = vi
      .fn()
      .mockReturnValue('blob:http://localhost/mock-blob-uuid') as unknown as typeof window.URL.createObjectURL
    window.URL.revokeObjectURL = vi.fn() as unknown as typeof window.URL.revokeObjectURL
    // @ts-expect-error Mocking Image
    window.Image = MockImage

    HTMLCanvasElement.prototype.getContext = vi.fn().mockImplementation(function () {
      return {
        drawImage: vi.fn(),
      }
    })

    HTMLCanvasElement.prototype.toBlob = vi.fn().mockImplementation(function (
      cb: (blob: Blob | null) => void
    ) {
      const compressedBlob = new Blob(['compressed-image-data'], { type: 'image/jpeg' })
      cb(compressedBlob)
    })
  })

  afterEach(() => {
    window.URL.createObjectURL = originalCreateObjectURL
    window.URL.revokeObjectURL = originalRevokeObjectURL
    window.Image = originalImage
    HTMLCanvasElement.prototype.getContext = originalGetContext
    HTMLCanvasElement.prototype.toBlob = originalToBlob
    vi.restoreAllMocks()
  })

  describe('CustomerClarificationModal Dimension Validation & Compression', () => {
    it('displays evidence-dimension-error banner and blocks submission when image resolution is below 50x50', async () => {
      mockWidth = 40
      mockHeight = 40

      const submitClarificationSpy = vi.spyOn(refundService, 'submitClarification')
      const onSuccess = vi.fn()
      renderWithClient(
        <CustomerClarificationModal
          refundId="ref-101"
          isOpen={true}
          onClose={vi.fn()}
          onSuccess={onSuccess}
        />
      )

      // Enter response text
      const textarea = screen.getByTestId('clarification-response-textarea')
      fireEvent.change(textarea, { target: { value: 'Here is the requested explanation.' } })

      // Upload undersized image
      const fileInput = screen.getByTestId('clarification-file-input')
      const undersizedFile = new File(['undersized-data'], 'too_small.png', { type: 'image/png' })
      fireEvent.change(fileInput, { target: { files: [undersizedFile] } })

      // Error banner should be displayed
      const errorBanner = await screen.findByTestId('evidence-dimension-error')
      expect(errorBanner).toBeInTheDocument()
      expect(errorBanner).toHaveTextContent(
        'Image dimensions (40x40) are below minimum required resolution of 50x50 pixels.'
      )

      // Compression badge should NOT be displayed and file preview should NOT exist
      expect(screen.queryByTestId('evidence-compressed-badge')).not.toBeInTheDocument()
      expect(screen.queryByTestId('clarification-file-preview')).not.toBeInTheDocument()

      // Attempt submission
      const submitBtn = screen.getByTestId('clarification-submit-button')
      fireEvent.click(submitBtn)

      // Submission should be blocked
      expect(submitClarificationSpy).not.toHaveBeenCalled()
      expect(onSuccess).not.toHaveBeenCalled()
      expect(screen.queryByTestId('clarification-success-state')).not.toBeInTheDocument()
    })

    it('displays evidence-dimension-error banner and blocks submission when image resolution exceeds 8192x8192', async () => {
      mockWidth = 9000
      mockHeight = 9000

      const submitClarificationSpy = vi.spyOn(refundService, 'submitClarification')
      const onSuccess = vi.fn()
      renderWithClient(
        <CustomerClarificationModal
          refundId="ref-101"
          isOpen={true}
          onClose={vi.fn()}
          onSuccess={onSuccess}
        />
      )

      const textarea = screen.getByTestId('clarification-response-textarea')
      fireEvent.change(textarea, { target: { value: 'Here is the requested explanation.' } })

      const fileInput = screen.getByTestId('clarification-file-input')
      const oversizedFile = new File(['huge-data'], 'too_big.jpg', { type: 'image/jpeg' })
      fireEvent.change(fileInput, { target: { files: [oversizedFile] } })

      const errorBanner = await screen.findByTestId('evidence-dimension-error')
      expect(errorBanner).toBeInTheDocument()
      expect(errorBanner).toHaveTextContent(
        'Image dimensions (9000x9000) exceed maximum allowed resolution of 8192x8192 pixels.'
      )

      expect(screen.queryByTestId('evidence-compressed-badge')).not.toBeInTheDocument()

      const submitBtn = screen.getByTestId('clarification-submit-button')
      fireEvent.click(submitBtn)

      expect(submitClarificationSpy).not.toHaveBeenCalled()
      expect(onSuccess).not.toHaveBeenCalled()
      expect(screen.queryByTestId('clarification-success-state')).not.toBeInTheDocument()
    })

    it('renders evidence-compressed-badge on valid image upload and submits successfully', async () => {
      mockWidth = 800
      mockHeight = 600

      const mockUpdatedRefund: RefundRecord = {
        refundId: 'ref-101',
        orderId: 'ORD-1001',
        status: 'pending',
        customerRequestText: 'Packaging arrived crumpled with dented box.',
        createdAt: '2026-09-28T10:00:00Z',
        updatedAt: '2026-09-28T10:05:00Z',
      } as unknown as RefundRecord

      const submitClarificationSpy = vi
        .spyOn(refundService, 'submitClarification')
        .mockResolvedValue(mockUpdatedRefund)

      const onSuccess = vi.fn()
      renderWithClient(
        <CustomerClarificationModal
          refundId="ref-101"
          isOpen={true}
          onClose={vi.fn()}
          onSuccess={onSuccess}
        />
      )

      const textarea = screen.getByTestId('clarification-response-textarea')
      fireEvent.change(textarea, { target: { value: 'Packaging arrived crumpled with dented box.' } })

      const fileInput = screen.getByTestId('clarification-file-input')
      const validFile = new File(['valid-image-content-longer-string'], 'valid_evidence.png', {
        type: 'image/png',
      })
      fireEvent.change(fileInput, { target: { files: [validFile] } })

      // Wait for compressed badge to appear
      const badge = await screen.findByTestId('evidence-compressed-badge')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveTextContent('800x600')

      // No dimension error banner
      expect(screen.queryByTestId('evidence-dimension-error')).not.toBeInTheDocument()

      // Submit clarification
      const submitBtn = screen.getByTestId('clarification-submit-button')
      fireEvent.click(submitBtn)

      await waitFor(() => {
        expect(submitClarificationSpy).toHaveBeenCalledWith(
          'ref-101',
          expect.objectContaining({
            responseText: 'Packaging arrived crumpled with dented box.',
            evidenceFile: expect.any(File),
          })
        )
        expect(screen.getByTestId('clarification-success-state')).toBeInTheDocument()
      })
      expect(onSuccess).toHaveBeenCalledWith(mockUpdatedRefund)
    })

    it('clears attached file, dimension error, and compression badge when remove button is clicked', async () => {
      mockWidth = 1000
      mockHeight = 800

      renderWithClient(
        <CustomerClarificationModal
          refundId="ref-101"
          isOpen={true}
          onClose={vi.fn()}
        />
      )

      const fileInput = screen.getByTestId('clarification-file-input')
      const validFile = new File(['evidence-bytes-long-string-sample'], 'photo.jpg', {
        type: 'image/jpeg',
      })
      fireEvent.change(fileInput, { target: { files: [validFile] } })

      await screen.findByTestId('evidence-compressed-badge')
      expect(screen.getByTestId('clarification-file-preview')).toBeInTheDocument()

      // Click remove file button
      const removeBtn = screen.getByTestId('remove-file-button')
      fireEvent.click(removeBtn)

      expect(screen.queryByTestId('clarification-file-preview')).not.toBeInTheDocument()
      expect(screen.queryByTestId('evidence-compressed-badge')).not.toBeInTheDocument()
      expect(screen.queryByTestId('evidence-dimension-error')).not.toBeInTheDocument()
      expect(screen.getByTestId('clarification-drop-zone')).toBeInTheDocument()
    })
  })

  describe('CreateRefundModal Dimension Validation & Compression', () => {
    it('displays evidence-dimension-error banner and blocks submission when image resolution is below 50x50', async () => {
      mockWidth = 30
      mockHeight = 40

      const submitRefundSpy = vi.spyOn(refundService, 'submitRefund')
      const onSuccess = vi.fn()
      renderWithClient(
        <CreateRefundModal
          isOpen={true}
          onClose={vi.fn()}
          onSuccess={onSuccess}
        />
      )

      // Fill in valid order ID and description
      const orderIdInput = screen.getByTestId('create-order-id-input')
      fireEvent.change(orderIdInput, { target: { value: 'ORD-7777' } })

      const textarea = screen.getByTestId('customer-request-textarea')
      fireEvent.change(textarea, { target: { value: 'Item arrived smashed and broken.' } })

      // Attach undersized image
      const fileInput = screen.getByTestId('file-picker-input')
      const undersizedFile = new File(['undersized-data'], 'too_small.png', { type: 'image/png' })
      fireEvent.change(fileInput, { target: { files: [undersizedFile] } })

      const errorBanner = await screen.findByTestId('evidence-dimension-error')
      expect(errorBanner).toBeInTheDocument()
      expect(errorBanner).toHaveTextContent(
        'Image dimensions (30x40) are below minimum required resolution of 50x50 pixels.'
      )

      expect(screen.queryByTestId('evidence-compressed-badge')).not.toBeInTheDocument()
      expect(screen.queryByTestId('selected-file-badge')).not.toBeInTheDocument()

      // Submit
      const submitBtn = screen.getByTestId('create-refund-submit-button')
      fireEvent.click(submitBtn)

      expect(submitRefundSpy).not.toHaveBeenCalled()
      expect(onSuccess).not.toHaveBeenCalled()
    })

    it('displays evidence-dimension-error banner and blocks submission when image resolution exceeds 8192x8192', async () => {
      mockWidth = 9000
      mockHeight = 6000

      const submitRefundSpy = vi.spyOn(refundService, 'submitRefund')
      const onSuccess = vi.fn()
      renderWithClient(
        <CreateRefundModal
          isOpen={true}
          onClose={vi.fn()}
          onSuccess={onSuccess}
        />
      )

      const orderIdInput = screen.getByTestId('create-order-id-input')
      fireEvent.change(orderIdInput, { target: { value: 'ORD-8888' } })

      const textarea = screen.getByTestId('customer-request-textarea')
      fireEvent.change(textarea, { target: { value: 'Missing contents inside parcel.' } })

      const fileInput = screen.getByTestId('file-picker-input')
      const oversizedFile = new File(['huge-data'], 'too_big.jpg', { type: 'image/jpeg' })
      fireEvent.change(fileInput, { target: { files: [oversizedFile] } })

      const errorBanner = await screen.findByTestId('evidence-dimension-error')
      expect(errorBanner).toBeInTheDocument()
      expect(errorBanner).toHaveTextContent(
        'Image dimensions (9000x6000) exceed maximum allowed resolution of 8192x8192 pixels.'
      )

      expect(screen.queryByTestId('evidence-compressed-badge')).not.toBeInTheDocument()

      const submitBtn = screen.getByTestId('create-refund-submit-button')
      fireEvent.click(submitBtn)

      expect(submitRefundSpy).not.toHaveBeenCalled()
      expect(onSuccess).not.toHaveBeenCalled()
    })

    it('renders evidence-compressed-badge on valid image upload and submits successfully', async () => {
      mockWidth = 800
      mockHeight = 600

      const mockCreateResponse: RefundCreateResponse = {
        refundId: 'ref-created-123',
        status: 'pending',
      } as unknown as RefundCreateResponse

      const submitRefundSpy = vi
        .spyOn(refundService, 'submitRefund')
        .mockResolvedValue(mockCreateResponse)

      const onSuccess = vi.fn()
      const onClose = vi.fn()
      renderWithClient(
        <CreateRefundModal
          isOpen={true}
          onClose={onClose}
          onSuccess={onSuccess}
        />
      )

      const orderIdInput = screen.getByTestId('create-order-id-input')
      fireEvent.change(orderIdInput, { target: { value: 'ORD-5555' } })

      const textarea = screen.getByTestId('customer-request-textarea')
      fireEvent.change(textarea, { target: { value: 'Device casing cracked upon arrival.' } })

      const fileInput = screen.getByTestId('file-picker-input')
      const validFile = new File(['valid-image-bytes-length-greater'], 'valid_evidence.png', {
        type: 'image/png',
      })
      fireEvent.change(fileInput, { target: { files: [validFile] } })

      const badge = await screen.findByTestId('evidence-compressed-badge')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveTextContent('800x600')

      expect(screen.queryByTestId('evidence-dimension-error')).not.toBeInTheDocument()

      const submitBtn = screen.getByTestId('create-refund-submit-button')
      fireEvent.click(submitBtn)

      await waitFor(() => {
        expect(submitRefundSpy).toHaveBeenCalledWith(
          expect.objectContaining({
            orderId: 'ORD-5555',
            customerRequestText: 'Device casing cracked upon arrival.',
            file: expect.any(File),
          })
        )
        expect(onSuccess).toHaveBeenCalledWith(mockCreateResponse)
      })
      expect(onClose).toHaveBeenCalled()
    })

    it('clears attached file, dimension error, and compression badge when remove button is clicked', async () => {
      mockWidth = 1200
      mockHeight = 900

      renderWithClient(
        <CreateRefundModal
          isOpen={true}
          onClose={vi.fn()}
        />
      )

      const fileInput = screen.getByTestId('file-picker-input')
      const validFile = new File(['valid-image-bytes-longer-string'], 'package.jpg', {
        type: 'image/jpeg',
      })
      fireEvent.change(fileInput, { target: { files: [validFile] } })

      await screen.findByTestId('evidence-compressed-badge')
      expect(screen.getByTestId('selected-file-badge')).toBeInTheDocument()

      const removeBtn = screen.getByTestId('remove-file-button')
      fireEvent.click(removeBtn)

      expect(screen.queryByTestId('selected-file-badge')).not.toBeInTheDocument()
      expect(screen.queryByTestId('evidence-compressed-badge')).not.toBeInTheDocument()
      expect(screen.queryByTestId('evidence-dimension-error')).not.toBeInTheDocument()
      expect(screen.getByTestId('file-dropzone')).toBeInTheDocument()
    })
  })
})
