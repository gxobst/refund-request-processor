import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import App from './App'

describe('App', () => {
  it('mounts and renders the application title', () => {
    render(<App />)
    const titleElement = screen.getByRole('heading', {
      level: 1,
      name: /AI Refund Request Processor/i,
    })
    expect(titleElement).toBeInTheDocument()
  })

  it('renders the operations section header', () => {
    render(<App />)
    expect(screen.getByText(/Back-Office Operations/i)).toBeInTheDocument()
  })
})
