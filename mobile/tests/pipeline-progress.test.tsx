import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { PipelineProgress } from '../components/PipelineProgress';
import type { ItemDraft, PipelineEvent, StreamOptions } from '../lib/api';
import { ApiError, streamFromPhoto, streamResume } from '../lib/api';

jest.mock('../lib/supabase', () => ({ supabase: {} }));
jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));

// Keep the real ApiError (the component narrows on it) and replace only
// the two calls. lib/api.ts throws at import without its env var.
jest.mock('../lib/api', () => {
  process.env.EXPO_PUBLIC_BACKEND_URL = 'https://backend.test';
  return {
    ...jest.requireActual('../lib/api'),
    streamFromPhoto: jest.fn(),
    streamResume: jest.fn(),
  };
});

const mockBack = jest.fn();
const mockReplace = jest.fn();
jest.mock('expo-router', () => ({
  useRouter: () => ({ back: mockBack, replace: mockReplace }),
}));

const mockStreamFromPhoto = streamFromPhoto as jest.Mock;
const mockStreamResume = streamResume as jest.Mock;

const STORAGE_PATH = 'photos/user-a-id/some-uuid.jpg';

const AWAITING = {
  thread_id: 'thread-1',
  suggested_category: 'wine' as const,
  confidence: 0.94,
  ttl_seconds: 3600,
};

const DRAFT: ItemDraft = {
  category: 'wine',
  photo_url: STORAGE_PATH,
  title: 'Beringer Cabernet Sauvignon 2019',
  description: 'A Napa red.',
  confidence_scores: { vintage: 0.9 },
  wine: { producer: 'Beringer', vintage: 2019 },
  halloween: null,
  other: null,
};

/** A stream call the test drives by hand: emit events, then settle it. */
function controlledStream<T>(mock: jest.Mock) {
  let options: StreamOptions = {};
  let resolve: (value: T) => void = () => {};
  let reject: (err: unknown) => void = () => {};
  mock.mockImplementationOnce((...args: unknown[]) => {
    options = (args[args.length - 1] as StreamOptions | undefined) ?? {};
    return new Promise<T>((res, rej) => {
      resolve = res;
      reject = rej;
    });
  });
  return {
    emit: (event: PipelineEvent) => act(async () => options.onEvent?.(event)),
    resolve: (value: T) => act(async () => resolve(value)),
    reject: (err: unknown) => act(async () => reject(err)),
    signal: () => options.signal,
  };
}

/** Renders and walks the first stream through to the category picker. */
async function renderAtCategoryPicker() {
  mockStreamFromPhoto.mockResolvedValueOnce(AWAITING);
  await render(<PipelineProgress storagePath={STORAGE_PATH} />);
  await waitFor(() => expect(screen.getByTestId('confirm-category-button')).toBeTruthy());
}

/** The nearest onPress above a host element, found the way fireEvent finds it. */
function pressHandler(instance: ReturnType<typeof screen.getByTestId>): () => void {
  for (let fiber = instance.unstable_fiber; fiber; fiber = fiber.return) {
    const onPress: unknown = fiber.memoizedProps?.onPress;
    if (typeof onPress === 'function') return () => onPress();
  }
  throw new Error('No onPress handler found.');
}

function isSelected(testID: string): boolean {
  return screen.getByTestId(testID).props.accessibilityState?.selected === true;
}

describe('PipelineProgress', () => {
  beforeEach(() => {
    mockStreamFromPhoto.mockReset();
    mockStreamResume.mockReset();
    mockBack.mockReset();
    mockReplace.mockReset();
  });

  describe('router phase', () => {
    it('starts the pipeline with the storage path and shows the router result as it arrives', async () => {
      const stream = controlledStream<typeof AWAITING>(mockStreamFromPhoto);

      await render(<PipelineProgress storagePath={STORAGE_PATH} />);

      expect(mockStreamFromPhoto).toHaveBeenCalledTimes(1);
      expect(mockStreamFromPhoto.mock.calls[0][0]).toBe(STORAGE_PATH);
      expect(screen.getByText('Identifying category...')).toBeTruthy();

      await stream.emit({
        event: 'category_router',
        data: { suggested_category: 'wine', confidence: 0.94 },
      });

      expect(screen.getByText('Category identified (wine, 94%)')).toBeTruthy();
      expect(screen.queryByTestId('confirm-category-button')).toBeNull();
    });

    it('does not start a second run when re-rendered with the same storage path', async () => {
      mockStreamFromPhoto.mockResolvedValue(AWAITING);

      await render(<PipelineProgress storagePath={STORAGE_PATH} />);
      await waitFor(() => expect(screen.getByTestId('confirm-category-button')).toBeTruthy());
      await screen.rerender(<PipelineProgress storagePath={STORAGE_PATH} />);
      await screen.rerender(<PipelineProgress storagePath={STORAGE_PATH} />);

      expect(mockStreamFromPhoto).toHaveBeenCalledTimes(1);
    });

    it('aborts the stream on unmount and does nothing with a late result', async () => {
      const stream = controlledStream<typeof AWAITING>(mockStreamFromPhoto);
      await render(<PipelineProgress storagePath={STORAGE_PATH} />);

      await screen.unmount();

      expect(stream.signal()?.aborted).toBe(true);
      await stream.reject(new ApiError('aborted', 'The request was cancelled.'));
      expect(mockStreamFromPhoto).toHaveBeenCalledTimes(1);
      expect(mockStreamResume).not.toHaveBeenCalled();
    });

    it('shows a retryable error on a network failure, and Try Again starts one new run', async () => {
      mockStreamFromPhoto.mockRejectedValueOnce(new ApiError('network', 'Network request failed'));
      await render(<PipelineProgress storagePath={STORAGE_PATH} />);
      await waitFor(() => expect(screen.getByTestId('pipeline-error')).toBeTruthy());
      expect(screen.getByText(/reach the server/)).toBeTruthy();
      // The underlying error stays visible; the friendly line alone can't
      // tell a bad backend URL from a dead connection.
      expect(screen.getByTestId('pipeline-error-detail').props.children).toBe('Network request failed');

      mockStreamFromPhoto.mockResolvedValueOnce(AWAITING);
      await fireEvent.press(screen.getByTestId('retry-button'));

      await waitFor(() => expect(screen.getByTestId('confirm-category-button')).toBeTruthy());
      expect(mockStreamFromPhoto).toHaveBeenCalledTimes(2);
    });

    it('shows a retryable error when the stream ends before the category arrives', async () => {
      mockStreamFromPhoto.mockRejectedValueOnce(new ApiError('stream', 'ended early'));

      await render(<PipelineProgress storagePath={STORAGE_PATH} />);

      await waitFor(() => expect(screen.getByText(/connection ended/i)).toBeTruthy());
      expect(screen.getByTestId('retry-button')).toBeTruthy();
    });

    it('offers only Start Over on a 403, which goes back', async () => {
      mockStreamFromPhoto.mockRejectedValueOnce(new ApiError('http', 'forbidden', 403));

      await render(<PipelineProgress storagePath={STORAGE_PATH} />);

      await waitFor(() => expect(screen.getByTestId('pipeline-error')).toBeTruthy());
      expect(screen.queryByTestId('retry-button')).toBeNull();
      await fireEvent.press(screen.getByTestId('start-over-button'));
      expect(mockBack).toHaveBeenCalledTimes(1);
      expect(mockStreamFromPhoto).toHaveBeenCalledTimes(1);
    });

    it('shows a retryable error with the status on a 500', async () => {
      mockStreamFromPhoto.mockRejectedValueOnce(new ApiError('http', 'boom', 500));

      await render(<PipelineProgress storagePath={STORAGE_PATH} />);

      await waitFor(() => expect(screen.getByText(/500/)).toBeTruthy());
      expect(screen.getByTestId('retry-button')).toBeTruthy();
    });
  });

  describe('category confirmation', () => {
    it("preselects the router's suggestion", async () => {
      await renderAtCategoryPicker();

      expect(screen.getByText('Category identified (wine, 94%)')).toBeTruthy();
      expect(isSelected('category-option-wine')).toBe(true);
      expect(isSelected('category-option-halloween')).toBe(false);
      expect(isSelected('category-option-other')).toBe(false);
      expect(mockStreamResume).not.toHaveBeenCalled();
    });

    it("resumes with the user's choice, not the suggestion, when they differ", async () => {
      await renderAtCategoryPicker();
      controlledStream<ItemDraft>(mockStreamResume);

      await fireEvent.press(screen.getByTestId('category-option-halloween'));
      expect(isSelected('category-option-halloween')).toBe(true);
      expect(isSelected('category-option-wine')).toBe(false);
      await fireEvent.press(screen.getByTestId('confirm-category-button'));

      expect(mockStreamResume).toHaveBeenCalledTimes(1);
      expect(mockStreamResume.mock.calls[0].slice(0, 2)).toEqual(['thread-1', 'halloween']);
      expect(screen.getByText('Category confirmed (halloween)')).toBeTruthy();
    });

    it('resumes only once when Continue is pressed twice', async () => {
      await renderAtCategoryPicker();
      controlledStream<ItemDraft>(mockStreamResume);
      const button = screen.getByTestId('confirm-category-button');

      // fireEvent.press re-renders between presses, which would remove the
      // button; call the handler twice in one tick instead, as two taps
      // landing before a re-render would.
      const onPress = pressHandler(button);
      await act(async () => {
        onPress();
        onPress();
      });

      expect(mockStreamResume).toHaveBeenCalledTimes(1);
      expect(mockStreamResume.mock.calls[0].slice(0, 2)).toEqual(['thread-1', 'wine']);
    });
  });

  describe('extraction phase', () => {
    async function renderResumed(category: 'wine' | 'halloween' | 'other' = 'wine') {
      await renderAtCategoryPicker();
      const stream = controlledStream<ItemDraft>(mockStreamResume);
      await fireEvent.press(screen.getByTestId(`category-option-${category}`));
      await fireEvent.press(screen.getByTestId('confirm-category-button'));
      return stream;
    }

    function status(node: string): string {
      return screen.getByTestId(`stage-${node}`).props.accessibilityValue?.text;
    }

    it('keys progress by node name, so ocr can finish before identify', async () => {
      const stream = await renderResumed();

      expect(status('identify')).toBe('active');
      expect(status('ocr')).toBe('active');
      expect(status('generate_description_and_title')).toBe('pending');
      expect(status('extract_structured')).toBe('pending');

      await stream.emit({ event: 'ocr', data: { state: 'no_text', text: '', reason: 'no_text' } });

      expect(status('ocr')).toBe('done');
      expect(status('identify')).toBe('active');
      expect(status('generate_description_and_title')).toBe('pending');

      await stream.emit({ event: 'identify', data: { best_guess: 'Beringer Cab', confidence: 0.88 } });

      expect(status('identify')).toBe('done');
      expect(status('generate_description_and_title')).toBe('active');

      await stream.emit({
        event: 'generate_description_and_title',
        data: { title: 'T', description: 'D' },
      });

      expect(status('generate_description_and_title')).toBe('done');
      expect(status('extract_structured')).toBe('active');

      await stream.emit({
        event: 'extract_structured',
        data: { fields: { producer: 'Beringer' }, confidence_scores: {} },
      });

      expect(status('extract_structured')).toBe('done');
      expect(mockReplace).not.toHaveBeenCalled();
    });

    it('has no extraction stage for "other", which skips that node', async () => {
      await renderResumed('other');

      expect(screen.getByTestId('stage-identify')).toBeTruthy();
      expect(screen.queryByTestId('stage-extract_structured')).toBeNull();
    });

    it('navigates to the form with the complete payload, and only that payload', async () => {
      const stream = await renderResumed();
      await stream.emit({
        event: 'generate_description_and_title',
        data: { title: 'An intermediate title', description: 'Intermediate' },
      });
      expect(mockReplace).not.toHaveBeenCalled();

      await stream.resolve(DRAFT);

      expect(mockReplace).toHaveBeenCalledTimes(1);
      const target = mockReplace.mock.calls[0][0];
      expect(target.pathname).toBe('/item/new');
      expect(JSON.parse(target.params.draft)).toEqual(DRAFT);
    });

    it('does not navigate when the screen unmounts before complete', async () => {
      const stream = await renderResumed();

      await screen.unmount();

      expect(stream.signal()?.aborted).toBe(true);
      await stream.resolve(DRAFT);
      expect(mockReplace).not.toHaveBeenCalled();
    });

    it.each([
      [401, /sign in again/i],
      [403, /different account/i],
      [409, /already been processed/i],
      [410, /expired/i],
    ])('shows a %i from resume with no retry', async (httpStatus, message) => {
      const stream = await renderResumed();

      await stream.reject(new ApiError('http', 'nope', httpStatus));

      expect(screen.getByText(message)).toBeTruthy();
      expect(screen.queryByTestId('retry-button')).toBeNull();
      expect(screen.getByTestId('start-over-button')).toBeTruthy();
      expect(mockReplace).not.toHaveBeenCalled();
    });

    it('says a stream that ends early cannot be picked up again, with no retry', async () => {
      const stream = await renderResumed();
      await stream.emit({ event: 'identify', data: { best_guess: 'x', confidence: 0.5 } });

      await stream.reject(new ApiError('stream', 'ended early'));

      expect(screen.getByText(/can't be picked up/i)).toBeTruthy();
      expect(screen.queryByTestId('retry-button')).toBeNull();
      expect(mockReplace).not.toHaveBeenCalled();
    });

    it('retries resume with the same thread and category after a network failure', async () => {
      const stream = await renderResumed('halloween');
      await stream.reject(new ApiError('network', 'Network request failed'));
      controlledStream<ItemDraft>(mockStreamResume);

      await fireEvent.press(screen.getByTestId('retry-button'));

      expect(mockStreamResume).toHaveBeenCalledTimes(2);
      expect(mockStreamResume.mock.calls[1].slice(0, 2)).toEqual(['thread-1', 'halloween']);
      expect(mockStreamFromPhoto).toHaveBeenCalledTimes(1);
    });
  });
});
