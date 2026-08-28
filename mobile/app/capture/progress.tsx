import { useLocalSearchParams } from 'expo-router';

import { PlaceholderScreen } from '../../components/PlaceholderScreen';

/**
 * Placeholder for the pipeline progress screen -- real SSE progress UI
 * lands in step 5 (KICKOFF_PROMPT_FRONTEND.md). Step 4's upload logic
 * runs at the top of this screen once it lands, using the local
 * photoUri param captured here; step 3 (this one) just verifies the
 * capture -> confirm -> navigate handoff works end-to-end.
 */
export default function CaptureProgressScreen() {
  const { photoUri } = useLocalSearchParams<{ photoUri: string }>();
  return <PlaceholderScreen name={photoUri ? 'Pipeline Progress' : 'Pipeline Progress (no photo)'} />;
}
