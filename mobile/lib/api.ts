/**
 * The only module allowed to talk to the backend -- CLAUDE.md: "The API
 * client (lib/api.ts) is the only place that talks to the backend.
 * Components never fetch directly."
 *
 * Empty in step 1: real typed request/response functions land alongside
 * the endpoints that need them (from step 4 onward). Response/request
 * types should come from a generated OpenAPI client (openapi-typescript
 * against the backend's schema) -- that's a new dependency + build step,
 * to be proposed separately when the first real endpoint call is added.
 */

const backendUrl = process.env.EXPO_PUBLIC_BACKEND_URL;

if (!backendUrl) {
  throw new Error(
    'Missing EXPO_PUBLIC_BACKEND_URL. Set CELLAR_DOOR_MOBILE_ENV_FILE to your env file, ' +
      'or create mobile/.env -- see .env.example.',
  );
}

export const BACKEND_URL = backendUrl;
