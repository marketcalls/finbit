/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the FinBit API, for example http://127.0.0.1:8000 */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

/*
  React 19 moved the JSX namespace under React.JSX, so the bare global JSX
  namespace no longer exists. The component signatures frozen in contract
  section 11 are written as ": JSX.Element", so keep that spelling valid by
  aliasing the global name back onto React's namespace.
*/
declare namespace JSX {
  type Element = import('react').JSX.Element;
}
