import js from '@eslint/js'
import vue from 'eslint-plugin-vue'
import ts from 'typescript-eslint'
import prettier from 'eslint-config-prettier'

export default [
  { ignores: ['dist/**', 'coverage/**', 'node_modules/**'] },
  js.configs.recommended,
  ...ts.configs.recommended,
  ...vue.configs['flat/recommended'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: { parser: ts.parser },
      globals: {
        URL: 'readonly',
        document: 'readonly',
        setTimeout: 'readonly',
        HTMLInputElement: 'readonly',
      },
    },
    rules: {
      'no-undef': 'off', // Vue 的 TypeScript 脚本由 vue-tsc 检查未定义符号（含 DOM 类型）。
      '@typescript-eslint/no-explicit-any': 'error',
      'vue/multi-word-component-names': ['error', { ignores: ['App'] }],
    },
  },
  { files: ['**/*.ts'], rules: { '@typescript-eslint/no-explicit-any': 'error' } },
  prettier,
]
