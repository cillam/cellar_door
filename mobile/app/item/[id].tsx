import { useLocalSearchParams } from 'expo-router';

import { PlaceholderScreen } from '../../components/PlaceholderScreen';

export default function ItemDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <PlaceholderScreen name={`Item Detail (${id})`} />;
}
