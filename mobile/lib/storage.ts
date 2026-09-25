import * as Crypto from 'expo-crypto';
import { File } from 'expo-file-system';

import { supabase } from './supabase';

const BUCKET = 'photos';

export type UploadResult = {
  /**
   * Bucket-prefixed, e.g. "photos/<user_id>/<uuid>.jpg" -- the exact
   * shape POST /items/from-photo's storage_path field expects, matching
   * the backend's own StorageClient/BaseItem.photo_url convention (see
   * backend/app/storage.py's module docstring: every path this app
   * passes around already has the bucket name as its own leading
   * segment). Not the same string as the key used below to talk to
   * supabase-js -- see that variable's comment.
   */
  storagePath: string;
};

/**
 * Uploads a captured/resized photo to Supabase Storage via the signed-
 * upload-URL flow SPEC.md's data flow specifies (request a signed URL,
 * then upload directly to Storage with it) rather than a plain
 * authenticated .upload() call.
 */
export async function uploadPhoto(userId: string, localUri: string): Promise<UploadResult> {
  const uuid = Crypto.randomUUID();
  // Bucket-relative -- what supabase-js's .from(BUCKET) calls want, since
  // selecting the bucket already scopes them. Deliberately named and
  // commented separately from storagePath below: sending this shorter
  // key to the backend instead would fail its "storage_path must start
  // with photos/<user_id>/" check (SPEC.md's auth section), and sending
  // the bucket-prefixed one to supabase-js would double the segment.
  const key = `${userId}/${uuid}.jpg`;
  const storagePath = `${BUCKET}/${key}`;

  // expo-file-system's current File class implements Blob natively,
  // including arrayBuffer() -- reads the local file straight into the
  // ArrayBuffer shape supabase-js's upload methods want. No base64
  // round-trip needed (the base64 + base64-arraybuffer-decode pattern
  // in Supabase's own React Native guide predates this API and works
  // around older FileSystem/Blob limitations that don't apply here).
  const file = new File(localUri);
  const body = await file.arrayBuffer();

  const { data: signed, error: signError } = await supabase.storage
    .from(BUCKET)
    .createSignedUploadUrl(key);
  if (signError || !signed) {
    throw new Error(signError?.message ?? 'Could not get an upload URL.');
  }

  const { error: uploadError } = await supabase.storage
    .from(BUCKET)
    .uploadToSignedUrl(key, signed.token, body, { contentType: 'image/jpeg' });
  if (uploadError) {
    throw new Error(uploadError.message);
  }

  return { storagePath };
}
