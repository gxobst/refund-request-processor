export function App() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between">
          <h1 className="text-xl font-semibold text-slate-900 tracking-tight">
            AI Refund Request Processor
          </h1>
          <span className="text-xs font-medium px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
            System Online
          </span>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-base font-medium text-slate-900 mb-2">Back-Office Operations</h2>
          <p className="text-sm text-slate-500">
            Automated refund request processing powered by multi-agent LangGraph workflow.
          </p>
        </div>
      </main>
    </div>
  )
}

export default App
