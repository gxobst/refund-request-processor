import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { EvidenceGallery } from '@/components/evidence/EvidenceGallery'
import type { EvidenceItem } from '@/types/api'

describe('Evidence Malware Inspection Integration Tests', () => {
  const cleanItem: EvidenceItem = {
    evidenceId: 'evi-clean-1',
    filename: 'clean_receipt.png',
    contentType: 'image/png',
    sizeBytes: 102400,
    url: 'https://storage.example.com/clean_receipt.png',
    scanStatus: 'clean',
    scannedAt: '2026-10-04T12:00:00Z',
  }

  const pendingItem: EvidenceItem = {
    evidenceId: 'evi-pending-2',
    filename: 'uploading_photo.jpg',
    contentType: 'image/jpeg',
    sizeBytes: 204800,
    url: 'https://storage.example.com/uploading_photo.jpg',
    scanStatus: 'pending',
  }

  const infectedItem: EvidenceItem = {
    evidenceId: 'evi-infected-3',
    filename: 'trojan_attachment.png',
    contentType: 'image/png',
    sizeBytes: 51200,
    url: 'https://storage.example.com/trojan_attachment.png',
    scanStatus: 'infected',
    threatName: 'Win32.Eicar.TestFile',
    scannedAt: '2026-10-04T12:05:00Z',
  }

  it('renders green scan status badge for clean evidence attachment', () => {
    render(<EvidenceGallery evidence={[cleanItem]} />)

    const cleanBadge = screen.getByTestId('evidence-scan-badge-clean')
    expect(cleanBadge).toBeInTheDocument()
    expect(cleanBadge).toHaveTextContent(/clean/i)
    expect(screen.queryByTestId('infected-evidence-warning')).not.toBeInTheDocument()
    expect(screen.queryByTestId('evidence-infected-blocked')).not.toBeInTheDocument()
  })

  it('renders yellow scan status badge with scanning indicator for pending evidence attachment', () => {
    render(<EvidenceGallery evidence={[pendingItem]} />)

    const pendingBadge = screen.getByTestId('evidence-scan-badge-pending')
    expect(pendingBadge).toBeInTheDocument()
    expect(pendingBadge).toHaveTextContent(/scanning/i)
    expect(screen.queryByTestId('infected-evidence-warning')).not.toBeInTheDocument()
    expect(screen.queryByTestId('evidence-infected-blocked')).not.toBeInTheDocument()
  })

  it('renders red scan status badge with detected threat name for infected evidence attachment', () => {
    render(<EvidenceGallery evidence={[infectedItem]} />)

    const infectedBadge = screen.getByTestId('evidence-scan-badge-infected')
    expect(infectedBadge).toBeInTheDocument()
    expect(infectedBadge).toHaveTextContent('Win32.Eicar.TestFile')
  })

  it('renders quarantine warning banner and blocks preview for infected evidence', () => {
    render(<EvidenceGallery evidence={[infectedItem]} />)

    // Red warning banner
    const warningBanner = screen.getByTestId('infected-evidence-warning')
    expect(warningBanner).toBeInTheDocument()
    expect(warningBanner).toHaveTextContent(/quarantined/i)

    // Thumbnail blocked preview element
    const blockedElement = screen.getByTestId('evidence-infected-blocked')
    expect(blockedElement).toBeInTheDocument()
    expect(blockedElement).toHaveTextContent(/preview blocked/i)

    // Clicking the card does NOT open the zoom modal
    const card = screen.getByTestId('evidence-card')
    fireEvent.click(card)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    // Pressing Enter does NOT open the zoom modal
    fireEvent.keyDown(card, { key: 'Enter', code: 'Enter' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('allows preview zoom modal for clean evidence while blocking infected in a mixed gallery', () => {
    render(<EvidenceGallery evidence={[cleanItem, infectedItem]} />)

    const cards = screen.getAllByTestId('evidence-card')
    expect(cards).toHaveLength(2)

    // Click clean item opens modal
    fireEvent.click(cards[0])
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByTestId('zoom-modal-image')).toHaveAttribute(
      'src',
      'https://storage.example.com/clean_receipt.png'
    )

    // Close modal
    const closeBtns = screen.getAllByRole('button', { name: /close/i })
    fireEvent.click(closeBtns[0])
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    // Click infected item does NOT open modal
    fireEvent.click(cards[1])
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('handles snake_case fields (scan_status, threat_name) from backend API gracefully', () => {
    const backendPayload = {
      evidence_id: 'evi-snake-1',
      filename: 'snake_evidence.jpg',
      content_type: 'image/jpeg',
      size_bytes: 30000,
      url: 'https://storage.example.com/snake.jpg',
      scan_status: 'infected',
      threat_name: 'Trojan.Generic.ExecutablePE',
    } as unknown as EvidenceItem

    render(<EvidenceGallery evidence={[backendPayload]} />)

    const badge = screen.getByTestId('evidence-scan-badge-infected')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveTextContent('Trojan.Generic.ExecutablePE')
    expect(screen.getByTestId('evidence-infected-blocked')).toBeInTheDocument()
    expect(screen.getByTestId('infected-evidence-warning')).toBeInTheDocument()
  })
})
