/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        decision: {
          auto_approve: {
            bg: '#ecfdf5',
            text: '#047857',
            border: '#a7f3d0',
          },
          deny: {
            bg: '#fff1f2',
            text: '#be123c',
            border: '#fecdd3',
          },
          escalate: {
            bg: '#fffbeb',
            text: '#92400e',
            border: '#fde68a',
          },
          pending: {
            bg: '#f0f9ff',
            text: '#0369a1',
            border: '#bae6fd',
          },
          manual_approved: {
            bg: '#f0fdfa',
            text: '#0f766e',
            border: '#99f6e4',
          },
          manual_denied: {
            bg: '#fef2f2',
            text: '#b91c1c',
            border: '#fecaca',
          },
        },
      },
    },
  },
  plugins: [],
}
