import * as React from 'react'
import { Header, type HeaderProps } from './Header'
import { cn } from '@/lib/utils'

export interface AppLayoutProps {
  children: React.ReactNode
  headerProps?: HeaderProps
  className?: string
  contentClassName?: string
}

export function AppLayout({
  children,
  headerProps,
  className,
  contentClassName,
}: AppLayoutProps) {
  return (
    <div
      className={cn(
        'min-h-screen bg-slate-50 text-slate-900 flex flex-col font-sans antialiased selection:bg-slate-200',
        className
      )}
    >
      {/* Top Header */}
      <Header {...headerProps} />

      {/* Main Content Area */}
      <main
        className={cn(
          'flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6',
          contentClassName
        )}
      >
        {children}
      </main>

      {/* Back-office Footer */}
      <footer className="border-t border-slate-200 bg-white py-4 mt-auto">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between text-xs text-slate-500 gap-2">
          <div>
            <span>AI Refund Request Processor</span>
            <span className="mx-2">•</span>
            <span>Autonomous Multi-Agent Decision Engine</span>
          </div>
          <div className="flex items-center space-x-4">
            <span>WCAG AA Compliant</span>
            <span>RFC 9457 APIs</span>
            <span>v0.1.0</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
