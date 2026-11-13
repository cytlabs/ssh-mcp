import { build } from "esbuild";

await build({
  entryPoints: ["frontend/main.js"],
  outfile: "src/ssh_mcp/static/app.js",
  bundle: true,
  minify: true,
  legalComments: "eof",
  target: "es2022",
  define: {
    "process.env.NODE_ENV": '"production"',
    __VUE_OPTIONS_API__: "true",
    __VUE_PROD_DEVTOOLS__: "false",
    __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: "false",
  },
});
