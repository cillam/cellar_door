import { fetch as expoFetch } from 'expo/fetch';

import type * as Api from '../lib/api';

jest.mock('expo/fetch', () => ({
  fetch: jest.fn(),
}));

const mockGetSession = jest.fn();
// lib/supabase.ts throws at import time without its env vars -- mock the
// whole module, same pattern as storage.test.ts.
jest.mock('../lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: () => mockGetSession(),
    },
  },
}));

const mockFetch = expoFetch as unknown as jest.Mock;

// lib/api.ts throws at import time without EXPO_PUBLIC_BACKEND_URL, and
// `import` is hoisted above any assignment, so set it and then require.
process.env.EXPO_PUBLIC_BACKEND_URL = 'https://backend.test';
const { ApiError, streamFromPhoto, streamResume } = require('../lib/api') as typeof Api;

const encoder = new TextEncoder();

/** A fetch response whose body hands out the given chunks, then ends. */
function streamResponse(chunks: (string | Uint8Array)[], status = 200) {
  const queue = chunks.map((chunk) => (typeof chunk === 'string' ? encoder.encode(chunk) : chunk));
  const cancel = jest.fn(async () => {});
  return {
    response: {
      ok: status >= 200 && status < 300,
      status,
      body: {
        getReader: () => ({
          read: async () => {
            const value = queue.shift();
            return value ? { done: false, value } : { done: true, value: undefined };
          },
          cancel,
        }),
      },
    },
    cancel,
  };
}

function errorResponse(status: number, body: unknown) {
  return { ok: false, status, body: null, text: async () => JSON.stringify(body) };
}

const SESSION = 'event: session\ndata: {"thread_id": "thread-1"}\n\n';
const ROUTER = 'event: category_router\ndata: {"suggested_category": "wine", "confidence": 0.94}\n\n';
const AWAIT =
  'event: await_category\ndata: {"thread_id": "thread-1", "suggested_category": "wine", ' +
  '"confidence": 0.94, "ttl_seconds": 3600}\n\n';

const DRAFT = {
  category: 'wine',
  photo_url: 'photos/user-a-id/some-uuid.jpg',
  title: 'Beringer Cabernet Sauvignon 2019',
  description: 'A Napa red.',
  confidence_scores: { vintage: 0.9 },
  wine: { producer: 'Beringer', vintage: 2019 },
  halloween: null,
  other: null,
};

async function rejection(promise: Promise<unknown>): Promise<Api.ApiError> {
  try {
    await promise;
  } catch (err) {
    if (err instanceof ApiError) return err;
    throw err;
  }
  throw new Error('expected the call to reject');
}

describe('lib/api', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockGetSession.mockReset();
    mockGetSession.mockResolvedValue({ data: { session: { access_token: 'jwt-abc' } }, error: null });
  });

  describe('streamFromPhoto', () => {
    it('POSTs the storage path with the JWT and returns the await_category payload', async () => {
      mockFetch.mockResolvedValue(streamResponse([SESSION, ROUTER, AWAIT]).response);
      const onEvent = jest.fn();

      const result = await streamFromPhoto('photos/user-a-id/some-uuid.jpg', { onEvent });

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const [url, init] = mockFetch.mock.calls[0];
      expect(url).toBe('https://backend.test/items/from-photo');
      expect(init.method).toBe('POST');
      expect(init.headers.Authorization).toBe('Bearer jwt-abc');
      expect(init.headers['Content-Type']).toBe('application/json');
      expect(JSON.parse(init.body)).toEqual({ storage_path: 'photos/user-a-id/some-uuid.jpg' });

      expect(result).toEqual({
        thread_id: 'thread-1',
        suggested_category: 'wine',
        confidence: 0.94,
        ttl_seconds: 3600,
      });
      expect(onEvent.mock.calls.map(([event]) => event.event)).toEqual([
        'session',
        'category_router',
        'await_category',
      ]);
      expect(onEvent.mock.calls[1][0].data).toEqual({ suggested_category: 'wine', confidence: 0.94 });
    });

    it('reassembles events split across chunks and delivered several to a chunk', async () => {
      const whole = SESSION + ROUTER + AWAIT;
      const cut = SESSION.length + 20;
      mockFetch.mockResolvedValue(
        streamResponse([whole.slice(0, 9), whole.slice(9, cut), whole.slice(cut)]).response,
      );
      const onEvent = jest.fn();

      const result = await streamFromPhoto('photos/u/p.jpg', { onEvent });

      expect(result.thread_id).toBe('thread-1');
      expect(onEvent).toHaveBeenCalledTimes(3);
    });

    it('ignores comment lines and event names it does not know, and accepts CRLF', async () => {
      mockFetch.mockResolvedValue(
        streamResponse([
          ': keep-alive\n\n',
          'event: some_future_node\ndata: {"x": 1}\n\n',
          SESSION.replace(/\n/g, '\r\n'),
          AWAIT,
        ]).response,
      );
      const onEvent = jest.fn();

      await streamFromPhoto('photos/u/p.jpg', { onEvent });

      expect(onEvent.mock.calls.map(([event]) => event.event)).toEqual(['session', 'await_category']);
    });

    it('stops reading once await_category arrives', async () => {
      const { response, cancel } = streamResponse([SESSION, AWAIT, ROUTER]);
      mockFetch.mockResolvedValue(response);
      const onEvent = jest.fn();

      await streamFromPhoto('photos/u/p.jpg', { onEvent });

      expect(onEvent).toHaveBeenCalledTimes(2);
      expect(cancel).toHaveBeenCalled();
    });

    it('rejects with kind "stream" when the stream ends before await_category', async () => {
      mockFetch.mockResolvedValue(streamResponse([SESSION, ROUTER]).response);

      const err = await rejection(streamFromPhoto('photos/u/p.jpg'));

      expect(err.kind).toBe('stream');
    });

    it('rejects with kind "stream" when a known event has the wrong shape', async () => {
      mockFetch.mockResolvedValue(
        streamResponse(['event: await_category\ndata: {"suggested_category": "cheese"}\n\n']).response,
      );

      const err = await rejection(streamFromPhoto('photos/u/p.jpg'));

      expect(err.kind).toBe('stream');
    });

    it('rejects with kind "http" and the status on a non-200', async () => {
      mockFetch.mockResolvedValue(
        errorResponse(403, { detail: 'storage_path does not belong to the authenticated user' }),
      );

      const err = await rejection(streamFromPhoto('photos/u/p.jpg'));

      expect(err.kind).toBe('http');
      expect(err.status).toBe(403);
      expect(err.message).toContain('storage_path does not belong');
    });

    it('rejects with kind "network" when the request itself fails', async () => {
      mockFetch.mockRejectedValue(new Error('Network request failed'));

      const err = await rejection(streamFromPhoto('photos/u/p.jpg'));

      expect(err.kind).toBe('network');
      expect(err.message).toContain('Network request failed');
      expect(err.message).toContain('https://backend.test/items/from-photo');
    });

    // Not "network": a 200 had already come back, so the run started. For
    // resume that makes it unretryable (the thread is spent), which is how
    // callers treat "stream".
    it('rejects with kind "stream" when the connection drops mid-stream', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        body: {
          getReader: () => ({
            read: jest
              .fn()
              .mockResolvedValueOnce({ done: false, value: encoder.encode(SESSION) })
              .mockRejectedValueOnce(new Error('stream was reset: CANCEL')),
            cancel: async () => {},
          }),
        },
      });

      const err = await rejection(streamFromPhoto('photos/u/p.jpg'));

      expect(err.kind).toBe('stream');
      expect(err.message).toContain('stream was reset: CANCEL');
    });

    it('rejects with kind "auth" without calling the backend when signed out', async () => {
      mockGetSession.mockResolvedValue({ data: { session: null }, error: null });

      const err = await rejection(streamFromPhoto('photos/u/p.jpg'));

      expect(err.kind).toBe('auth');
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('passes the abort signal through and rejects with kind "aborted" once it fires', async () => {
      const controller = new AbortController();
      mockFetch.mockImplementation(async () => {
        controller.abort();
        throw new Error('The operation was aborted.');
      });

      const err = await rejection(streamFromPhoto('photos/u/p.jpg', { signal: controller.signal }));

      expect(mockFetch.mock.calls[0][1].signal).toBe(controller.signal);
      expect(err.kind).toBe('aborted');
    });
  });

  describe('streamResume', () => {
    it('POSTs the category to the thread and returns only the complete payload', async () => {
      // A two-byte character split across chunks must survive reassembly.
      const identify = encoder.encode(
        'event: identify\ndata: {"best_guess": "Côte des Bar Champagne", "confidence": 0.88}\n\n',
      );
      const splitAt = identify.indexOf(0xc3) + 1;
      mockFetch.mockResolvedValue(
        streamResponse([
          'event: ocr\ndata: {"state": "no_text", "text": "", "reason": "no_text"}\n\n',
          identify.slice(0, splitAt),
          identify.slice(splitAt),
          'event: generate_description_and_title\ndata: {"title": "T", "description": "D"}\n\n',
          'event: extract_structured\ndata: {"fields": {"producer": "Beringer"}, "confidence_scores": {}}\n\n',
          `event: complete\ndata: ${JSON.stringify(DRAFT)}\n\n`,
        ]).response,
      );
      const onEvent = jest.fn();

      const draft = await streamResume('thread-1', 'wine', { onEvent });

      const [url, init] = mockFetch.mock.calls[0];
      expect(url).toBe('https://backend.test/items/from-photo/thread-1/resume');
      expect(init.headers.Authorization).toBe('Bearer jwt-abc');
      expect(JSON.parse(init.body)).toEqual({ category: 'wine' });
      expect(draft).toEqual(DRAFT);
      expect(onEvent.mock.calls.map(([event]) => event.event)).toEqual([
        'ocr',
        'identify',
        'generate_description_and_title',
        'extract_structured',
        'complete',
      ]);
      expect(onEvent.mock.calls[1][0].data.best_guess).toBe('Côte des Bar Champagne');
    });

    it.each([401, 403, 409, 410])('rejects with kind "http" and status %i', async (status) => {
      mockFetch.mockResolvedValue(errorResponse(status, { detail: 'nope' }));

      const err = await rejection(streamResume('thread-1', 'wine'));

      expect(err.kind).toBe('http');
      expect(err.status).toBe(status);
    });

    it('rejects with kind "stream" when the stream ends before complete', async () => {
      mockFetch.mockResolvedValue(
        streamResponse(['event: identify\ndata: {"best_guess": "x", "confidence": 0.5}\n\n']).response,
      );

      const err = await rejection(streamResume('thread-1', 'wine'));

      expect(err.kind).toBe('stream');
    });
  });
});
