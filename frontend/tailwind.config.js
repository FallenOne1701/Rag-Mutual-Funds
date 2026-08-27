/** Tokens mirror the "Fiscal Clarity" design system (Google Stitch export). */
/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "var(--c-background)",
        surface: "var(--c-surface)",
        "surface-container": "var(--c-surface-container)",
        "surface-container-high": "var(--c-surface-container-high)",
        "on-surface": "var(--c-on-surface)",
        "on-surface-variant": "var(--c-on-surface-variant)",
        outline: "var(--c-outline)",
        "outline-variant": "var(--c-outline-variant)",
        primary: "var(--c-primary)",
        "on-primary": "var(--c-on-primary)",
        "primary-container": "var(--c-primary-container)",
        "on-primary-container": "var(--c-on-primary-container)",
        "primary-accent": "var(--c-primary-accent)",
        secondary: "var(--c-secondary)",
        "on-secondary": "var(--c-on-secondary)",
        "secondary-container": "var(--c-secondary-container)",
        "on-secondary-container": "var(--c-on-secondary-container)",
        "warning-surface": "var(--c-warning-surface)",
        "warning-accent": "var(--c-warning-accent)",
        "warning-text": "var(--c-warning-text)",
        error: "var(--c-error)",
        "error-surface": "var(--c-error-surface)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      fontSize: {
        "label-sm": ["13px", { lineHeight: "18px", letterSpacing: "0.01em", fontWeight: "500" }],
        "body-md": ["15px", { lineHeight: "22px" }],
        "body-lg": ["16px", { lineHeight: "24px" }],
        "headline-md": ["20px", { lineHeight: "28px", fontWeight: "600" }],
        "headline-lg": ["32px", { lineHeight: "40px", letterSpacing: "-0.02em", fontWeight: "600" }],
      },
      borderRadius: {
        DEFAULT: "0.5rem",
        md: "0.75rem",
        lg: "1rem",
        xl: "1.5rem",
      },
      spacing: {
        "stack-sm": "8px",
        "stack-md": "16px",
        "stack-lg": "32px",
        gutter: "24px",
      },
      maxWidth: {
        container: "1200px",
        conversation: "780px",
      },
      boxShadow: {
        float: "0px 4px 20px rgba(0, 0, 0, 0.06)",
        composer: "0px 8px 30px rgba(0, 0, 0, 0.10)",
      },
      keyframes: {
        "fade-in-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        blink: {
          "0%, 80%, 100%": { opacity: "0.25" },
          "40%": { opacity: "1" },
        },
      },
      animation: {
        "fade-in-up": "fade-in-up 180ms ease-out both",
        blink: "blink 1.2s infinite ease-in-out",
      },
    },
  },
  plugins: [],
};
