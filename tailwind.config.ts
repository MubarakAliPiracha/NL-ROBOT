import type { Config } from 'tailwindcss';

const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  darkMode: ['class'],
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        app: token('bg'),
        surface: token('surface'),
        surfaceAlt: token('surface-alt'),
        line: token('line'),
        fg: token('fg'),
        muted: token('muted'),
        brand: token('brand'),
        brandDeep: token('brand-deep'),
        accent: token('accent'),
        pop: token('pop'),
        warn: token('warn'),
        danger: token('danger'),
      },
      boxShadow: {
        card: '0 1px 2px rgb(var(--shadow) / 0.08), 0 6px 18px rgb(var(--shadow) / 0.08)',
        lift: '0 2px 4px rgb(var(--shadow) / 0.1), 0 14px 30px rgb(var(--shadow) / 0.16)',
      },
    },
  },
  plugins: [],
};

export default config;
