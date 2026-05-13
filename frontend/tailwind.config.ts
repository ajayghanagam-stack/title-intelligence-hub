import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        // Logikality brand guideline §2 — Primary typeface is Mona Sans
        // (OFL-licensed, chosen as the close visual analogue to Proxima
        // Nova). Registered via @fontsource-variable/mona-sans imported
        // in `layout.tsx`. Arial/Helvetica/sans-serif remain the
        // documented fallback chain if the self-hosted font fails to
        // load.
        sans: [
          "Mona Sans Variable",
          "Mona Sans",
          "Arial",
          "Helvetica",
          "sans-serif",
        ],
        mono: ["var(--font-geist-mono)", "monospace"],
      },
      colors: {
        border: "var(--border)",
        input: "var(--input)",
        ring: "var(--ring)",
        background: "var(--background)",
        foreground: "var(--foreground)",
        primary: {
          DEFAULT: "var(--primary)",
          foreground: "var(--primary-foreground)",
        },
        secondary: {
          DEFAULT: "var(--secondary)",
          foreground: "var(--secondary-foreground)",
        },
        destructive: {
          DEFAULT: "var(--destructive)",
          foreground: "var(--destructive-foreground)",
        },
        muted: {
          DEFAULT: "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          foreground: "var(--accent-foreground)",
        },
        card: {
          DEFAULT: "var(--card)",
          foreground: "var(--card-foreground)",
        },
        popover: {
          DEFAULT: "var(--popover)",
          foreground: "var(--popover-foreground)",
        },
        success: {
          DEFAULT: "var(--success)",
          foreground: "var(--success-foreground)",
        },
        warning: {
          DEFAULT: "var(--warning)",
          foreground: "var(--warning-foreground)",
        },
        sidebar: {
          DEFAULT: "var(--sidebar)",
          foreground: "var(--sidebar-foreground)",
          primary: "var(--sidebar-primary)",
          "primary-foreground": "var(--sidebar-primary-foreground)",
          accent: "var(--sidebar-accent)",
          "accent-foreground": "var(--sidebar-accent-foreground)",
          border: "var(--sidebar-border)",
          ring: "var(--sidebar-ring)",
          muted: "var(--sidebar-muted)",
          "muted-foreground": "var(--sidebar-muted-foreground)",
        },
        // Phase 5.1 — locked Logikality brand palette (Refactoring §1.1).
        // These are the *only* acceptable color values in app code; an
        // ESLint rule blocks raw hex literals in JSX so the hand-roll
        // can't slip back in. Old aliases (amber/magenta) preserved as
        // a thin compat shim so existing components stay live during
        // the codemod sweep.
        brand: {
          teal: "#01BAED",      // Primary brand · CTAs · active states
          purple: "#BD33A4",    // Accents · highlights · active rail step
          orange: "#FCAE1E",    // Emphasis · soft flags · review band
          charcoal: "#1A1A2E",  // Dark backgrounds · headings on light
          gray: "#53585F",      // Body text · muted labels
          white: "#FFFFFF",     // Card surfaces · contrast areas
          // Compat aliases — point at the new palette so legacy class
          // names (bg-brand-amber, text-brand-magenta) keep working
          // through the sweep without visual regression.
          amber: "#FCAE1E",
          magenta: "#BD33A4",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
