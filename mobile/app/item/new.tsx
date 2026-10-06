import { useLocalSearchParams } from 'expo-router';
import { ScrollView, StyleSheet, Text } from 'react-native';

/**
 * Step 5 placeholder for the prefilled form (step 6). Receives the
 * pipeline's `complete` payload as a JSON string in the `draft` route
 * param and shows it raw, so the hand-off can be checked on a device
 * before the form exists.
 */
export default function NewItemScreen() {
  const { draft } = useLocalSearchParams<{ draft?: string }>();

  let pretty = 'No draft was passed to this screen.';
  if (draft) {
    try {
      pretty = JSON.stringify(JSON.parse(draft), null, 2);
    } catch {
      pretty = 'The draft passed to this screen is not valid JSON.';
    }
  }

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.heading}>Pipeline complete</Text>
      <Text style={styles.payload} testID="draft-payload">
        {pretty}
      </Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: 24,
    gap: 12,
  },
  heading: {
    fontSize: 18,
    fontWeight: '600',
  },
  payload: {
    fontSize: 12,
    fontFamily: 'monospace',
    color: '#333',
  },
});
