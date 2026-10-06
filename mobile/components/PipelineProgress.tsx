import { useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import type { Category, PipelineEvent } from '../lib/api';
import { ApiError, CATEGORIES, streamFromPhoto, streamResume } from '../lib/api';

type PipelineProgressProps = {
  /** Bucket-prefixed path from uploadPhoto(). */
  storagePath: string;
};

type RouterResult = { category: Category; confidence: number };

type Retry = { stage: 'router' } | { stage: 'resume'; threadId: string; category: Category };

type Phase =
  | { name: 'routing' }
  | { name: 'awaiting_category'; threadId: string }
  | { name: 'extracting'; category: Category }
  // retry is null when asking again can't help (or can't be done safely).
  // detail is the underlying error, shown small beneath the message.
  | {
      name: 'error';
      message: string;
      detail: string | null;
      retry: Retry | null;
      category: Category | null;
    };

type StageStatus = 'pending' | 'active' | 'done';

/** Nodes of the second stream that report progress, in display order. */
type ResumeNode = 'identify' | 'ocr' | 'generate_description_and_title' | 'extract_structured';

const STAGE_LABELS: Record<ResumeNode, Record<StageStatus, string>> = {
  identify: {
    pending: 'Identify item',
    active: 'Identifying item...',
    done: 'Item identified',
  },
  ocr: {
    pending: 'Read label text',
    active: 'Reading label text...',
    done: 'Label text read',
  },
  generate_description_and_title: {
    pending: 'Write description',
    active: 'Writing description...',
    done: 'Description generated',
  },
  extract_structured: {
    pending: 'Extract details',
    active: 'Extracting details...',
    done: 'Details extracted',
  },
};

const STATUS_GLYPHS: Record<StageStatus, string> = { pending: '○', active: '⋯', done: '✓' };

function isResumeNode(event: PipelineEvent['event']): event is ResumeNode {
  // hasOwnProperty, not `in`: `in` also matches inherited names.
  return Object.prototype.hasOwnProperty.call(STAGE_LABELS, event);
}

function percent(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

/**
 * The backend only emits an event when a node finishes, so "in progress"
 * is inferred from the graph's shape (SPEC.md): identify and ocr start
 * together, the description waits for both, extraction waits for the
 * description. Statuses are keyed by node name, never by arrival order.
 */
function stageStatuses(
  category: Category,
  finished: ReadonlySet<ResumeNode>,
): { node: ResumeNode; status: StageStatus }[] {
  const status = (node: ResumeNode, ready: boolean): StageStatus =>
    finished.has(node) ? 'done' : ready ? 'active' : 'pending';

  const stages = [
    { node: 'identify' as const, status: status('identify', true) },
    { node: 'ocr' as const, status: status('ocr', true) },
    {
      node: 'generate_description_and_title' as const,
      status: status('generate_description_and_title', finished.has('identify') && finished.has('ocr')),
    },
  ];
  // extract_structured is skipped for "other" and never emits an event.
  if (category === 'other') return stages;
  return [
    ...stages,
    {
      node: 'extract_structured' as const,
      status: status('extract_structured', finished.has('generate_description_and_title')),
    },
  ];
}

type ErrorDescription = { message: string; detail: string | null; retry: Retry | null };

function describeError(err: unknown, retry: Retry): ErrorDescription {
  const detail = err instanceof Error ? err.message : null;
  return { ...friendlyError(err, retry), detail };
}

function friendlyError(err: unknown, retry: Retry): { message: string; retry: Retry | null } {
  const resuming = retry.stage === 'resume';
  if (!(err instanceof ApiError)) {
    return { message: 'Something went wrong. Please try again.', retry };
  }

  switch (err.kind) {
    case 'auth':
      return { message: 'You are signed out. Sign in again to add this item.', retry: null };
    case 'network':
      return { message: "Couldn't reach the server. Check your connection and try again.", retry };
    case 'stream':
      // A resumed thread can't be resumed again (409), and there is no
      // endpoint to fetch a finished run, so this one is not retryable.
      return resuming
        ? {
            message:
              "The connection was lost before the item was finished. This run can't be picked up again, so start over with the photo.",
            retry: null,
          }
        : { message: 'The connection ended before a category came back. Try again.', retry };
    case 'http':
      break;
    case 'aborted':
      return { message: 'Cancelled.', retry: null };
  }

  switch (err.status) {
    case 401:
      return { message: 'Your session has expired. Sign in again to add this item.', retry: null };
    case 403:
      return {
        message: resuming
          ? 'This item was started from a different account. Start over to add it.'
          : "This photo doesn't belong to your account. Start over to add it.",
        retry: null,
      };
    case 404:
      return { message: "The uploaded photo couldn't be found. Start over and take it again.", retry: null };
    case 409:
      return {
        message: 'This photo has already been processed. Start over to add it again.',
        retry: null,
      };
    case 410:
      return {
        message: 'The category was confirmed too late and this run has expired. Start over to add it.',
        retry: null,
      };
    default: {
      const status = err.status ?? 0;
      return {
        message: `The server returned an error (${status}).`,
        // 5xx may be transient; a 4xx would fail the same way again.
        retry: status >= 500 ? retry : null,
      };
    }
  }
}

/**
 * Pipeline phase of the add-item flow: runs the category router, lets the
 * user confirm the category, then runs the rest and hands the `complete`
 * payload to the form route.
 *
 * Each from-photo call is a paid pipeline run, so nothing here starts one
 * implicitly more than once per storage path: the mount effect is guarded
 * by a ref, and every other start is a button press. Leaving the screen
 * aborts the open stream; nothing is retried automatically, and nothing
 * is done on backgrounding -- if the OS drops the connection it surfaces
 * as an error the user chooses how to act on.
 */
export function PipelineProgress({ storagePath }: PipelineProgressProps) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>({ name: 'routing' });
  const [routerResult, setRouterResult] = useState<RouterResult | null>(null);
  const [selected, setSelected] = useState<Category | null>(null);
  const [finished, setFinished] = useState<ReadonlySet<ResumeNode>>(new Set());

  const startedForRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Guards against a second press landing before the first one's state
  // update has re-rendered the button away.
  const requestInFlightRef = useRef(false);

  const runRouter = useCallback(async () => {
    if (requestInFlightRef.current) return;
    requestInFlightRef.current = true;
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    setPhase({ name: 'routing' });
    setRouterResult(null);
    setSelected(null);
    try {
      const awaiting = await streamFromPhoto(storagePath, {
        signal,
        onEvent: (event) => {
          if (signal.aborted || event.event !== 'category_router') return;
          setRouterResult({
            category: event.data.suggested_category,
            confidence: event.data.confidence,
          });
        },
      });
      if (signal.aborted) return;
      setRouterResult({ category: awaiting.suggested_category, confidence: awaiting.confidence });
      setSelected(awaiting.suggested_category);
      setPhase({ name: 'awaiting_category', threadId: awaiting.thread_id });
    } catch (err) {
      if (signal.aborted) return;
      setPhase({ name: 'error', category: null, ...describeError(err, { stage: 'router' }) });
    } finally {
      requestInFlightRef.current = false;
    }
  }, [storagePath]);

  const runResume = useCallback(
    async (threadId: string, category: Category) => {
      if (requestInFlightRef.current) return;
      requestInFlightRef.current = true;
      const controller = new AbortController();
      abortRef.current = controller;
      const { signal } = controller;

      setPhase({ name: 'extracting', category });
      setFinished(new Set());
      try {
        const draft = await streamResume(threadId, category, {
          signal,
          onEvent: (event) => {
            if (signal.aborted) return;
            const node = event.event;
            if (isResumeNode(node)) {
              setFinished((previous) => new Set(previous).add(node));
            }
          },
        });
        if (signal.aborted) return;
        // replace, not push: going back from the form should not land on
        // a finished progress screen. Step 6 owns the destination.
        router.replace({ pathname: '/item/new', params: { draft: JSON.stringify(draft) } });
      } catch (err) {
        if (signal.aborted) return;
        setPhase({
          name: 'error',
          category,
          ...describeError(err, { stage: 'resume', threadId, category }),
        });
      } finally {
        requestInFlightRef.current = false;
      }
    },
    [router],
  );

  useEffect(() => {
    if (startedForRef.current === storagePath) return;
    startedForRef.current = storagePath;
    void runRouter();
  }, [storagePath, runRouter]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const confirmedCategory =
    phase.name === 'extracting' || phase.name === 'error' ? phase.category : null;

  return (
    <View style={styles.container}>
      <View style={styles.stages}>
        <StageRow
          testID="stage-category_router"
          status={routerResult ? 'done' : phase.name === 'routing' ? 'active' : 'pending'}
          label={
            routerResult
              ? `Category identified (${routerResult.category}, ${percent(routerResult.confidence)})`
              : 'Identifying category...'
          }
        />
        {confirmedCategory ? (
          <>
            <StageRow
              testID="stage-await_category"
              status="done"
              label={`Category confirmed (${confirmedCategory})`}
            />
            {stageStatuses(confirmedCategory, finished).map(({ node, status }) => {
              // Once the run has failed nothing is still in progress.
              const shown = phase.name === 'error' && status === 'active' ? 'pending' : status;
              return (
                <StageRow
                  key={node}
                  testID={`stage-${node}`}
                  status={shown}
                  label={STAGE_LABELS[node][shown]}
                />
              );
            })}
          </>
        ) : null}
      </View>

      {phase.name === 'routing' || phase.name === 'extracting' ? (
        <ActivityIndicator size="large" />
      ) : null}

      {phase.name === 'awaiting_category' ? (
        <View style={styles.picker}>
          <Text style={styles.prompt}>What is this item?</Text>
          <View style={styles.options}>
            {CATEGORIES.map((category) => {
              const isSelected = category === selected;
              return (
                <Pressable
                  key={category}
                  testID={`category-option-${category}`}
                  accessibilityRole="radio"
                  accessibilityState={{ selected: isSelected }}
                  style={[styles.option, isSelected && styles.optionSelected]}
                  onPress={() => setSelected(category)}
                >
                  <Text style={[styles.optionText, isSelected && styles.optionTextSelected]}>
                    {category}
                  </Text>
                </Pressable>
              );
            })}
          </View>
          <Pressable
            testID="confirm-category-button"
            style={styles.button}
            onPress={() => {
              if (selected) void runResume(phase.threadId, selected);
            }}
          >
            <Text style={styles.buttonText}>Continue</Text>
          </Pressable>
        </View>
      ) : null}

      {phase.name === 'error' ? (
        <View style={styles.errorBlock}>
          <Text style={styles.errorText} testID="pipeline-error">
            {phase.message}
          </Text>
          {phase.detail ? (
            <Text style={styles.errorDetail} testID="pipeline-error-detail" selectable>
              {phase.detail}
            </Text>
          ) : null}
          {phase.retry ? (
            <Pressable
              testID="retry-button"
              style={styles.button}
              onPress={() => {
                const { retry } = phase;
                if (retry?.stage === 'resume') void runResume(retry.threadId, retry.category);
                else if (retry) void runRouter();
              }}
            >
              <Text style={styles.buttonText}>Try Again</Text>
            </Pressable>
          ) : null}
          {/* Back to the add screen, where the photo is still showing
              with Retake/Confirm. */}
          <Pressable
            testID="start-over-button"
            style={styles.secondaryButton}
            onPress={() => router.back()}
          >
            <Text style={styles.secondaryButtonText}>Start Over</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

type StageRowProps = {
  testID: string;
  status: StageStatus;
  label: string;
};

function StageRow({ testID, status, label }: StageRowProps) {
  return (
    <View style={styles.stage} testID={testID} accessible accessibilityValue={{ text: status }}>
      <Text style={[styles.glyph, status === 'done' && styles.glyphDone]}>{STATUS_GLYPHS[status]}</Text>
      <Text style={[styles.stageText, status === 'pending' && styles.stageTextPending]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    padding: 24,
    gap: 24,
  },
  stages: {
    gap: 12,
  },
  stage: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  glyph: {
    width: 20,
    fontSize: 16,
    textAlign: 'center',
    color: '#555',
  },
  glyphDone: {
    color: '#2e7d32',
  },
  stageText: {
    flex: 1,
    fontSize: 16,
    fontWeight: '600',
  },
  stageTextPending: {
    color: '#888',
    fontWeight: '400',
  },
  picker: {
    gap: 16,
  },
  prompt: {
    fontSize: 16,
    fontWeight: '600',
  },
  options: {
    flexDirection: 'row',
    gap: 8,
  },
  option: {
    flex: 1,
    borderWidth: 1,
    borderColor: '#6b2d5c',
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: 'center',
  },
  optionSelected: {
    backgroundColor: '#6b2d5c',
  },
  optionText: {
    fontSize: 15,
    color: '#6b2d5c',
    textTransform: 'capitalize',
  },
  optionTextSelected: {
    color: '#fff',
    fontWeight: '600',
  },
  errorBlock: {
    gap: 12,
  },
  errorText: {
    fontSize: 16,
    color: '#c0392b',
    textAlign: 'center',
  },
  errorDetail: {
    fontSize: 12,
    color: '#555',
    textAlign: 'center',
  },
  button: {
    backgroundColor: '#6b2d5c',
    borderRadius: 8,
    paddingVertical: 14,
    paddingHorizontal: 28,
    alignItems: 'center',
  },
  buttonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  secondaryButton: {
    borderRadius: 8,
    paddingVertical: 14,
    paddingHorizontal: 28,
    alignItems: 'center',
  },
  secondaryButtonText: {
    color: '#6b2d5c',
    fontSize: 16,
    fontWeight: '600',
  },
});
