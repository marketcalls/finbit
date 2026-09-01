/**
 * Metro configuration for the FinBit monorepo.
 *
 * Metro only reads files under the project root unless it is told otherwise, so
 * an untouched config cannot see `packages/shared` and every import of
 * `@finbit/shared` fails at bundle time with "module not found". The three
 * settings below are what CONTRACT_MOBILE_ADMIN.md section 2.4 requires:
 *
 *   watchFolders          the repo root, so shared source is watched and bundled
 *   nodeModulesPaths      mobile/node_modules first, then the repo root, so a
 *                         hoisted dependency still resolves
 *   extraNodeModules      the bare specifier `@finbit/shared` mapped to the
 *                         package directory, because the package is not
 *                         installed into node_modules by npm
 *
 * Paths are resolved from __dirname rather than written as literals: this repo
 * is developed on Windows and a POSIX-only path would break the build there.
 */

const { getDefaultConfig } = require('expo/metro-config');
const path = require('path');

const projectRoot = __dirname;
const workspaceRoot = path.resolve(projectRoot, '..');

const config = getDefaultConfig(projectRoot);

config.watchFolders = [workspaceRoot];

config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, 'node_modules'),
  path.resolve(workspaceRoot, 'node_modules'),
];

config.resolver.extraNodeModules = {
  ...config.resolver.extraNodeModules,
  '@finbit/shared': path.resolve(workspaceRoot, 'packages', 'shared'),
};

// Hierarchical lookup stays on, which is the default. packages/shared installs
// its own dependency (@noble/hashes) into packages/shared/node_modules, and
// disabling the walk up the filesystem would make that copy invisible to Metro
// while TypeScript still resolved it, which is the worst of both worlds.

// @finbit/shared and @noble/hashes are both exports-map packages whose subpath
// imports (for example "@noble/hashes/sha256") only resolve when Metro honours
// the "exports" field. SDK 54 enables this by default; it is pinned here so an
// upstream default flip cannot silently break signing.
config.resolver.unstable_enablePackageExports = true;

module.exports = config;
