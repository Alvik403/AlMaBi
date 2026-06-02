export default {
  content: ["./templates/**/*.html", "./assets/src/**/*.js"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "sans-serif"],
      },
      colors: {
        brand: {
          50: "#f0f9ff",
          100: "#e0f2fe",
          500: "#0ea5e9",
          600: "#0284c7",
          700: "#0369a1",
          800: "#075985",
          900: "#0c4a6e",
        },
        ineff: {
          light: "#fff7ed",
          border: "#fed7aa",
          text: "#c2410c",
        },
      },
    },
  },
};
