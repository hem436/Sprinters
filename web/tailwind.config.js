/** @type {import('tailwindcss').Config} */
// Colors follow the wireframe (Knowledge Assistant Wireframes): neutral grays with ink #1f2328
// and one blue accent #2557d6. slate and indigo are remapped, so every screen picks them up.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      colors: {
        slate: {
          50: '#f8f9fa',
          100: '#f4f5f7',
          200: '#e3e5e8',
          300: '#c9ccd1',
          400: '#8a9099',
          500: '#5b616b',
          600: '#4a5058',
          700: '#3c4148',
          800: '#2b2f35',
          900: '#1f2328',
          950: '#121417',
        },
        indigo: {
          50: '#eef3fd',
          100: '#dfe7fb',
          200: '#c3d3f6',
          300: '#9db4ee',
          400: '#6f8fe4',
          500: '#4672dc',
          600: '#2557d6',
          700: '#1d47b3',
          800: '#163f9e',
          900: '#132f73',
          950: '#0d1e4a',
        },
      },
    },
  },
  plugins: [],
}
