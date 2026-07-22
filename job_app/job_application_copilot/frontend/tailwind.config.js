/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        void:    "#0C0A09",
        surface: "#1C1917",
        elevated:"#292524",
        amber: {
          DEFAULT: "#F59E0B",
          light:   "#FBBF24",
        },
        emerald: { DEFAULT: "#10B981" },
        rose:    { DEFAULT: "#F43F5E" },
      },
      fontFamily: {
        display: ["'Playfair Display'", "serif"],
        body:    ["'Outfit'", "sans-serif"],
        mono:    ["'JetBrains Mono'", "monospace"],
      },
    },
  },
  plugins: [],
};
