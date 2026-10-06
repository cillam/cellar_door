/**
 * The only module allowed to talk to the backend -- CLAUDE.md: "The API
 * client (lib/api.ts) is the only place that talks to the backend.
 * Components never fetch directly."
 *
 * Step 5 adds the two photo-pipeline calls, both SSE streams read over a
 * POST. They use expo/fetch, whose response body is a real ReadableStream
 * on native; React Native's own fetch can only hand back a whole body.
 *
 * The event types below are hand-written, not generated. CLAUDE.md wants
 * API types from openapi-typescript, but both routes return a bare
 * StreamingResponse, so the OpenAPI schema describes none of these
 * payloads. They mirror SPEC.md's "POST /items/from-photo" and ".../resume"
 * sections and backend/app/routers/items.py's `_sse_event_for_update`, and
 * every payload is checked at runtime before it is typed. The generator
 * is deferred to step 6, where POST /items has a schema worth generating.
 */

import { fetch as expoFetch } from 'expo/fetch';

import { supabase } from './supabase';

const backendUrl = process.env.EXPO_PUBLIC_BACKEND_URL;

if (!backendUrl) {
  throw new Error(
    'Missing EXPO_PUBLIC_BACKEND_URL. Set CELLAR_DOOR_MOBILE_ENV_FILE to your env file, ' +
      'or create mobile/.env -- see .env.example.',
  );
}

export const BACKEND_URL = backendUrl;

export const CATEGORIES = ['wine', 'halloween', 'other'] as const;
export type Category = (typeof CATEGORIES)[number];

export type AwaitCategoryData = {
  thread_id: string;
  suggested_category: Category;
  confidence: number;
  ttl_seconds: number;
};

/**
 * The `complete` event's payload (backend ItemDraft). Exactly one of
 * wine/halloween/other is set, matching `category`; their fields are left
 * loose here because the step 6 form is what gives them real types.
 */
export type ItemDraft = {
  category: Category;
  photo_url: string;
  title: string;
  description: string;
  confidence_scores: Record<string, number>;
  wine: Record<string, unknown> | null;
  halloween: Record<string, unknown> | null;
  other: Record<string, unknown> | null;
};

export type PipelineEvent =
  | { event: 'session'; data: { thread_id: string } }
  | { event: 'category_router'; data: { suggested_category: Category; confidence: number } }
  | { event: 'await_category'; data: AwaitCategoryData }
  | { event: 'identify'; data: { best_guess: string; confidence: number } }
  | {
      event: 'ocr';
      data: { state: 'text_present' | 'text_unreadable' | 'no_text'; text: string; reason: string | null };
    }
  | { event: 'generate_description_and_title'; data: { title: string; description: string } }
  | {
      event: 'extract_structured';
      data: { fields: Record<string, unknown> | null; confidence_scores: Record<string, number> };
    }
  | { event: 'complete'; data: ItemDraft };

export type StreamOptions = {
  /** Called for every recognised event, in arrival order, terminal one included. */
  onEvent?: (event: PipelineEvent) => void;
  signal?: AbortSignal;
};

/**
 * - `auth`: no signed-in session to take a JWT from; nothing was sent.
 * - `network`: the request failed before any response came back.
 * - `http`: the backend answered with a non-2xx; `status` is set.
 * - `stream`: a 200 came back but the stream was cut short, ended without
 *   its terminal event, or carried an event that doesn't match SPEC.md.
 *   The backend has no error event, so this is the only sign that a node
 *   failed.
 * - `aborted`: the caller's signal fired.
 */
export type ApiErrorKind = 'auth' | 'network' | 'http' | 'stream' | 'aborted';

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;

  constructor(kind: ApiErrorKind, message: string, status: number | null = null) {
    super(message);
    // Keeps `instanceof ApiError` true if classes are ever down-levelled.
    Object.setPrototypeOf(this, ApiError.prototype);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isCategory(value: unknown): value is Category {
  return CATEGORIES.some((category) => category === value);
}

function isNumberRecord(value: unknown): value is Record<string, number> {
  return isRecord(value) && Object.values(value).every((entry) => typeof entry === 'number');
}

function isNullableRecord(value: unknown): value is Record<string, unknown> | null {
  return value === null || isRecord(value);
}

/**
 * Narrows one decoded SSE event to its SPEC.md shape. Returns null for an
 * event name this client doesn't know (a node added later shouldn't break
 * an older app); throws for a known event whose payload is wrong.
 */
function toPipelineEvent(name: string, data: unknown): PipelineEvent | null {
  const malformed = new ApiError('stream', `The server sent a "${name}" event this app can't read.`);
  if (!isRecord(data)) throw malformed;

  switch (name) {
    case 'session': {
      const { thread_id } = data;
      if (typeof thread_id !== 'string') throw malformed;
      return { event: name, data: { thread_id } };
    }
    case 'category_router': {
      const { suggested_category, confidence } = data;
      if (!isCategory(suggested_category) || typeof confidence !== 'number') throw malformed;
      return { event: name, data: { suggested_category, confidence } };
    }
    case 'await_category': {
      const { thread_id, suggested_category, confidence, ttl_seconds } = data;
      if (
        typeof thread_id !== 'string' ||
        !isCategory(suggested_category) ||
        typeof confidence !== 'number' ||
        typeof ttl_seconds !== 'number'
      ) {
        throw malformed;
      }
      return { event: name, data: { thread_id, suggested_category, confidence, ttl_seconds } };
    }
    case 'identify': {
      const { best_guess, confidence } = data;
      if (typeof best_guess !== 'string' || typeof confidence !== 'number') throw malformed;
      return { event: name, data: { best_guess, confidence } };
    }
    case 'ocr': {
      const { state, text, reason } = data;
      if (
        (state !== 'text_present' && state !== 'text_unreadable' && state !== 'no_text') ||
        typeof text !== 'string' ||
        (reason !== null && reason !== undefined && typeof reason !== 'string')
      ) {
        throw malformed;
      }
      return { event: name, data: { state, text, reason: reason ?? null } };
    }
    case 'generate_description_and_title': {
      const { title, description } = data;
      if (typeof title !== 'string' || typeof description !== 'string') throw malformed;
      return { event: name, data: { title, description } };
    }
    case 'extract_structured': {
      const { fields, confidence_scores } = data;
      if (!isNullableRecord(fields) || !isNumberRecord(confidence_scores)) throw malformed;
      return { event: name, data: { fields, confidence_scores } };
    }
    case 'complete': {
      const { category, photo_url, title, description, confidence_scores } = data;
      const wine = data.wine ?? null;
      const halloween = data.halloween ?? null;
      const other = data.other ?? null;
      if (
        !isCategory(category) ||
        typeof photo_url !== 'string' ||
        typeof title !== 'string' ||
        typeof description !== 'string' ||
        !isNumberRecord(confidence_scores) ||
        !isNullableRecord(wine) ||
        !isNullableRecord(halloween) ||
        !isNullableRecord(other)
      ) {
        throw malformed;
      }
      return {
        event: name,
        data: { category, photo_url, title, description, confidence_scores, wine, halloween, other },
      };
    }
    default:
      return null;
  }
}

type RawSseEvent = { name: string; data: string };

/**
 * Incremental SSE decoder: feed it response chunks, get back the events
 * each chunk completed. Chunk boundaries are arbitrary -- they can fall
 * mid-line or mid-character -- so bytes are only decoded up to the last
 * newline received (0x0A never occurs inside a multi-byte UTF-8
 * character) and the rest waits for the next chunk.
 */
function createSseDecoder(): (chunk: Uint8Array) => RawSseEvent[] {
  const decoder = new TextDecoder();
  let pending = new Uint8Array(0);
  let name = '';
  let dataLines: string[] = [];

  return (chunk) => {
    const bytes = new Uint8Array(pending.length + chunk.length);
    bytes.set(pending);
    bytes.set(chunk, pending.length);

    const lastNewline = bytes.lastIndexOf(0x0a);
    if (lastNewline === -1) {
      pending = bytes;
      return [];
    }
    pending = bytes.slice(lastNewline + 1);
    const lines = decoder.decode(bytes.slice(0, lastNewline + 1)).split('\n');
    lines.pop(); // the empty string after the final newline

    const events: RawSseEvent[] = [];
    for (const rawLine of lines) {
      const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
      if (line === '') {
        // Blank line: dispatch what has accumulated.
        if (dataLines.length > 0) {
          events.push({ name: name || 'message', data: dataLines.join('\n') });
        }
        name = '';
        dataLines = [];
        continue;
      }
      if (line.startsWith(':')) continue; // comment / keep-alive

      const colon = line.indexOf(':');
      const field = colon === -1 ? line : line.slice(0, colon);
      let value = colon === -1 ? '' : line.slice(colon + 1);
      if (value.startsWith(' ')) value = value.slice(1);

      if (field === 'event') name = value;
      else if (field === 'data') dataLines.push(value);
    }
    return events;
  };
}

function transportError(err: unknown, signal: AbortSignal | undefined): ApiError {
  if (err instanceof ApiError) return err;
  if (signal?.aborted) return new ApiError('aborted', 'The request was cancelled.');
  return new ApiError('network', err instanceof Error ? err.message : 'Network request failed.');
}

/** FastAPI error bodies are `{"detail": "..."}`; fall back to the status alone. */
async function httpError(response: { status: number; text: () => Promise<string> }): Promise<ApiError> {
  let detail = '';
  try {
    const body: unknown = JSON.parse(await response.text());
    if (isRecord(body) && typeof body.detail === 'string') detail = body.detail;
  } catch {
    // Not JSON, or the body couldn't be read: the status is all there is.
  }
  const message = `The server returned ${response.status}${detail ? `: ${detail}` : '.'}`;
  return new ApiError('http', message, response.status);
}

/**
 * POSTs `body` and reads the SSE response until `terminal` arrives, which
 * it returns. Stops reading there rather than waiting for the server to
 * close the connection.
 */
async function postEventStream(
  path: string,
  body: Record<string, string>,
  terminal: PipelineEvent['event'],
  { onEvent, signal }: StreamOptions,
): Promise<PipelineEvent> {
  // Read at call time, not passed in: getSession() refreshes an expired
  // token, and callers then have no token to put in an effect's deps.
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) {
    throw new ApiError('auth', 'You are signed out. Sign in and try again.');
  }

  const url = `${BACKEND_URL}${path}`;
  let response: Awaited<ReturnType<typeof expoFetch>>;
  try {
    response = await expoFetch(url, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    const failure = transportError(err, signal);
    if (failure.kind !== 'network') throw failure;
    // Name the URL: a request that never left the device is as likely a
    // wrong EXPO_PUBLIC_BACKEND_URL as a dead connection.
    throw new ApiError('network', `${failure.message} (POST ${url})`);
  }

  if (!response.ok) throw await httpError(response);
  if (!response.body) throw new ApiError('stream', 'The server sent an empty response.');

  const reader = response.body.getReader();
  const decode = createSseDecoder();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const raw of decode(value)) {
        let payload: unknown;
        try {
          payload = JSON.parse(raw.data);
        } catch {
          throw new ApiError('stream', `The server sent a "${raw.name}" event this app can't read.`);
        }
        const event = toPipelineEvent(raw.name, payload);
        if (!event) continue;
        onEvent?.(event);
        if (event.event === terminal) return event;
      }
    }
  } catch (err) {
    const failure = transportError(err, signal);
    if (failure.kind !== 'network') throw failure;
    // The response had started, so this is a cut-short stream, not a
    // request that failed to send: the run exists on the backend.
    throw new ApiError('stream', `The connection dropped mid-stream: ${failure.message}`);
  } finally {
    void reader.cancel().catch(() => {});
  }

  throw new ApiError('stream', `The connection ended before "${terminal}" arrived.`);
}

/**
 * POST /items/from-photo. Runs the category router and resolves with the
 * `await_category` payload once the graph has paused for the user.
 * `storagePath` is the bucket-prefixed path uploadPhoto() returns.
 *
 * Every call starts a new paid pipeline run.
 */
export async function streamFromPhoto(
  storagePath: string,
  options: StreamOptions = {},
): Promise<AwaitCategoryData> {
  const event = await postEventStream(
    '/items/from-photo',
    { storage_path: storagePath },
    'await_category',
    options,
  );
  if (event.event !== 'await_category') {
    throw new ApiError('stream', 'The connection ended before "await_category" arrived.');
  }
  return event.data;
}

/**
 * POST /items/from-photo/{thread_id}/resume. Resumes the paused graph with
 * the user's category and resolves with the `complete` payload -- per
 * SPEC.md the only payload that should populate the form.
 *
 * A thread can be resumed once: a second call for the same thread gets a
 * 409, including after a first call whose stream was cut short.
 */
export async function streamResume(
  threadId: string,
  category: Category,
  options: StreamOptions = {},
): Promise<ItemDraft> {
  const event = await postEventStream(
    `/items/from-photo/${encodeURIComponent(threadId)}/resume`,
    { category },
    'complete',
    options,
  );
  if (event.event !== 'complete') {
    throw new ApiError('stream', 'The connection ended before "complete" arrived.');
  }
  return event.data;
}
