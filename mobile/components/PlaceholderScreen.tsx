import { StyleSheet, Text, View } from 'react-native';

type PlaceholderScreenProps = {
  name: string;
};

/**
 * Step 1 navigation-shell placeholder -- renders just the screen name so
 * routing can be verified before any real UI exists. Each route below is
 * replaced with real UI screen-by-screen in later steps (auth in step 2,
 * camera in step 3, etc) per KICKOFF_PROMPT_FRONTEND.md.
 */
export function PlaceholderScreen({ name }: PlaceholderScreenProps) {
  return (
    <View style={styles.container}>
      <Text style={styles.text}>{name}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  text: {
    fontSize: 18,
    fontWeight: '600',
  },
});
