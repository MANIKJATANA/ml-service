// Tailwind CSS v4 is wired through its dedicated PostCSS plugin (see globals.css
// `@import "tailwindcss"`). No tailwind.config.js — tokens live in `@theme`.
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
