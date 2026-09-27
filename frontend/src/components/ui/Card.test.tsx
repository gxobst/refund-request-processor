import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from './Card'

describe('Card component', () => {
  it('renders card with all compound elements', () => {
    render(
      <Card>
        <CardHeader>
          <CardTitle>Decision Overview</CardTitle>
          <CardDescription>Automated LangGraph evaluation summary</CardDescription>
        </CardHeader>
        <CardContent>
          <p>Confidence: 94%</p>
        </CardContent>
        <CardFooter>
          <span>Footer Actions</span>
        </CardFooter>
      </Card>
    )

    expect(screen.getByText('Decision Overview')).toBeInTheDocument()
    expect(screen.getByText('Automated LangGraph evaluation summary')).toBeInTheDocument()
    expect(screen.getByText('Confidence: 94%')).toBeInTheDocument()
    expect(screen.getByText('Footer Actions')).toBeInTheDocument()
  })
})
