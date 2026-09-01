/**
 * @finbit/shared: the one definition of the FinBit API contract.
 *
 * The web app and the Expo app both import from here, so the wire types, the
 * route constants and the request signing exist exactly once. This package ships
 * TypeScript source rather than a build output, which is why the consumers alias
 * it through tsconfig paths and a bundler resolver instead of a package build
 * step (CONTRACT_MOBILE_ADMIN.md section 2.4).
 *
 * Nothing here touches react, react-native or the DOM.
 */

export * from './types';
export * from './endpoints';
export * from './signing';
export * from './storage';
export * from './client';
