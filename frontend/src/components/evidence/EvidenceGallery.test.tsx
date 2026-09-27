import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { EvidenceGallery, formatFileSize } from './EvidenceGallery'
import type { EvidenceItem } from '@/types/api'

const mockEvidenceList: EvidenceItem[] = [
  {
    evidenceId: 'evi-1',
    filename: 'shattered_vase.jpg',
    contentType: 'image/jpeg',
    sizeBytes: 460800, // 450 KB
    url: 'https://storage.example.com/refunds/shattered_vase.jpg',
    createdAt: '2026-09-28T10:00:00Z',
  } as unknown as EvidenceItem,
  {
    evidenceId: 'evi-2',
    filename: 'box_barcode_label.png',
    contentType: 'image/png',
    sizeBytes: 2516582, // 2.4 MB
    url: 'https://storage.example.com/refunds/box_barcode_label.png',
    createdAt: '2026-09-28T10:05:00Z',
  } as unknown as EvidenceItem,
]

describe('formatFileSize helper', () => {
  it('formats various byte sizes accurately', () => {
    expect(formatFileSize(0)).toBe('0 B')
    expect(formatFileSize(null)).toBe('0 B')
    expect(formatFileSize(undefined)).toBe('0 B')
    expect(formatFileSize(512)).toBe('512 B')
    expect(formatFileSize(460800)).toBe('450.0 KB')
    expect(formatFileSize(2516582)).toBe('2.4 MB')
  })
})

describe('EvidenceGallery component', () => {
  it('renders empty state when evidence is empty list or null', () => {
    const { rerender } = render(<EvidenceGallery evidence={[]} />)

    expect(screen.getByTestId('evidence-empty-state')).toBeInTheDocument()
    expect(screen.getByText('No evidence attachments')).toBeInTheDocument()
    expect(
      screen.getByText(/no customer-uploaded photos or documents attached/i)
    ).toBeInTheDocument()

    rerender(<EvidenceGallery evidence={null} />)
    expect(screen.getByTestId('evidence-empty-state')).toBeInTheDocument()

    rerender(
      <EvidenceGallery
        evidence={[]}
        emptyMessage="Custom empty message for test"
      />
    )
    expect(screen.getByText('Custom empty message for test')).toBeInTheDocument()
  })

  it('renders loading skeleton when isLoading is true', () => {
    render(<EvidenceGallery isLoading={true} />)

    expect(screen.getByTestId('evidence-loading-skeleton')).toBeInTheDocument()
    const skeletonCards = screen.getAllByTestId('evidence-skeleton-card')
    expect(skeletonCards.length).toBe(3)
  })

  it('renders thumbnail cards, filenames, formatted file sizes, and MIME badges', () => {
    render(<EvidenceGallery evidence={mockEvidenceList} />)

    const cards = screen.getAllByTestId('evidence-card')
    expect(cards.length).toBe(2)

    // Filenames
    expect(screen.getByText('shattered_vase.jpg')).toBeInTheDocument()
    expect(screen.getByText('box_barcode_label.png')).toBeInTheDocument()

    // Formatted sizes
    expect(screen.getByText('450.0 KB')).toBeInTheDocument()
    expect(screen.getByText('2.4 MB')).toBeInTheDocument()

    // MIME type badges
    expect(screen.getByText('image/jpeg')).toBeInTheDocument()
    expect(screen.getByText('image/png')).toBeInTheDocument()

    // Images with proper alt
    const img1 = screen.getByAltText('shattered_vase.jpg')
    expect(img1).toHaveAttribute('src', 'https://storage.example.com/refunds/shattered_vase.jpg')
  })

  it('handles broken image onError and renders fallback placeholder without failing', () => {
    render(<EvidenceGallery evidence={mockEvidenceList} />)

    const img = screen.getByAltText('shattered_vase.jpg')
    expect(screen.queryByTestId('image-fallback')).not.toBeInTheDocument()

    // Trigger image error
    fireEvent.error(img)

    expect(screen.getByTestId('image-fallback')).toBeInTheDocument()
    expect(screen.getByText('Preview unavailable')).toBeInTheDocument()
  })

  it('opens zoom modal with enlarged image and external link upon thumbnail click', () => {
    render(<EvidenceGallery evidence={mockEvidenceList} />)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    const cards = screen.getAllByTestId('evidence-card')
    fireEvent.click(cards[0])

    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeInTheDocument()

    // Check modal image
    const modalImg = screen.getByTestId('zoom-modal-image')
    expect(modalImg).toBeInTheDocument()
    expect(modalImg).toHaveAttribute(
      'src',
      'https://storage.example.com/refunds/shattered_vase.jpg'
    )

    // Check external link
    const link = screen.getByTestId('open-original-link')
    expect(link).toHaveAttribute(
      'href',
      'https://storage.example.com/refunds/shattered_vase.jpg'
    )
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('dismisses zoom modal on Escape key press or close button click', () => {
    render(<EvidenceGallery evidence={mockEvidenceList} />)

    const cards = screen.getAllByTestId('evidence-card')
    fireEvent.click(cards[1])

    expect(screen.getByRole('dialog')).toBeInTheDocument()

    // Press Escape
    fireEvent.keyDown(document, { key: 'Escape', code: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    // Open again
    fireEvent.click(cards[1])
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    // Click Close button
    const closeBtns = screen.getAllByRole('button', { name: /close/i })
    fireEvent.click(closeBtns[0])
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('supports keyboard navigation (Enter/Space) to open thumbnail modal', () => {
    render(<EvidenceGallery evidence={mockEvidenceList} />)

    const cards = screen.getAllByTestId('evidence-card')
    fireEvent.keyDown(cards[0], { key: 'Enter', code: 'Enter' })

    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
