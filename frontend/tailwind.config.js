/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,jsx,ts,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'sans-serif',
        ],
      },
      colors: {
        brand: {
          50:  '#eef4ff',
          100: '#d9e6ff',
          200: '#b8d1ff',
          300: '#8eb4ff',
          400: '#5e8eff',
          500: '#3b6bf2',
          600: '#2a52cc',
          700: '#223fa0',
          800: '#1c337a',
          900: '#16285c',
        },
      },
    },
  },
  plugins: [],
}
