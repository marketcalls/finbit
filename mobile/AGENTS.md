# FinBit mobile

## Expo SDK 54, deliberately

This project targets **Expo SDK 54**. Read the versioned docs at
https://docs.expo.dev/versions/v54.0.0/ before writing any code.

Do not bump the SDK without checking which version the Expo Go apps in the App
Store and Play Store can actually open:

```bash
curl -s https://api.expo.dev/v2/versions/latest | python -c "import sys,json;print(json.load(sys.stdin)['data']['expoGoSdkVersion'])"
```

Newer SDKs ship Expo Go only as sideloadable GitHub releases, so a project ahead
of that version cannot be opened by a store-installed Expo Go. That is why every
version in `package.json` is pinned to the set in `CONTRACT_MOBILE_ADMIN.md`
section 2.1.

Add a package with `npx expo install <pkg>`, never `npm install`, so Expo picks
the SDK 54 compatible version. The one exception is `@noble/hashes`, which is not
an Expo module and has no SDK-specific build.

If `npx expo-doctor` reports a version mismatch, fix it with
`npx expo install --check`. Never hand-edit a version to silence it.

## Why the lockfile and the override exist

`package-lock.json` is committed and comes from the working SDK 54 prototype.
Install from it (`npm install`, or `npm ci`) rather than deleting it, because a
fresh unlocked resolve of the gluestack tree currently produces a broken app:

- `react-aria-components@1.21.0` depends on `react-aria@3.52.0`, which is not on
  the registry, so the install fails outright. The `overrides` entry pinning
  `@adobe/react-spectrum` to `3.47.3` is what keeps a lock-less install working:
  that release pins the pair of versions that are actually published.
- Newer resolutions of `@gluestack-ui/*` also drop several `@react-native-aria`
  packages that `@gluestack-ui/actionsheet` imports, and Metro then fails to
  bundle with "unable to resolve @react-native-aria/overlays". TypeScript stays
  happy throughout, so this only shows up when the app is actually bundled.

After changing dependencies, prove the app still bundles rather than trusting the
typecheck:

```bash
npx expo export --platform android --output-dir dist   # dist/ is git-ignored
```

## Monorepo wiring

The app lives inside the FinBit repo and imports wire types, route constants and
request signing from `@finbit/shared`, which is TypeScript source with no build
step. Two files make that work and both must stay in step:

- `metro.config.js` adds the repo root to `watchFolders`, lists both
  `mobile/node_modules` and the root `node_modules` in `resolver.nodeModulesPaths`
  and maps `@finbit/shared` in `resolver.extraNodeModules`.
- `tsconfig.json` carries the matching `paths` entry.

A "module not found: @finbit/shared" from Metro when TypeScript is happy means
the Metro half drifted. Clear the cache with `npx expo start -c` after changing
either file, because Metro caches resolution aggressively.

## House rules

- No emoji, no em dashes, no en dashes, anywhere: code, comments, strings, logs.
- No raw hex colour in a component. Every colour comes from
  `src/theme/tokens.ts`, read through `useThemeColors()`.
- Never log or throw a device secret, a token or a signature. The signing layer
  is in `@finbit/shared` and already avoids this; keep it that way.
- There is no login screen and there never will be one. The device registers
  itself in the background on first launch. A failed handshake shows a retry
  screen (`DeviceAuthProvider`), not a sign-in form.

## Commands

```bash
npm install            # from mobile/
npx expo start         # LAN, the usual case
npx expo start --tunnel
npx tsc --noEmit
npx expo-doctor
```

The backend runs separately: `uv run uvicorn app.main:app --reload` from
`backend/`. The app finds it through `EXPO_PUBLIC_API_URL`, or by taking the Expo
dev server host and swapping in port 8000.
