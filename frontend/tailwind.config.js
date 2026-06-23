/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      animation: {
        'fade-up': 'fadeUp 0.7s ease-out both',
        float: 'float 6s ease-in-out infinite',
        ticker: 'ticker 28s linear infinite',
        'bar-fill': 'barFill 1.4s ease-out both',
        glow: 'glow 4s ease-in-out infinite',
      },
      keyframes: {
        fadeUp: {
          '0%': { opacity: '0', transform: 'translateY(24px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-10px)' },
        },
        ticker: {
          '0%': { transform: 'translateX(0)' },
          '100%': { transform: 'translateX(-50%)' },
        },
        barFill: {
          '0%': { width: '0%' },
          '100%': { width: '72%' },
        },
        glow: {
          '0%, 100%': { boxShadow: '0 0 40px rgba(20,184,166,0.15)' },
          '50%': { boxShadow: '0 0 60px rgba(20,184,166,0.25)' },
        },
      },
    },
  },
  plugins: [],
}
