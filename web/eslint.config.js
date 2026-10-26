import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/", "src/api/schema.d.ts", "test-results/", "playwright-report/"] },
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    rules: {
      // LLD-1 §11.3: tokens, the email and the password never go into browser storage.
      "no-restricted-globals": [
        "error",
        { name: "localStorage", message: "Nothing auth-related is stored in the browser (LLD-1 §11.3)." },
        { name: "sessionStorage", message: "Nothing auth-related is stored in the browser (LLD-1 §11.3)." },
      ],
    },
  },
);
