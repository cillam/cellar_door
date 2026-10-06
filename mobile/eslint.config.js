// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');

module.exports = defineConfig([
  expoConfig,
  {
    // .expo/ holds generated files (typed routes), not code we write.
    ignores: ['dist/*', '.expo/*'],
  },
  {
    files: ['tests/**'],
    rules: {
      // jest.mock() factories are hoisted above imports, so anything they
      // need has to be require()d inside the factory.
      '@typescript-eslint/no-require-imports': 'off',
      // Mock components are anonymous stubs; a display name adds nothing.
      'react/display-name': 'off',
    },
  },
]);
