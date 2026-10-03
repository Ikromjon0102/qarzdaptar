// Landing sahifa (templates/landing.html, templates/landing/, templates/privacy.html) uchun Tailwind sozlamasi.
// O'zgartirgandan keyin: npm install && npm run build:css
module.exports = {
  content: ['./templates/landing.html', './templates/landing/*.html', './templates/privacy.html'],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: '#30e87a', hover: '#5cf09a' },
        ink: { DEFAULT: '#0b1710', 2: '#0e1d14' },
        card: '#13261b',
        line: '#22402e',
        fg: '#ecf6f0',
        muted: '#a9c4b3',  // asosiy fonda kontrast ~9:1
        dim: '#86a493',    // ~6:1
      },
      fontFamily: {
        sans: ['Manrope', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
