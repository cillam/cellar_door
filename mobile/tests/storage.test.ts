import { uploadPhoto } from '../lib/storage';

jest.mock('expo-crypto', () => ({
  randomUUID: () => 'test-uuid',
}));

const mockFetch = jest.fn();
global.fetch = mockFetch as unknown as typeof fetch;

const mockCreateSignedUploadUrl = jest.fn();
const mockUploadToSignedUrl = jest.fn();
// lib/supabase.ts throws at import time if EXPO_PUBLIC_SUPABASE_* env
// vars are unset, which they are in this jest process (no app.config.ts
// dotenv loading happens here) -- mock the whole module rather than let
// the real client construct itself, same pattern as the auth-context
// mocks elsewhere in this repo.
jest.mock('../lib/supabase', () => ({
  supabase: {
    storage: {
      from: () => ({
        createSignedUploadUrl: mockCreateSignedUploadUrl,
        uploadToSignedUrl: mockUploadToSignedUrl,
      }),
    },
  },
}));

describe('uploadPhoto', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockResolvedValue({ arrayBuffer: async () => new ArrayBuffer(8) });
  });

  it('requests a signed URL for the bucket-relative key and uploads with it', async () => {
    mockCreateSignedUploadUrl.mockResolvedValue({
      data: { signedUrl: 'https://x.supabase.co/...', path: 'user-a-id/test-uuid.jpg', token: 'tok' },
      error: null,
    });
    mockUploadToSignedUrl.mockResolvedValue({ data: { path: 'user-a-id/test-uuid.jpg' }, error: null });

    const result = await uploadPhoto('user-a-id', 'file:///photo.jpg');

    expect(mockCreateSignedUploadUrl).toHaveBeenCalledWith('user-a-id/test-uuid.jpg');
    expect(mockUploadToSignedUrl).toHaveBeenCalledWith(
      'user-a-id/test-uuid.jpg',
      'tok',
      expect.any(ArrayBuffer),
      { contentType: 'image/jpeg' },
    );
    // Bucket-prefixed for the backend contract -- distinct from the
    // bucket-relative key sent to supabase-js above.
    expect(result).toEqual({ storagePath: 'photos/user-a-id/test-uuid.jpg' });
  });

  it('throws without requesting a signed URL when the file reads back empty', async () => {
    mockFetch.mockResolvedValue({ arrayBuffer: async () => new ArrayBuffer(0) });

    await expect(uploadPhoto('user-a-id', 'file:///photo.jpg')).rejects.toThrow(
      'Could not read the photo file.',
    );
    expect(mockCreateSignedUploadUrl).not.toHaveBeenCalled();
  });

  it('throws when createSignedUploadUrl fails, without attempting the upload', async () => {
    mockCreateSignedUploadUrl.mockResolvedValue({
      data: null,
      error: { message: 'insufficient permissions' },
    });

    await expect(uploadPhoto('user-a-id', 'file:///photo.jpg')).rejects.toThrow(
      'insufficient permissions',
    );
    expect(mockUploadToSignedUrl).not.toHaveBeenCalled();
  });

  it('throws when uploadToSignedUrl fails', async () => {
    mockCreateSignedUploadUrl.mockResolvedValue({
      data: { signedUrl: 'https://x.supabase.co/...', path: 'user-a-id/test-uuid.jpg', token: 'tok' },
      error: null,
    });
    mockUploadToSignedUrl.mockResolvedValue({ data: null, error: { message: 'network error' } });

    await expect(uploadPhoto('user-a-id', 'file:///photo.jpg')).rejects.toThrow('network error');
  });
});
