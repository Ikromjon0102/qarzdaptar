// Landing sahifa (templates/landing.html) uchun Tailwind sozlamasi.
// O'zgartirgandan keyin: npm install && npm run build:css
module.exports = {
  content: ['./templates/landing.html'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: '#30e87a',
        'background-light': '#f6f8f7',
        'background-dark': '#0d1a12',
        'card-dark': '#1a3224',
        'border-green': '#244732',
      },
      fontFamily: {
        display: ['Spline Sans', 'sans-serif'],
        body: ['Noto Sans', 'sans-serif'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [require('@tailwindcss/forms'), require('@tailwindcss/container-queries')],
};
