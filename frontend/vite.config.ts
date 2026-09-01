import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

/*
  packages/shared ships TypeScript source rather than a build output
  (CONTRACT_MOBILE_ADMIN.md section 2.4), so the bare package name is aliased to
  its entry file. Because the alias rewrites the specifier to an absolute source
  path, Vite treats the package as project source and not as a dependency to
  pre-bundle, which is what we want: the .ts goes through the normal transform
  pipeline and editing the API contract hot reloads like any other source file.
  Its own dependency, @noble/hashes, is a plain package and is still pre-bundled
  from packages/shared/node_modules where it is installed.

  This file is type checked by tsconfig.node.json, which carries no @types/node,
  so node:path and node:url cannot be imported here. import.meta.dirname is a
  Node 20.11 built-in and Vite 8 already requires Node 20.19 or newer, so it is
  always present; only its type is missing, which the declaration below adds.
  Write it exactly as "import.meta.dirname": Vite bundles this config to a temp
  file under node_modules and substitutes that expression with the real
  directory, so any other spelling, a destructure or a cast included, silently
  resolves against the temp file instead. Forward slashes are correct on Windows
  too, since Vite normalises every path it is given.
*/
declare global {
  interface ImportMeta {
    readonly dirname: string;
  }
}

const SHARED_ENTRY = `${import.meta.dirname}/../packages/shared/src/index.ts`;

// Dev server runs on 5173, which is the origin allowed by the backend CORS config.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@finbit/shared': SHARED_ENTRY,
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    fs: {
      /*
        Entries are resolved against the project root, and setting this replaces
        the default allowlist. The repo root covers both frontend/ and the
        shared package, without which the dev server refuses to serve any file
        outside frontend/ and the app fails to boot.
      */
      allow: ['..'],
    },
  },
  preview: {
    port: 4173,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
